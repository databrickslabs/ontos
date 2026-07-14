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

    def test_update_last_polled_only_if_changed_skips_unchanged(self, repository, db_session):
        """update_last_polled(only_if_changed=True) must not write when the job
        state is identical — this is what lets a quiet poll cycle perform zero
        Lakebase writes so the instance can idle."""
        from unittest.mock import patch

        installation_db = WorkflowInstallationDb(
            id=str(uuid.uuid4()),
            workflow_id="poll-wf",
            name="Poll WF",
            job_id=999,
            status="installed",
        )
        db_session.add(installation_db)
        db_session.commit()

        state = {'run_id': 1, 'life_cycle_state': 'TERMINATED', 'result_state': 'SUCCESS'}
        # First call persists the state.
        repository.update_last_polled(db_session, workflow_id="poll-wf", job_state=state, only_if_changed=True)

        # Identical state → no write.
        with patch.object(db_session, "commit") as spy_commit:
            repository.update_last_polled(
                db_session, workflow_id="poll-wf", job_state=dict(state), only_if_changed=True,
            )
            assert spy_commit.call_count == 0, "unchanged state should not commit"

    def test_update_last_polled_writes_on_change(self, repository, db_session):
        """A changed job state must still persist under only_if_changed."""
        installation_db = WorkflowInstallationDb(
            id=str(uuid.uuid4()),
            workflow_id="poll-wf2",
            name="Poll WF2",
            job_id=1000,
            status="installed",
        )
        db_session.add(installation_db)
        db_session.commit()

        repository.update_last_polled(
            db_session, workflow_id="poll-wf2",
            job_state={'run_id': 1, 'life_cycle_state': 'RUNNING'}, only_if_changed=True,
        )
        updated = repository.update_last_polled(
            db_session, workflow_id="poll-wf2",
            job_state={'run_id': 1, 'life_cycle_state': 'TERMINATED', 'result_state': 'SUCCESS'},
            only_if_changed=True,
        )
        assert updated is not None
        assert 'TERMINATED' in (updated.last_job_state or '')

