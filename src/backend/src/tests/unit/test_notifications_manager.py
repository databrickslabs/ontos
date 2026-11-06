"""
Unit tests for NotificationsManager
"""
import pytest
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch, mock_open
from src.controller.notifications_manager import (
    NotificationNotDeletableError,
    NotificationNotFoundError,
    NotificationsManager,
)
from src.models.notifications import Notification, NotificationType
from src.models.users import UserInfo
from src.db_models.notifications import NotificationDb


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
    def manager(self, mock_settings_manager):
        """Create NotificationsManager instance for testing."""
        return NotificationsManager(settings_manager=mock_settings_manager)

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
        broadcast_notif = Mock(spec=NotificationDb)
        broadcast_notif.id = "notif-1"
        broadcast_notif.recipient = None
        broadcast_notif.title = "Broadcast"
        broadcast_notif.type = "info"
        broadcast_notif.created_at = datetime(2024, 1, 1)
        broadcast_notif.read = False
        broadcast_notif.can_delete = True
        broadcast_notif.subtitle = None
        broadcast_notif.description = None
        broadcast_notif.link = None
        broadcast_notif.action_type = None
        broadcast_notif.action_payload = None
        broadcast_notif.data = None
        broadcast_notif.target_roles = None

        manager._repo.get_multi.return_value = [broadcast_notif]

        result = manager.get_notifications(mock_db, user_info=None)

        assert len(result) == 1
        assert result[0].title == "Broadcast"

    def test_get_notifications_filtered_by_email(self, manager, sample_user_info):
        """Test getting notifications filtered by user email."""
        mock_db = Mock()
        
        # Create notifications
        user_notif = Mock(spec=NotificationDb)
        user_notif.id = "notif-1"
        user_notif.recipient = "user@example.com"
        user_notif.title = "User Notification"
        user_notif.type = "info"
        user_notif.created_at = datetime(2024, 1, 1)
        user_notif.read = False
        user_notif.can_delete = True
        user_notif.subtitle = None
        user_notif.description = None
        user_notif.link = None
        user_notif.action_type = None
        user_notif.action_payload = None
        user_notif.data = None
        user_notif.target_roles = None

        other_notif = Mock(spec=NotificationDb)
        other_notif.id = "notif-2"
        other_notif.recipient = "other@example.com"
        other_notif.title = "Other Notification"
        other_notif.type = "info"
        other_notif.created_at = datetime(2024, 1, 2)
        other_notif.read = False
        other_notif.can_delete = True
        other_notif.subtitle = None
        other_notif.description = None
        other_notif.link = None
        other_notif.action_type = None
        other_notif.action_payload = None
        other_notif.data = None
        other_notif.target_roles = None

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
        role_notif = Mock(spec=NotificationDb)
        role_notif.id = "notif-1"
        role_notif.recipient = "Data Consumer"
        role_notif.title = "Role Notification"
        role_notif.type = "info"
        role_notif.created_at = datetime(2024, 1, 1)
        role_notif.read = False
        role_notif.can_delete = True
        role_notif.subtitle = None
        role_notif.description = None
        role_notif.link = None
        role_notif.action_type = None
        role_notif.action_payload = None
        role_notif.data = None
        role_notif.target_roles = None

        manager._repo.get_multi.return_value = [role_notif]

        result = manager.get_notifications(mock_db, user_info=sample_user_info)

        assert len(result) == 1
        assert result[0].title == "Role Notification"

    def test_get_notifications_sorts_by_created_at(self, manager):
        """Test that notifications are sorted by created_at descending."""
        mock_db = Mock()
        
        # Create notifications with different timestamps
        notif1 = Mock(spec=NotificationDb)
        notif1.id = "notif-1"
        notif1.recipient = None
        notif1.title = "First"
        notif1.type = "info"
        notif1.created_at = datetime(2024, 1, 1)
        notif1.read = False
        notif1.can_delete = True
        notif1.subtitle = None
        notif1.description = None
        notif1.link = None
        notif1.action_type = None
        notif1.action_payload = None
        notif1.data = None
        notif1.target_roles = None

        notif2 = Mock(spec=NotificationDb)
        notif2.id = "notif-2"
        notif2.recipient = None
        notif2.title = "Second"
        notif2.type = "info"
        notif2.created_at = datetime(2024, 1, 3)
        notif2.read = False
        notif2.can_delete = True
        notif2.subtitle = None
        notif2.description = None
        notif2.link = None
        notif2.action_type = None
        notif2.action_payload = None
        notif2.data = None
        notif2.target_roles = None

        notif3 = Mock(spec=NotificationDb)
        notif3.id = "notif-3"
        notif3.recipient = None
        notif3.title = "Third"
        notif3.type = "info"
        notif3.created_at = datetime(2024, 1, 2)
        notif3.read = False
        notif3.can_delete = True
        notif3.subtitle = None
        notif3.description = None
        notif3.link = None
        notif3.action_type = None
        notif3.action_payload = None
        notif3.data = None
        notif3.target_roles = None

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
        
        notif_db = Mock(spec=NotificationDb)
        notif_db.id = "notif-123"
        notif_db.read = False
        
        manager._repo.get.return_value = notif_db

        result = manager.mark_as_read(mock_db, notification_id="notif-123")

        assert result is True
        assert notif_db.read is True
        mock_db.commit.assert_called_once()

    def test_mark_as_read_not_found(self, manager):
        """Test marking non-existent notification as read."""
        mock_db = Mock()
        manager._repo.get.return_value = None

        with pytest.raises(NotificationNotFoundError):
            manager.mark_as_read(mock_db, notification_id="nonexistent")

    # Mark All as Read Tests

    def test_mark_all_as_read_success(self, manager, sample_user_info):
        """Test marking all notifications as read for user."""
        mock_db = Mock()
        
        notif1 = Mock(spec=NotificationDb)
        notif1.id = "notif-1"
        notif1.recipient = "user@example.com"
        notif1.read = False
        notif1.title = "Test 1"
        notif1.type = "info"
        notif1.created_at = datetime(2024, 1, 1)
        notif1.can_delete = True
        notif1.subtitle = None
        notif1.description = None
        notif1.link = None
        notif1.action_type = None
        notif1.action_payload = None
        notif1.data = None
        notif1.target_roles = None

        notif2 = Mock(spec=NotificationDb)
        notif2.id = "notif-2"
        notif2.recipient = "user@example.com"
        notif2.read = False
        notif2.title = "Test 2"
        notif2.type = "info"
        notif2.created_at = datetime(2024, 1, 2)
        notif2.can_delete = True
        notif2.subtitle = None
        notif2.description = None
        notif2.link = None
        notif2.action_type = None
        notif2.action_payload = None
        notif2.data = None
        notif2.target_roles = None

        manager._repo.get_multi.return_value = [notif1, notif2]

        result = manager.mark_all_as_read(mock_db, user_info=sample_user_info)

        assert result == 2
        assert notif1.read is True
        assert notif2.read is True

    # Delete Notification Tests

    def test_delete_notification_success(self, manager):
        """Test deleting a notification."""
        mock_db = Mock()
        
        notif_db = Mock(spec=NotificationDb)
        notif_db.id = "notif-123"
        notif_db.can_delete = True
        
        manager._repo.get.return_value = notif_db
        manager._repo.remove.return_value = notif_db

        result = manager.delete_notification(mock_db, notification_id="notif-123")

        assert result is True
        manager._repo.remove.assert_called_once()

    def test_delete_notification_not_found(self, manager):
        """Test deleting non-existent notification."""
        mock_db = Mock()
        manager._repo.get.return_value = None

        with pytest.raises(NotificationNotFoundError):
            manager.delete_notification(mock_db, notification_id="nonexistent")

    def test_delete_notification_cannot_delete(self, manager):
        """Test trying to delete a notification marked as non-deletable.

        Raises rather than returning False so the route can distinguish it
        from "not found" and answer 403 instead of 404 (see #675).
        """
        mock_db = Mock()

        notif_db = Mock(spec=NotificationDb)
        notif_db.id = "notif-123"
        notif_db.can_delete = False

        manager._repo.get.return_value = notif_db

        with pytest.raises(NotificationNotDeletableError):
            manager.delete_notification(mock_db, notification_id="notif-123")

        manager._repo.remove.assert_not_called()

    def test_delete_notification_admin_override(self, manager):
        """Admins may delete a non-deletable notification (#675)."""
        mock_db = Mock()

        notif_db = Mock(spec=NotificationDb)
        notif_db.id = "notif-123"
        notif_db.can_delete = False

        manager._repo.get.return_value = notif_db
        manager._repo.remove.return_value = notif_db

        result = manager.delete_notification(
            mock_db, notification_id="notif-123", is_admin=True
        )

        assert result is True
        manager._repo.remove.assert_called_once()

