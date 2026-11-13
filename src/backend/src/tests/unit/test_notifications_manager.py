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


def _db_notif(id, title="Test", recipient=None, created_at=datetime(2024, 1, 1), **kw):
    """A notification row as the repository returns it."""
    fields = dict(
        id=id, type="info", title=title, subtitle=None, description=None, message=None,
        link=None, created_at=created_at, updated_at=None, read=False, can_delete=True,
        recipient=recipient, recipient_role_id=None, recipient_role_name=None,
        target_roles=None, action_type=None, action_payload=None, data=None,
    )
    fields.update(kw)
    return SimpleNamespace(**fields)


def _role(name, groups=(), users=()):
    return SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111", name=name,
        assigned_groups=list(groups), assigned_users=list(users),
    )


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
        mgr = NotificationsManager(settings_manager=mock_settings_manager)
        mgr._repo = Mock()
        return mgr

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
        manager._repo.get_multi.return_value = []

        assert manager.get_notifications(Mock()) == []

    def test_get_notifications_broadcast_only(self, manager):
        """Without user info only broadcast (no recipient) notifications are returned."""
        manager._repo.get_multi.return_value = [
            _db_notif("notif-1", "Broadcast"),
            _db_notif("notif-2", "Personal", recipient="user@example.com"),
        ]

        result = manager.get_notifications(Mock(), user_info=None)

        assert [n.title for n in result] == ["Broadcast"]

    def test_get_notifications_filtered_by_email(self, manager, sample_user_info):
        """A user sees their own notifications, not other users'."""
        manager._repo.get_multi.return_value = [
            _db_notif("notif-1", "User Notification", recipient="user@example.com"),
            _db_notif("notif-2", "Other Notification", recipient="other@example.com",
                      created_at=datetime(2024, 1, 2)),
        ]

        result = manager.get_notifications(Mock(), user_info=sample_user_info)

        assert len(result) == 1
        assert result[0].recipient == "user@example.com"

    def test_get_notifications_filtered_by_role(
        self, manager, sample_user_info, mock_settings_manager
    ):
        """A legacy role-name recipient reaches members of the role, with the role name set."""
        mock_settings_manager.list_app_roles.return_value = [
            _role("Data Consumer", groups=["data_consumers"])
        ]
        manager._repo.get_multi.return_value = [
            _db_notif("notif-1", "Role Notification", recipient="Data Consumer")
        ]

        result = manager.get_notifications(Mock(), user_info=sample_user_info)

        assert [n.title for n in result] == ["Role Notification"]
        assert result[0].recipient_role_name == "Data Consumer"

    def test_get_notifications_hides_role_from_non_members(
        self, manager, sample_user_info, mock_settings_manager
    ):
        """A role notification is not shown to a user outside the role."""
        mock_settings_manager.list_app_roles.return_value = [
            _role("Data Producer", groups=["producers"])
        ]
        manager._repo.get_multi.return_value = [
            _db_notif("notif-1", "Role Notification", recipient="Data Producer")
        ]

        assert manager.get_notifications(Mock(), user_info=sample_user_info) == []

    def test_get_notifications_sorts_by_created_at(self, manager):
        """Notifications are sorted by created_at descending for a user."""
        manager._repo.get_multi.return_value = [
            _db_notif("notif-1", "First", created_at=datetime(2024, 1, 1)),
            _db_notif("notif-2", "Second", created_at=datetime(2024, 1, 3)),
            _db_notif("notif-3", "Third", created_at=datetime(2024, 1, 2)),
        ]
        user = UserInfo(username="u", email="u@example.com", user="u", ip="1", groups=[])

        result = manager.get_notifications(Mock(), user_info=user)

        assert [n.title for n in result] == ["Second", "Third", "First"]

    # Mark as Read Tests

    def test_mark_notification_read_success(self, manager):
        """Marking an unread notification updates it through the repository and commits."""
        mock_db = Mock()
        row = _db_notif("notif-123")
        manager._repo.get.return_value = row
        manager._repo.update.return_value = _db_notif("notif-123", read=True)

        result = manager.mark_notification_read(mock_db, notification_id="notif-123")

        assert result.read is True
        manager._repo.update.assert_called_once_with(
            db=mock_db, db_obj=row, obj_in={"read": True}
        )
        mock_db.commit.assert_called_once()

    def test_mark_notification_read_already_read(self, manager):
        """An already-read notification is returned without an update or commit."""
        mock_db = Mock()
        manager._repo.get.return_value = _db_notif("notif-123", read=True)

        result = manager.mark_notification_read(mock_db, notification_id="notif-123")

        assert result.read is True
        manager._repo.update.assert_not_called()
        mock_db.commit.assert_not_called()

    def test_mark_notification_read_not_found(self, manager):
        """A missing notification returns None (no exception)."""
        manager._repo.get.return_value = None

        assert manager.mark_notification_read(Mock(), notification_id="nope") is None
        manager._repo.update.assert_not_called()

    # Delete Notification Tests

    def test_delete_notification_success(self, manager):
        """Deleting removes through the repository and returns True."""
        mock_db = Mock()
        manager._repo.remove.return_value = _db_notif("notif-123")

        assert manager.delete_notification(mock_db, notification_id="notif-123") is True
        manager._repo.remove.assert_called_once_with(db=mock_db, id="notif-123")

    def test_delete_notification_not_found(self, manager):
        """Deleting a missing notification returns False (the route maps it to 404)."""
        manager._repo.remove.return_value = None

        assert manager.delete_notification(Mock(), notification_id="nonexistent") is False
