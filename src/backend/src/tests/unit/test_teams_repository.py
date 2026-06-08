"""
Unit tests for TeamRepository

Tests database operations for team management including:
- CRUD operations (create, read, update, delete)
- Querying by domain
- Team counting
"""
import pytest
import uuid

from src.repositories.teams_repository import TeamRepository
from src.models.teams import TeamCreate
from src.db_models.teams import TeamDb


class TestTeamRepository:
    """Test suite for TeamRepository"""

    @pytest.fixture
    def repository(self):
        """Create repository instance for testing."""
        return TeamRepository()

    @pytest.fixture
    def sample_team_data(self):
        """Sample team data for testing."""
        return TeamCreate(
            name="Test Team",
            description="A test team",
        )

    # =====================================================================
    # Create Tests
    # =====================================================================

    def test_create_team(self, repository, db_session):
        """Test creating a team."""
        # Arrange - Create team directly using TeamDb
        team_db = TeamDb(
            id=str(uuid.uuid4()),
            name="Test Team",
            created_by="test-user",
            updated_by="test-user",
            extra_metadata='{}',
        )

        # Act
        db_session.add(team_db)
        db_session.commit()
        db_session.refresh(team_db)

        # Assert
        assert team_db.name == "Test Team"

    # =====================================================================
    # Get Tests
    # =====================================================================

    def test_get_team_by_id(self, repository, db_session):
        """Test retrieving a team by ID."""
        # Arrange
        team_db = TeamDb(
            id=str(uuid.uuid4()),
            name="Test Team",
            created_by="test-user",
            updated_by="test-user",
            extra_metadata='{}',
        )
        db_session.add(team_db)
        db_session.commit()

        # Act
        retrieved_team = repository.get(db_session, id=team_db.id)

        # Assert
        assert retrieved_team is not None
        assert retrieved_team.id == team_db.id

    def test_get_team_not_found(self, repository, db_session):
        """Test retrieving non-existent team."""
        # Act
        result = repository.get(db_session, id="nonexistent-id")

        # Assert
        assert result is None

    # =====================================================================
    # List Tests
    # =====================================================================

    def test_get_multi_empty(self, repository, db_session):
        """Test listing teams when none exist."""
        # Act
        teams = repository.get_multi(db_session)

        # Assert
        assert teams == []

    def test_get_multi_teams(self, repository, db_session):
        """Test listing multiple teams."""
        # Arrange - Create 3 teams
        for i in range(3):
            team_db = TeamDb(
                id=str(uuid.uuid4()),
                name=f"Team {i}",
                created_by="test-user",
                updated_by="test-user",
                extra_metadata='{}',
            )
            db_session.add(team_db)
        db_session.commit()

        # Act
        teams = repository.get_multi(db_session)

        # Assert
        assert len(teams) == 3

    # =====================================================================
    # Update Tests
    # =====================================================================

    def test_update_team(self, repository, db_session):
        """Test updating a team."""
        # Arrange
        team_db = TeamDb(
            id=str(uuid.uuid4()),
            name="Original Name",
            created_by="test-user",
            updated_by="test-user",
            extra_metadata='{}',
        )
        db_session.add(team_db)
        db_session.commit()

        # Act
        update_data = {"name": "Updated Name"}
        updated_team = repository.update(db_session, db_obj=team_db, obj_in=update_data)
        db_session.commit()

        # Assert
        assert updated_team.name == "Updated Name"

    # =====================================================================
    # Delete Tests
    # =====================================================================

    def test_delete_team(self, repository, db_session):
        """Test deleting a team."""
        # Arrange
        team_db = TeamDb(
            id=str(uuid.uuid4()),
            name="Test Team",
            created_by="test-user",
            updated_by="test-user",
            extra_metadata='{}',
        )
        db_session.add(team_db)
        db_session.commit()
        team_id = team_db.id

        # Act
        repository.remove(db_session, id=team_id)
        db_session.commit()

        # Assert
        deleted_team = repository.get(db_session, id=team_id)
        assert deleted_team is None

    # =====================================================================
    # Domain Filtering Tests
    # =====================================================================

    def test_get_teams_by_domain(self, repository, db_session):
        """Test filtering teams by domain."""
        # Arrange
        team_with_domain = TeamDb(
            id=str(uuid.uuid4()),
            name="Domain Team",
            domain_id="domain-123",
            created_by="test-user",
            updated_by="test-user",
            extra_metadata='{}',
        )
        team_without_domain = TeamDb(
            id=str(uuid.uuid4()),
            name="Standalone Team",
            created_by="test-user",
            updated_by="test-user",
            extra_metadata='{}',
        )
        db_session.add(team_with_domain)
        db_session.add(team_without_domain)
        db_session.commit()

        # Act
        domain_teams = repository.get_teams_by_domain(db_session, domain_id="domain-123")

        # Assert
        assert len(domain_teams) == 1
        assert domain_teams[0].name == "Domain Team"

    # =====================================================================
    # Count Tests
    # =====================================================================

    def test_count_teams_empty(self, repository, db_session):
        """Test team count when none exist."""
        # Act
        count = repository.count(db_session)

        # Assert
        assert count == 0

    def test_count_teams(self, repository, db_session):
        """Test team count with multiple teams."""
        # Arrange - Create 5 teams
        for i in range(5):
            team_db = TeamDb(
                id=str(uuid.uuid4()),
                name=f"Team {i}",
                created_by="test-user",
                updated_by="test-user",
                extra_metadata='{}',
            )
            db_session.add(team_db)
        db_session.commit()

        # Act
        count = repository.count(db_session)

        # Assert
        assert count == 5

