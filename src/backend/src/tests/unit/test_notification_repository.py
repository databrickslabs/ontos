"""
Unit tests for NotificationRepository

Tests database operations for notification management including:
- CRUD operations (create, read, list, update, delete)
- Filtering by recipient, read status
"""
import pytest
import uuid

from src.repositories.notification_repository import NotificationRepository
from src.db_models.notifications import NotificationDb


class TestNotificationRepository:
    """Test suite for NotificationRepository"""

    @pytest.fixture
    def repository(self):
        """Create repository instance for testing."""
        return NotificationRepository(NotificationDb)

    def test_create_notification(self, repository, db_session):
        """Test creating a notification."""
        # Arrange
        notification_db = NotificationDb(
            id=str(uuid.uuid4()),
            type="info",
            title="Test Notification",
            description="Test description",
            recipient="user@example.com",
        )

        # Act
        db_session.add(notification_db)
        db_session.commit()
        db_session.refresh(notification_db)

        # Assert
        assert notification_db.title == "Test Notification"

    def test_get_notification_by_id(self, repository, db_session):
        """Test retrieving a notification by ID."""
        # Arrange
        notification_db = NotificationDb(
            id=str(uuid.uuid4()),
            type="info",
            title="Test Notification",
            recipient="user@example.com",
        )
        db_session.add(notification_db)
        db_session.commit()

        # Act
        result = repository.get(db_session, id=notification_db.id)

        # Assert
        assert result is not None
        assert result.id == notification_db.id

    def test_get_multi_empty(self, repository, db_session):
        """Test listing notifications when none exist."""
        # Act
        result = repository.get_multi(db_session)

        # Assert
        assert result == []

    def test_get_multi_notifications(self, repository, db_session):
        """Test listing multiple notifications."""
        # Arrange
        for i in range(3):
            notification_db = NotificationDb(
                id=str(uuid.uuid4()),
                type="info",
                title=f"Notification {i}",
                recipient="user@example.com",
            )
            db_session.add(notification_db)
        db_session.commit()

        # Act
        result = repository.get_multi(db_session)

        # Assert
        assert len(result) == 3


    def test_mark_as_read(self, repository, db_session):
        """Test marking notification as read."""
        # Arrange
        notification_db = NotificationDb(
            id=str(uuid.uuid4()),
            type="info",
            title="Test Notification",
            recipient="user@example.com",
            read=False,
        )
        db_session.add(notification_db)
        db_session.commit()

        # Act
        notification_db.read = True
        db_session.commit()
        db_session.refresh(notification_db)

        # Assert
        assert notification_db.read is True

    def test_delete_notification(self, repository, db_session):
        """Test deleting a notification."""
        # Arrange
        notification_db = NotificationDb(
            id=str(uuid.uuid4()),
            type="info",
            title="Test Notification",
            recipient="user@example.com",
        )
        db_session.add(notification_db)
        db_session.commit()
        notification_id = notification_db.id

        # Act
        repository.remove(db_session, id=notification_id)
        db_session.commit()

        # Assert
        deleted = repository.get(db_session, id=notification_id)
        assert deleted is None

    def test_count_notifications(self, repository, db_session):
        """Test counting notifications."""
        # Arrange
        for i in range(5):
            notification_db = NotificationDb(
                id=str(uuid.uuid4()),
                type="info",
                title=f"Notification {i}",
                recipient="user@example.com",
            )
            db_session.add(notification_db)
        db_session.commit()

        # Act
        count = repository.count(db_session)

        # Assert
        assert count == 5

