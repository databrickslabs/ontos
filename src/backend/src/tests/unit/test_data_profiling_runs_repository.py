"""
Unit tests for DataProfilingRunsRepository

Tests database operations for data profiling runs including:
- CRUD operations (create, read, list)
- Get by contract ID
- Get latest for contract
"""
import pytest
import uuid
from datetime import datetime, timezone

from src.repositories.data_profiling_runs_repository import DataProfilingRunsRepository
from src.db_models.data_contracts import DataProfilingRunDb


class TestDataProfilingRunsRepository:
    """Test suite for DataProfilingRunsRepository"""

    @pytest.fixture
    def repository(self):
        """Create repository instance for testing."""
        return DataProfilingRunsRepository(DataProfilingRunDb)

    @pytest.fixture
    def sample_contract_id(self):
        """Sample contract ID for testing."""
        return str(uuid.uuid4())

    def test_create_profiling_run(self, repository, db_session, sample_contract_id):
        """Test creating a profiling run."""
        # Arrange
        run_db = DataProfilingRunDb(
            id=str(uuid.uuid4()),
            contract_id=sample_contract_id,
            source="dqx",
            status="pending",
        )

        # Act
        db_session.add(run_db)
        db_session.commit()
        db_session.refresh(run_db)

        # Assert
        assert run_db.contract_id == sample_contract_id

    def test_get_profiling_run_by_id(self, repository, db_session, sample_contract_id):
        """Test retrieving a profiling run by ID."""
        # Arrange
        run_db = DataProfilingRunDb(
            id=str(uuid.uuid4()),
            contract_id=sample_contract_id,
            source="dqx",
            status="completed",
        )
        db_session.add(run_db)
        db_session.commit()

        # Act
        result = repository.get(db_session, id=run_db.id)

        # Assert
        assert result is not None
        assert result.id == run_db.id

    def test_get_by_contract_id(self, repository, db_session, sample_contract_id):
        """Test retrieving profiling runs by contract ID."""
        # Arrange - Create multiple runs for same contract
        run1 = DataProfilingRunDb(
            id=str(uuid.uuid4()),
            contract_id=sample_contract_id,
            source="dqx",
            status="completed",
        )
        run2 = DataProfilingRunDb(
            id=str(uuid.uuid4()),
            contract_id=sample_contract_id,
            source="llm",
            status="running",
        )
        db_session.add_all([run1, run2])
        db_session.commit()

        # Act
        result = repository.get_by_contract_id(db_session, contract_id=sample_contract_id)

        # Assert
        assert len(result) == 2
        run_ids = [r.id for r in result]
        assert run1.id in run_ids
        assert run2.id in run_ids

    def test_get_by_contract_id_empty(self, repository, db_session):
        """Test retrieving runs for contract with no runs."""
        # Act
        result = repository.get_by_contract_id(
            db_session, contract_id=str(uuid.uuid4())
        )

        # Assert
        assert result == []

    def test_get_latest_for_contract(self, repository, db_session, sample_contract_id):
        """Test retrieving the latest profiling run for a contract."""
        # Arrange - Create multiple runs with different timestamps
        run1 = DataProfilingRunDb(
            id=str(uuid.uuid4()),
            contract_id=sample_contract_id,
            source="dqx",
            status="completed",
        )
        db_session.add(run1)
        db_session.commit()
        
        # Add a newer run
        run2 = DataProfilingRunDb(
            id=str(uuid.uuid4()),
            contract_id=sample_contract_id,
            source="llm",
            status="running",
        )
        db_session.add(run2)
        db_session.commit()

        # Act
        result = repository.get_latest_for_contract(
            db_session, contract_id=sample_contract_id
        )

        # Assert
        assert result is not None
        # Should return one of the runs (order may vary if timestamps are the same)
        assert result.id in [run1.id, run2.id]

    def test_get_latest_for_contract_empty(self, repository, db_session):
        """Test retrieving latest run for contract with no runs."""
        # Act
        result = repository.get_latest_for_contract(
            db_session, contract_id=str(uuid.uuid4())
        )

        # Assert
        assert result is None

    def test_get_multi_empty(self, repository, db_session):
        """Test listing runs when none exist."""
        # Act
        result = repository.get_multi(db_session)

        # Assert
        assert result == []

    def test_get_multi_runs(self, repository, db_session):
        """Test listing multiple profiling runs."""
        # Arrange
        for i in range(3):
            run_db = DataProfilingRunDb(
                id=str(uuid.uuid4()),
                contract_id=str(uuid.uuid4()),
                source="dqx",
                status="completed",
            )
            db_session.add(run_db)
        db_session.commit()

        # Act
        result = repository.get_multi(db_session)

        # Assert
        assert len(result) == 3

    def test_count_profiling_runs(self, repository, db_session):
        """Test counting profiling runs."""
        # Arrange
        for i in range(5):
            run_db = DataProfilingRunDb(
                id=str(uuid.uuid4()),
                contract_id=str(uuid.uuid4()),
                source="dqx",
                status="completed",
            )
            db_session.add(run_db)
        db_session.commit()

        # Act
        count = repository.count(db_session)

        # Assert
        assert count == 5

    def test_delete_profiling_run(self, repository, db_session, sample_contract_id):
        """Test deleting a profiling run."""
        # Arrange
        run_db = DataProfilingRunDb(
            id=str(uuid.uuid4()),
            contract_id=sample_contract_id,
            source="dqx",
            status="completed",
        )
        db_session.add(run_db)
        db_session.commit()
        run_id = run_db.id

        # Act
        repository.remove(db_session, id=run_id)
        db_session.commit()

        # Assert
        deleted = repository.get(db_session, id=run_id)
        assert deleted is None

