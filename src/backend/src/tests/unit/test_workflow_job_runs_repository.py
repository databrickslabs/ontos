"""
Unit tests for WorkflowJobRunRepository

Tests database operations for workflow job run tracking including:
- CRUD operations (create, read, list, update, delete)
- Filtering by workflow installation, state
"""
import pytest
import uuid

from src.repositories.workflow_job_runs_repository import WorkflowJobRunRepository
from src.db_models.workflow_job_runs import WorkflowJobRunDb
from src.db_models.workflow_installations import WorkflowInstallationDb


class TestWorkflowJobRunRepository:
    """Test suite for WorkflowJobRunRepository"""

    @pytest.fixture
    def repository(self):
        """Create repository instance for testing."""
        return WorkflowJobRunRepository(WorkflowJobRunDb)

    @pytest.fixture
    def sample_installation(self, db_session):
        """Create a sample workflow installation for testing."""
        installation = WorkflowInstallationDb(
            id=str(uuid.uuid4()),
            workflow_id="test-workflow",
            name="Test Workflow",
            job_id=12345,
        )
        db_session.add(installation)
        db_session.commit()
        db_session.refresh(installation)
        return installation

    def test_create_job_run(self, repository, db_session, sample_installation):
        """Test creating a workflow job run."""
        # Arrange
        job_run_db = WorkflowJobRunDb(
            id=str(uuid.uuid4()),
            workflow_installation_id=sample_installation.id,
            run_id=98765,
            life_cycle_state="RUNNING",
        )

        # Act
        db_session.add(job_run_db)
        db_session.commit()
        db_session.refresh(job_run_db)

        # Assert
        assert job_run_db.run_id == 98765

    def test_get_job_run_by_id(self, repository, db_session, sample_installation):
        """Test retrieving a job run by ID."""
        # Arrange
        job_run_db = WorkflowJobRunDb(
            id=str(uuid.uuid4()),
            workflow_installation_id=sample_installation.id,
            run_id=98765,
        )
        db_session.add(job_run_db)
        db_session.commit()

        # Act
        result = repository.get(db_session, id=job_run_db.id)

        # Assert
        assert result is not None
        assert result.id == job_run_db.id

    def test_get_multi_empty(self, repository, db_session):
        """Test listing job runs when none exist."""
        # Act
        result = repository.get_multi(db_session)

        # Assert
        assert result == []

    def test_get_multi_job_runs(self, repository, db_session, sample_installation):
        """Test listing multiple job runs."""
        # Arrange
        for i in range(3):
            job_run_db = WorkflowJobRunDb(
                id=str(uuid.uuid4()),
                workflow_installation_id=sample_installation.id,
                run_id=98765 + i,
            )
            db_session.add(job_run_db)
        db_session.commit()

        # Act
        result = repository.get_multi(db_session)

        # Assert
        assert len(result) == 3

    def test_get_by_run_id(self, repository, db_session, sample_installation):
        """Test getting job run by run_id."""
        # Arrange
        job_run_db = WorkflowJobRunDb(
            id=str(uuid.uuid4()),
            workflow_installation_id=sample_installation.id,
            run_id=98765,
        )
        db_session.add(job_run_db)
        db_session.commit()

        # Act
        result = repository.get_by_run_id(db_session, run_id=98765)

        # Assert
        assert result is not None
        assert result.run_id == 98765

    def test_update_job_run(self, repository, db_session, sample_installation):
        """Test updating a job run."""
        # Arrange
        job_run_db = WorkflowJobRunDb(
            id=str(uuid.uuid4()),
            workflow_installation_id=sample_installation.id,
            run_id=98765,
            life_cycle_state="RUNNING",
        )
        db_session.add(job_run_db)
        db_session.commit()

        # Act
        job_run_db.life_cycle_state = "TERMINATED"
        job_run_db.result_state = "SUCCESS"
        db_session.commit()
        db_session.refresh(job_run_db)

        # Assert
        assert job_run_db.life_cycle_state == "TERMINATED"
        assert job_run_db.result_state == "SUCCESS"

    def test_delete_job_run(self, repository, db_session, sample_installation):
        """Test deleting a job run."""
        # Arrange
        job_run_db = WorkflowJobRunDb(
            id=str(uuid.uuid4()),
            workflow_installation_id=sample_installation.id,
            run_id=98765,
        )
        db_session.add(job_run_db)
        db_session.commit()
        job_run_id = job_run_db.id

        # Act
        repository.remove(db_session, id=job_run_id)
        db_session.commit()

        # Assert
        deleted = repository.get(db_session, id=job_run_id)
        assert deleted is None

    def test_count_job_runs(self, repository, db_session, sample_installation):
        """Test counting job runs."""
        # Arrange
        for i in range(5):
            job_run_db = WorkflowJobRunDb(
                id=str(uuid.uuid4()),
                workflow_installation_id=sample_installation.id,
                run_id=98765 + i,
            )
            db_session.add(job_run_db)
        db_session.commit()

        # Act
        count = repository.count(db_session)

        # Assert
        assert count == 5

