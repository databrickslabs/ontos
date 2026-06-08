"""
Unit tests for AuditLogRepository

Tests database operations for audit log management including:
- CRUD operations (create, read, list)
- Filtering by username, feature, action, success, time range
- Counting with filters
"""
import pytest
from datetime import datetime, timezone
import uuid

from src.repositories.audit_log_repository import AuditLogRepository
from src.db_models.audit_log import AuditLogDb


class TestAuditLogRepository:
    """Test suite for AuditLogRepository"""

    @pytest.fixture
    def repository(self):
        """Create repository instance for testing."""
        return AuditLogRepository(AuditLogDb)

    def test_create_audit_log(self, repository, db_session):
        """Test creating an audit log entry."""
        # Arrange
        log_db = AuditLogDb(
            id=uuid.uuid4(),
            username="test-user",
            feature="data_products",
            action="create",
            success=True,
        )

        # Act
        db_session.add(log_db)
        db_session.commit()
        db_session.refresh(log_db)

        # Assert
        assert log_db.username == "test-user"

    def test_get_audit_log_by_id(self, repository, db_session):
        """Test retrieving an audit log by ID."""
        # Arrange
        log_db = AuditLogDb(
            id=uuid.uuid4(),
            username="test-user",
            feature="data_products",
            action="create",
            success=True,
        )
        db_session.add(log_db)
        db_session.commit()

        # Act
        result = repository.get(db_session, id=log_db.id)

        # Assert
        assert result is not None
        assert result.id == log_db.id

    def test_get_multi_empty(self, repository, db_session):
        """Test listing audit logs when none exist."""
        # Act
        result = repository.get_multi(db_session)

        # Assert
        assert len(result) == 0

    def test_get_multi_logs(self, repository, db_session):
        """Test listing multiple audit logs."""
        # Arrange
        for i in range(3):
            log_db = AuditLogDb(
                id=uuid.uuid4(),
                username=f"user-{i}",
                feature="data_products",
                action="view",
                success=True,
            )
            db_session.add(log_db)
        db_session.commit()

        # Act
        result = repository.get_multi(db_session)

        # Assert
        assert len(result) == 3

    def test_get_multi_filter_by_username(self, repository, db_session):
        """Test filtering logs by username."""
        # Arrange
        for i in range(3):
            log_db = AuditLogDb(
                id=uuid.uuid4(),
                username="target-user" if i == 1 else f"user-{i}",
                feature="data_products",
                action="view",
                success=True,
            )
            db_session.add(log_db)
        db_session.commit()

        # Act
        result = repository.get_multi(db_session, username="target-user")

        # Assert
        assert len(result) == 1
        assert result[0].username == "target-user"

    def test_get_multi_filter_by_feature(self, repository, db_session):
        """Test filtering logs by feature."""
        # Arrange
        log1 = AuditLogDb(
            id=uuid.uuid4(),
            username="user1",
            feature="data_products",
            action="create",
            success=True,
        )
        log2 = AuditLogDb(
            id=uuid.uuid4(),
            username="user2",
            feature="data_contracts",
            action="create",
            success=True,
        )
        db_session.add_all([log1, log2])
        db_session.commit()

        # Act
        result = repository.get_multi(db_session, feature="data_products")

        # Assert
        assert len(result) == 1
        assert result[0].feature == "data_products"

    def test_get_multi_filter_by_action(self, repository, db_session):
        """Test filtering logs by action."""
        # Arrange
        log1 = AuditLogDb(
            id=uuid.uuid4(),
            username="user1",
            feature="data_products",
            action="create",
            success=True,
        )
        log2 = AuditLogDb(
            id=uuid.uuid4(),
            username="user2",
            feature="data_products",
            action="delete",
            success=True,
        )
        db_session.add_all([log1, log2])
        db_session.commit()

        # Act
        result = repository.get_multi(db_session, action="create")

        # Assert
        assert len(result) == 1
        assert result[0].action == "create"

    def test_get_multi_filter_by_success(self, repository, db_session):
        """Test filtering logs by success status."""
        # Arrange
        log1 = AuditLogDb(
            id=uuid.uuid4(),
            username="user1",
            feature="data_products",
            action="create",
            success=True,
        )
        log2 = AuditLogDb(
            id=uuid.uuid4(),
            username="user2",
            feature="data_products",
            action="create",
            success=False,
        )
        db_session.add_all([log1, log2])
        db_session.commit()

        # Act
        result = repository.get_multi(db_session, success=False)

        # Assert
        assert len(result) == 1
        assert result[0].success is False

    def test_get_multi_pagination(self, repository, db_session):
        """Test pagination for listing audit logs."""
        # Arrange
        for i in range(10):
            log_db = AuditLogDb(
                id=uuid.uuid4(),
                username=f"user-{i}",
                feature="data_products",
                action="view",
                success=True,
            )
            db_session.add(log_db)
        db_session.commit()

        # Act
        result = repository.get_multi(db_session, skip=0, limit=5)

        # Assert
        assert len(result) == 5

    def test_get_multi_count(self, repository, db_session):
        """Test counting audit logs."""
        # Arrange
        for i in range(7):
            log_db = AuditLogDb(
                id=uuid.uuid4(),
                username=f"user-{i}",
                feature="data_products",
                action="view",
                success=True,
            )
            db_session.add(log_db)
        db_session.commit()

        # Act
        count = repository.get_multi_count(db_session)

        # Assert
        assert count == 7

    def test_get_multi_count_with_filters(self, repository, db_session):
        """Test counting audit logs with filters."""
        # Arrange
        for i in range(5):
            log_db = AuditLogDb(
                id=uuid.uuid4(),
                username="target-user" if i < 2 else f"user-{i}",
                feature="data_products",
                action="view",
                success=True,
            )
            db_session.add(log_db)
        db_session.commit()

        # Act
        count = repository.get_multi_count(db_session, username="target-user")

        # Assert
        assert count == 2

