"""
Unit tests for ChangeLogRepository

Tests database operations for change log tracking including:
- CRUD operations (create, read, list)
- Filtering by entity, user, action
"""
import pytest
import uuid

from src.repositories.change_log_repository import ChangeLogRepository
from src.db_models.change_log import ChangeLogDb


class TestChangeLogRepository:
    """Test suite for ChangeLogRepository"""

    @pytest.fixture
    def repository(self):
        """Create repository instance for testing."""
        return ChangeLogRepository()

    def test_create_change_log(self, repository, db_session):
        """Test creating a change log entry."""
        # Arrange
        log_db = ChangeLogDb(
            id=str(uuid.uuid4()),
            entity_type="data_product",
            entity_id="product-123",
            action="created",
            username="user@example.com",
        )

        # Act
        db_session.add(log_db)
        db_session.commit()
        db_session.refresh(log_db)

        # Assert
        assert log_db.entity_type == "data_product"

    def test_get_change_log_by_id(self, repository, db_session):
        """Test retrieving a change log by ID."""
        # Arrange
        log_db = ChangeLogDb(
            id=str(uuid.uuid4()),
            entity_type="data_product",
            entity_id="product-123",
            action="updated",
            username="user@example.com",
        )
        db_session.add(log_db)
        db_session.commit()

        # Act
        result = repository.get(db_session, id=log_db.id)

        # Assert
        assert result is not None
        assert result.id == log_db.id

    def test_get_multi_empty(self, repository, db_session):
        """Test listing logs when none exist."""
        # Act
        result = repository.get_multi(db_session)

        # Assert
        assert result == []

    def test_get_multi_logs(self, repository, db_session):
        """Test listing multiple logs."""
        # Arrange
        for i in range(3):
            log_db = ChangeLogDb(
                id=str(uuid.uuid4()),
                entity_type=f"type_{i}",
                entity_id=f"entity_{i}",
                action="created",
                username="user@example.com",
            )
            db_session.add(log_db)
        db_session.commit()

        # Act
        result = repository.get_multi(db_session)

        # Assert
        assert len(result) == 3

    def test_get_by_entity(self, repository, db_session):
        """Test getting logs for specific entity."""
        # Arrange
        target_entity = "product-123"
        for i in range(2):
            log_db = ChangeLogDb(
                id=str(uuid.uuid4()),
                entity_type="data_product",
                entity_id=target_entity,
                action="updated",
                username="user@example.com",
            )
            db_session.add(log_db)
        
        # Add log for different entity
        other_log = ChangeLogDb(
            id=str(uuid.uuid4()),
            entity_type="data_product",
            entity_id="other-entity",
            action="created",
            username="user@example.com",
        )
        db_session.add(other_log)
        db_session.commit()

        # Act
        result = repository.list_by_entity(
            db_session, entity_type="data_product", entity_id=target_entity
        )

        # Assert
        assert len(result) == 2
        assert all(r.entity_id == target_entity for r in result)

    def test_count_logs(self, repository, db_session):
        """Test counting logs."""
        # Arrange
        for i in range(5):
            log_db = ChangeLogDb(
                id=str(uuid.uuid4()),
                entity_type="data_product",
                entity_id=f"product-{i}",
                action="created",
                username="user@example.com",
            )
            db_session.add(log_db)
        db_session.commit()

        # Act
        count = repository.count(db_session)

        # Assert
        assert count == 5

