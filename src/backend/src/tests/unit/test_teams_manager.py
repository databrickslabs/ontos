"""
Unit tests for TeamsManager

Tests business logic for team management including:
- Team CRUD operations (create, read, list, update, delete)
- Team member management (add, update, remove, list)
- Team filtering by domain
"""
import pytest
from unittest.mock import Mock, MagicMock
import uuid
from sqlalchemy.orm import Session

from src.controller.teams_manager import TeamsManager
from src.models.teams import TeamCreate, TeamUpdate, TeamMemberCreate, TeamMemberUpdate
from src.db_models.teams import TeamDb, TeamMemberDb
from src.models.data_domains import DataDomainCreate
from src.repositories.data_domain_repository import data_domain_repo
from src.repositories.entity_domain_association_repository import entity_domain_repo


def _make_domain(db_session, name: str) -> str:
    """Create a real data domain and return its id (needed for FK-backed assignments)."""
    d = data_domain_repo.create(db=db_session, obj_in=DataDomainCreate(name=name))
    db_session.commit()
    return d.id


class TestTeamsManager:
    """Test suite for TeamsManager"""

    @pytest.fixture
    def manager(self, db_session):
        """Create TeamsManager instance for testing."""
        return TeamsManager()

    @pytest.fixture
    def sample_team_data(self):
        """Sample team data for testing."""
        return TeamCreate(
            name="Test Team",
            description="A test team",
        )

    @pytest.fixture
    def sample_team_db(self, db_session, sample_team_data):
        """Create a sample team in the database."""
        team_db = TeamDb(
            id=str(uuid.uuid4()),
            name=sample_team_data.name,
            description=sample_team_data.description,
            created_by="test-user",
            updated_by="test-user",
            extra_metadata='{}',  # JSON string
        )
        db_session.add(team_db)
        db_session.commit()
        db_session.refresh(team_db)
        return team_db

    # =====================================================================
    # Create Team Tests
    # =====================================================================

    def test_create_team_success(self, manager, db_session, sample_team_data):
        """Test successful team creation."""
        # Act
        result = manager.create_team(db_session, sample_team_data, current_user_id="user1")

        # Assert
        assert result is not None
        assert result.name == sample_team_data.name
        assert result.description == sample_team_data.description

    def test_create_team_with_domain(self, manager, db_session):
        """Test creating team with (multi-)domain association."""
        # Arrange
        domain_id = _make_domain(db_session, "Domain 123")
        team_data = TeamCreate(
            name="Domain Team",
            description="Team with domain",
            domain_ids=[domain_id],
            primary_domain_id=domain_id,
        )

        # Act
        result = manager.create_team(db_session, team_data, current_user_id="user1")

        # Assert
        assert result.domain_ids == [domain_id]
        assert result.primary_domain_id == domain_id
        assert len(result.domains) == 1 and result.domains[0].is_primary

    def test_create_team_primary_not_in_domain_ids_is_clamped(self, manager, db_session):
        """A primary_domain_id outside domain_ids must be clamped to the first id, not
        propagated to set_domains_for_entity (which would raise ValueError -> HTTP 500)."""
        a = _make_domain(db_session, "Alpha")
        b = _make_domain(db_session, "Beta")
        team_data = TeamCreate(
            name="Clamp Team",
            description="primary not in set",
            domain_ids=[a, b],
            primary_domain_id="not-a-member",
        )

        # Act — should not raise; primary falls back to the first domain id.
        result = manager.create_team(db_session, team_data, current_user_id="user1")

        # Assert
        assert set(result.domain_ids) == {a, b}
        assert result.primary_domain_id == a

    # =====================================================================
    # Get Team Tests
    # =====================================================================

    def test_get_team_by_id_exists(self, manager, db_session, sample_team_db):
        """Test retrieving an existing team."""
        # Act
        result = manager.get_team_by_id(db_session, sample_team_db.id)

        # Assert
        assert result is not None
        assert str(result.id) == sample_team_db.id
        assert result.name == sample_team_db.name

    def test_get_team_by_id_not_found(self, manager, db_session):
        """Test retrieving a non-existent team."""
        # Act
        result = manager.get_team_by_id(db_session, "nonexistent-id")

        # Assert
        assert result is None

    # =====================================================================
    # List Teams Tests
    # =====================================================================

    def test_get_all_teams_empty(self, manager, db_session):
        """Test listing teams when none exist."""
        # Act
        result = manager.get_all_teams(db_session)

        # Assert
        assert result == []

    def test_get_all_teams_multiple(self, manager, db_session):
        """Test listing multiple teams."""
        # Arrange - Create 3 teams
        for i in range(3):
            team_db = TeamDb(
                id=str(uuid.uuid4()),
                name=f"Team {i}",
                description=f"Description {i}",
                created_by="test-user",
                updated_by="test-user",
                extra_metadata='{}',
            )
            db_session.add(team_db)
        db_session.commit()

        # Act
        result = manager.get_all_teams(db_session)

        # Assert
        assert len(result) == 3

    def test_get_teams_by_domain(self, manager, db_session):
        """Test filtering teams by domain (any-of via junction)."""
        # Arrange - Create teams with and without domain
        domain_id = _make_domain(db_session, "Domain 123")
        team_with_domain = TeamDb(
            id=str(uuid.uuid4()),
            name="Domain Team",
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
        entity_domain_repo.set_domains_for_entity(
            db_session, entity_type="team", entity_id=team_with_domain.id, domain_ids=[domain_id]
        )
        db_session.commit()

        # Act
        result = manager.get_teams_by_domain(db_session, domain_id)

        # Assert
        assert len(result) == 1
        assert result[0].name == "Domain Team"

    def test_get_standalone_teams(self, manager, db_session):
        """Test getting teams without any domain assignment."""
        # Arrange
        domain_id = _make_domain(db_session, "Domain 123")
        standalone_team = TeamDb(
            id=str(uuid.uuid4()),
            name="Standalone Team",
            created_by="test-user",
            updated_by="test-user",
            extra_metadata='{}',
        )
        domain_team = TeamDb(
            id=str(uuid.uuid4()),
            name="Domain Team",
            created_by="test-user",
            updated_by="test-user",
            extra_metadata='{}',
        )
        db_session.add(standalone_team)
        db_session.add(domain_team)
        db_session.commit()
        entity_domain_repo.set_domains_for_entity(
            db_session, entity_type="team", entity_id=domain_team.id, domain_ids=[domain_id]
        )
        db_session.commit()

        # Act
        result = manager.get_standalone_teams(db_session)

        # Assert
        assert len(result) == 1
        assert result[0].name == "Standalone Team"

    # =====================================================================
    # Update Team Tests
    # =====================================================================

    def test_update_team_success(self, manager, db_session, sample_team_db):
        """Test successful team update."""
        # Arrange
        team_update = TeamUpdate(
            name="Updated Name",
            description="Updated description",
        )

        # Act
        result = manager.update_team(
            db_session, sample_team_db.id, team_update, current_user_id="user1"
        )

        # Assert
        assert result is not None
        assert result.name == "Updated Name"
        assert result.description == "Updated description"

    def test_update_team_not_found(self, manager, db_session):
        """Test updating non-existent team raises NotFoundError."""
        # Arrange
        team_update = TeamUpdate(name="Updated")

        # Act & Assert
        from src.common.errors import NotFoundError
        with pytest.raises(NotFoundError):
            manager.update_team(
                db_session, "nonexistent-id", team_update, current_user_id="user1"
            )

    # =====================================================================
    # Delete Team Tests
    # =====================================================================

    def test_delete_team_success(self, manager, db_session, sample_team_db):
        """Test successful team deletion."""
        # Act
        result = manager.delete_team(db_session, sample_team_db.id)

        # Assert
        assert result is not None
        
        # Verify team is deleted
        deleted = manager.get_team_by_id(db_session, sample_team_db.id)
        assert deleted is None

    def test_delete_team_not_found(self, manager, db_session):
        """Test deleting non-existent team raises NotFoundError."""
        # Act & Assert
        from src.common.errors import NotFoundError
        with pytest.raises(NotFoundError):
            manager.delete_team(db_session, "nonexistent-id")

    # =====================================================================
    # Team Member Management Tests
    # =====================================================================

    def test_add_team_member_success(self, manager, db_session, sample_team_db):
        """Test adding a member to a team."""
        # Arrange
        member_data = TeamMemberCreate(
            member_type="user",
            member_identifier="user123@example.com",
        )

        # Act
        result = manager.add_team_member(
            db_session, sample_team_db.id, member_data, current_user_id="user1"
        )

        # Assert
        assert result is not None
        assert result.member_identifier == "user123@example.com"
        assert result.member_type == "user"

    def test_get_team_members_empty(self, manager, db_session, sample_team_db):
        """Test getting members when team has none."""
        # Act
        result = manager.get_team_members(db_session, sample_team_db.id)

        # Assert
        assert result == []

    def test_get_team_members_multiple(self, manager, db_session, sample_team_db):
        """Test getting multiple team members."""
        # Arrange - Add 2 members
        for i in range(2):
            member_db = TeamMemberDb(
                id=str(uuid.uuid4()),
                team_id=sample_team_db.id,
                member_type="user",
                member_identifier=f"user{i}@example.com",
                added_by="test-user",
            )
            db_session.add(member_db)
        db_session.commit()

        # Act
        result = manager.get_team_members(db_session, sample_team_db.id)

        # Assert
        assert len(result) == 2

    def test_update_team_member_success(self, manager, db_session, sample_team_db):
        """Test updating a team member's app role override."""
        # Arrange - Add a member
        member_db = TeamMemberDb(
            id=str(uuid.uuid4()),
            team_id=sample_team_db.id,
            member_type="user",
            member_identifier="user123@example.com",
            added_by="test-user",
        )
        db_session.add(member_db)
        db_session.commit()

        member_update = TeamMemberUpdate(app_role_override="role-123")

        # Act
        result = manager.update_team_member(
            db_session, sample_team_db.id, member_db.id, member_update, current_user_id="user1"
        )

        # Assert
        assert result is not None
        assert result.app_role_override == "role-123"

    def test_remove_team_member_success(self, manager, db_session, sample_team_db):
        """Test removing a team member."""
        # Arrange - Add a member
        member_db = TeamMemberDb(
            id=str(uuid.uuid4()),
            team_id=sample_team_db.id,
            member_type="user",
            member_identifier="user123@example.com",
            added_by="test-user",
        )
        db_session.add(member_db)
        db_session.commit()
        member_identifier = member_db.member_identifier  # Use identifier instead of ID

        # Act
        manager.remove_team_member(db_session, sample_team_db.id, member_identifier)
        
        # Assert - Verify member is removed
        members = manager.get_team_members(db_session, sample_team_db.id)
        assert len(members) == 0

    def test_remove_team_member_not_found(self, manager, db_session, sample_team_db):
        """Test removing non-existent team member."""
        # Act
        result = manager.remove_team_member(db_session, sample_team_db.id, "nonexistent-member-id")

        # Assert
        assert result is False

    # =====================================================================
    # Team Summary Tests
    # =====================================================================

    def test_get_teams_summary(self, manager, db_session):
        """Test getting team summary."""
        # Arrange - Create a team with members
        team_db = TeamDb(
            id=str(uuid.uuid4()),
            name="Test Team",
            created_by="test-user",
            updated_by="test-user",
            extra_metadata='{}',
        )
        db_session.add(team_db)
        db_session.commit()

        # Add a member
        member_db = TeamMemberDb(
            id=str(uuid.uuid4()),
            team_id=team_db.id,
            member_type="user",
            member_identifier="user123@example.com",
            added_by="test-user",
        )
        db_session.add(member_db)
        db_session.commit()

        # Act
        result = manager.get_teams_summary(db_session)

        # Assert
        assert len(result) == 1
        assert result[0].name == "Test Team"
        assert result[0].member_count == 1

