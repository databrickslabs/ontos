"""
Unit tests for WorkflowInstallationRepository

Tests database operations for workflow installation management including:
- CRUD operations (create, read, list, update, delete)
- Filtering by workflow_id, status
"""
import pytest
import uuid

from src.repositories.workflow_installations_repository import WorkflowInstallationRepository
from src.db_models.workflow_installations import WorkflowInstallationDb


class TestWorkflowInstallationRepository:
    """Test suite for WorkflowInstallationRepository"""

    @pytest.fixture
    def repository(self):
        """Create repository instance for testing."""
        return WorkflowInstallationRepository(WorkflowInstallationDb)

    def test_create_installation(self, repository, db_session):
        """Test creating a workflow installation."""
        # Arrange
        installation_db = WorkflowInstallationDb(
            id=str(uuid.uuid4()),
            workflow_id="test-workflow",
            name="Test Workflow",
            job_id=12345,
            status="installed",
        )

        # Act
        db_session.add(installation_db)
        db_session.commit()
        db_session.refresh(installation_db)

        # Assert
        assert installation_db.workflow_id == "test-workflow"

    def test_get_installation_by_id(self, repository, db_session):
        """Test retrieving an installation by ID."""
        # Arrange
        installation_db = WorkflowInstallationDb(
            id=str(uuid.uuid4()),
            workflow_id="test-workflow",
            name="Test Workflow",
            job_id=12345,
        )
        db_session.add(installation_db)
        db_session.commit()

        # Act
        result = repository.get(db_session, id=installation_db.id)

        # Assert
        assert result is not None
        assert result.id == installation_db.id

    def test_get_multi_empty(self, repository, db_session):
        """Test listing installations when none exist."""
        # Act
        result = repository.get_multi(db_session)

        # Assert
        assert result == []

    def test_get_multi_installations(self, repository, db_session):
        """Test listing multiple installations."""
        # Arrange
        for i in range(3):
            installation_db = WorkflowInstallationDb(
                id=str(uuid.uuid4()),
                workflow_id=f"workflow-{i}",
                name=f"Workflow {i}",
                job_id=12345 + i,
            )
            db_session.add(installation_db)
        db_session.commit()

        # Act
        result = repository.get_multi(db_session)

        # Assert
        assert len(result) == 3

    def test_get_by_workflow_id(self, repository, db_session):
        """Test getting installation by workflow_id."""
        # Arrange
        installation_db = WorkflowInstallationDb(
            id=str(uuid.uuid4()),
            workflow_id="test-workflow",
            name="Test Workflow",
            job_id=12345,
        )
        db_session.add(installation_db)
        db_session.commit()

        # Act
        result = repository.get_by_workflow_id(db_session, workflow_id="test-workflow")

        # Assert
        assert result is not None
        assert result.workflow_id == "test-workflow"

    def test_update_installation(self, repository, db_session):
        """Test updating an installation."""
        # Arrange
        installation_db = WorkflowInstallationDb(
            id=str(uuid.uuid4()),
            workflow_id="test-workflow",
            name="Test Workflow",
            job_id=12345,
            status="installed",
        )
        db_session.add(installation_db)
        db_session.commit()

        # Act
        installation_db.status = "updating"
        db_session.commit()
        db_session.refresh(installation_db)

        # Assert
        assert installation_db.status == "updating"

    def test_delete_installation(self, repository, db_session):
        """Test deleting an installation."""
        # Arrange
        installation_db = WorkflowInstallationDb(
            id=str(uuid.uuid4()),
            workflow_id="test-workflow",
            name="Test Workflow",
            job_id=12345,
        )
        db_session.add(installation_db)
        db_session.commit()
        installation_id = installation_db.id

        # Act
        repository.remove(db_session, id=installation_id)
        db_session.commit()

        # Assert
        deleted = repository.get(db_session, id=installation_id)
        assert deleted is None

    def test_count_installations(self, repository, db_session):
        """Test counting installations."""
        # Arrange
        for i in range(5):
            installation_db = WorkflowInstallationDb(
                id=str(uuid.uuid4()),
                workflow_id=f"workflow-{i}",
                name=f"Workflow {i}",
                job_id=12345 + i,
            )
            db_session.add(installation_db)
        db_session.commit()

        # Act
        count = repository.count(db_session)

        # Assert
        assert count == 5

