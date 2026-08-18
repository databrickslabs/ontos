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

    def test_upsert_run_skips_commit_when_unchanged(self, repository, db_session, sample_installation):
        """upsert_run must not write when the incoming state matches storage.

        The background poll re-fetches the last N days of runs every cycle, so
        most upserts are for already-terminal runs whose state is identical to
        what we stored. Committing those every cycle kept Lakebase permanently
        busy; a no-op upsert must skip the write entirely.
        """
        from unittest.mock import patch

        run_data = {
            'run_name': 'nightly',
            'life_cycle_state': 'TERMINATED',
            'result_state': 'SUCCESS',
            'state_message': None,
            'start_time': 1000,
            'end_time': 2000,
        }
        # First upsert creates the row.
        repository.upsert_run(
            db_session, run_id=555, workflow_installation_id=sample_installation.id, run_data=run_data,
        )

        # Second upsert with identical data must not commit.
        with patch.object(db_session, "commit") as spy_commit:
            result = repository.upsert_run(
                db_session, run_id=555, workflow_installation_id=sample_installation.id, run_data=dict(run_data),
            )
            assert spy_commit.call_count == 0, "unchanged upsert should not commit"
        assert result.run_id == 555

    def test_upsert_run_commits_on_state_change(self, repository, db_session, sample_installation):
        """A real state transition must still be persisted."""
        from unittest.mock import patch

        base = {
            'run_name': 'nightly',
            'life_cycle_state': 'RUNNING',
            'result_state': None,
            'state_message': None,
            'start_time': 1000,
            'end_time': None,
        }
        repository.upsert_run(
            db_session, run_id=556, workflow_installation_id=sample_installation.id, run_data=base,
        )

        # A changed upsert must commit (spy). Refresh-under-mocked-commit would
        # reload the stale row, so assert the commit fired here...
        changed = dict(base, life_cycle_state='TERMINATED', result_state='SUCCESS', end_time=2000)
        with patch.object(db_session, "commit") as spy_commit:
            repository.upsert_run(
                db_session, run_id=556, workflow_installation_id=sample_installation.id, run_data=changed,
            )
            assert spy_commit.call_count == 1, "state change must commit"

        # ...and verify it actually persisted with a real (unmocked) upsert.
        result = repository.upsert_run(
            db_session, run_id=556, workflow_installation_id=sample_installation.id, run_data=changed,
        )
        assert result.life_cycle_state == 'TERMINATED'
        assert result.result_state == 'SUCCESS'

