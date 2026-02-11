"""
Unit tests for NotificationsManager
"""
import pytest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock
from src.controller.notifications_manager import NotificationsManager
from src.models.notifications import Notification, NotificationType
from src.models.users import UserInfo
from src.db_models.notifications import NotificationDb


def _make_notif_db(**kwargs):
    """Create a mock NotificationDb with all attributes needed for Notification.model_validate."""
    defaults = {
        "id": "notif-1",
        "recipient": None,
        "title": "Test",
        "type": "info",
        "created_at": datetime(2024, 1, 1),
        "read": False,
        "can_delete": True,
        "subtitle": None,
        "description": None,
        "message": None,
        "link": None,
        "action_type": None,
        "action_payload": None,
        "data": None,
        "target_roles": None,
        "updated_at": None,
        "recipient_role_id": None,
        "recipient_role_name": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestNotificationsManager:
    """Test suite for NotificationsManager."""

    @pytest.fixture
    def mock_settings_manager(self):
        """Create mock settings manager."""
        manager = Mock()
        manager.list_app_roles.return_value = []
        return manager

    @pytest.fixture
    def mock_repository(self):
        """Create mock notification repository."""
        return Mock()

    @pytest.fixture
    def manager(self, mock_settings_manager, mock_repository):
        """Create NotificationsManager instance for testing."""
        manager = NotificationsManager(settings_manager=mock_settings_manager)
        manager._repo = mock_repository  # Replace real repo with mock for unit testing
        return manager

    @pytest.fixture
    def sample_notification(self):
        """Sample notification object."""
        return Notification(
            id="notif-123",
            recipient="user@example.com",
            title="Test Notification",
            subtitle="Subtitle",
            description="Test description",
            link="/test/link",
            type=NotificationType.INFO,
            created_at=datetime(2024, 1, 1, 0, 0, 0),
            read=False,
            can_delete=True,
        )

    @pytest.fixture
    def sample_user_info(self):
        """Sample user info."""
        return UserInfo(
            username="testuser",
            email="user@example.com",
            user="testuser",
            ip="127.0.0.1",
            groups=["users", "data_consumers"],
        )

    # Initialization Tests

    def test_manager_initialization(self, mock_settings_manager):
        """Test manager initializes with settings manager."""
        manager = NotificationsManager(settings_manager=mock_settings_manager)
        assert manager._settings_manager == mock_settings_manager

    # Get Notifications Tests

    def test_get_notifications_empty(self, manager):
        """Test getting notifications when none exist."""
        mock_db = Mock()
        manager._repo.get_multi.return_value = []

        result = manager.get_notifications(mock_db)

        assert result == []

    def test_get_notifications_broadcast_only(self, manager):
        """Test getting broadcast notifications without user info."""
        mock_db = Mock()
        
        # Create notification DB objects
        broadcast_notif = _make_notif_db(id="notif-1", recipient=None, title="Broadcast")

        manager._repo.get_multi.return_value = [broadcast_notif]

        result = manager.get_notifications(mock_db, user_info=None)

        assert len(result) == 1
        assert result[0].title == "Broadcast"

    def test_get_notifications_filtered_by_email(self, manager, sample_user_info):
        """Test getting notifications filtered by user email."""
        mock_db = Mock()
        
        # Create notifications
        user_notif = _make_notif_db(id="notif-1", recipient="user@example.com", title="User Notification")
        other_notif = _make_notif_db(
            id="notif-2",
            recipient="other@example.com",
            title="Other Notification",
            created_at=datetime(2024, 1, 2),
        )

        manager._repo.get_multi.return_value = [user_notif, other_notif]

        result = manager.get_notifications(mock_db, user_info=sample_user_info)

        # Should only get notifications for this user
        assert len(result) == 1
        assert result[0].recipient == "user@example.com"

    def test_get_notifications_filtered_by_role(self, manager, sample_user_info, mock_settings_manager):
        """Test getting notifications filtered by user role."""
        mock_db = Mock()
        
        # Mock role
        mock_role = Mock()
        mock_role.name = "Data Consumer"
        mock_role.assigned_groups = ["data_consumers"]
        mock_settings_manager.list_app_roles.return_value = [mock_role]

        # Create role-targeted notification
        role_notif = _make_notif_db(
            id="notif-1", recipient="Data Consumer", title="Role Notification"
        )

        manager._repo.get_multi.return_value = [role_notif]

        result = manager.get_notifications(mock_db, user_info=sample_user_info)

        assert len(result) == 1
        assert result[0].title == "Role Notification"

    def test_get_notifications_sorts_by_created_at(self, manager):
        """Test that notifications are sorted by created_at descending."""
        mock_db = Mock()
        
        # Create notifications with different timestamps
        notif1 = _make_notif_db(id="notif-1", title="First", created_at=datetime(2024, 1, 1))
        notif2 = _make_notif_db(id="notif-2", title="Second", created_at=datetime(2024, 1, 3))
        notif3 = _make_notif_db(id="notif-3", title="Third", created_at=datetime(2024, 1, 2))

        manager._repo.get_multi.return_value = [notif1, notif2, notif3]

        result = manager.get_notifications(mock_db)

        # Should be sorted newest first
        assert result[0].title == "Second"
        assert result[1].title == "Third"
        assert result[2].title == "First"

    # Mark as Read Tests

    def test_mark_as_read_success(self, manager):
        """Test marking notification as read."""
        mock_db = Mock()
        
        notif_db = _make_notif_db(id="notif-123", read=False, title="Test")
        
        def mock_update(db, db_obj, obj_in):
            for k, v in obj_in.items():
                setattr(db_obj, k, v)
            return db_obj
        
        manager._repo.get.return_value = notif_db
        manager._repo.update.side_effect = mock_update

        result = manager.mark_notification_read(db=mock_db, notification_id="notif-123")

        assert result is not None
        assert notif_db.read is True
        mock_db.commit.assert_called_once()

    def test_mark_as_read_not_found(self, manager):
        """Test marking non-existent notification as read."""
        mock_db = Mock()
        manager._repo.get.return_value = None

        result = manager.mark_notification_read(db=mock_db, notification_id="nonexistent")

        assert result is None

    # Mark All as Read Tests

    def test_mark_all_as_read_success(self, manager, sample_user_info):
        """Test marking all notifications as read for user."""
        mock_db = Mock()
        
        notif1 = _make_notif_db(id="notif-1", recipient="user@example.com", read=False, title="Test 1")
        notif2 = _make_notif_db(
            id="notif-2",
            recipient="user@example.com",
            read=False,
            title="Test 2",
            created_at=datetime(2024, 1, 2),
        )

        def mock_update(db, db_obj, obj_in):
            for k, v in obj_in.items():
                setattr(db_obj, k, v)
            return db_obj

        manager._repo.get_multi.return_value = [notif1, notif2]
        manager._repo.update.side_effect = mock_update

        result = manager.mark_all_as_read(mock_db, user_info=sample_user_info)

        assert result == 2
        assert notif1.read is True
        assert notif2.read is True

    # Delete Notification Tests

    def test_delete_notification_success(self, manager):
        """Test deleting a notification."""
        mock_db = Mock()
        
        notif_db = _make_notif_db(id="notif-123", can_delete=True)
        
        manager._repo.get.return_value = notif_db
        manager._repo.remove.return_value = notif_db

        result = manager.delete_notification(mock_db, notification_id="notif-123")

        assert result is True
        manager._repo.remove.assert_called_once()

    def test_delete_notification_not_found(self, manager):
        """Test deleting non-existent notification."""
        mock_db = Mock()
        manager._repo.get.return_value = None

        result = manager.delete_notification(mock_db, notification_id="nonexistent")

        assert result is False

    def test_delete_notification_cannot_delete(self, manager):
        """Test trying to delete a notification marked as non-deletable."""
        mock_db = Mock()
        
        notif_db = _make_notif_db(id="notif-123", can_delete=False)
        
        manager._repo.get.return_value = notif_db

        result = manager.delete_notification(mock_db, notification_id="notif-123")

        assert result is False
        manager._repo.remove.assert_not_called()

