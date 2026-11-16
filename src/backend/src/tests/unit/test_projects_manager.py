"""
Unit tests for ProjectsManager

Tests business logic for project management including:
- Project CRUD operations (create, read, list, update, delete)
- Team assignment to projects
- User project access checking
- Project summary views
"""
import pytest
from unittest.mock import Mock, MagicMock
import uuid
from sqlalchemy.orm import Session

from src.controller.projects_manager import ProjectsManager
from src.models.projects import ProjectCreate, ProjectUpdate
from src.db_models.projects import ProjectDb


class TestProjectsManager:
    """Test suite for ProjectsManager"""

    @pytest.fixture
    def manager(self, db_session):
        """Create ProjectsManager instance for testing."""
        return ProjectsManager()

    @pytest.fixture
    def sample_project_data(self):
        """Sample project data for testing."""
        return ProjectCreate(
            name="Test Project",
            description="A test project",
        )

    @pytest.fixture
    def sample_project_db(self, db_session, sample_project_data):
        """Create a sample project in the database."""
        project_db = ProjectDb(
            id=str(uuid.uuid4()),
            name=sample_project_data.name,
            description=sample_project_data.description,
            created_by="test-user",
            updated_by="test-user",
            extra_metadata='{}',
        )
        db_session.add(project_db)
        db_session.commit()
        db_session.refresh(project_db)
        return project_db

    # =====================================================================
    # Create Project Tests
    # =====================================================================

    def test_create_project_success(self, manager, db_session, sample_project_data):
        """Test successful project creation."""
        # Act
        result = manager.create_project(db_session, sample_project_data, current_user_id="user1")

        # Assert
        assert result is not None
        assert result.name == sample_project_data.name
        assert result.description == sample_project_data.description

    def test_create_project_with_team(self, manager, db_session):
        """Test creating project with team association."""
        # Arrange
        project_data = ProjectCreate(
            name="Project with Team",
            description="Project with team",
            team_id="team-123",
        )

        # Act
        result = manager.create_project(db_session, project_data, current_user_id="user1")

        # Assert
        assert result is not None
        assert result.name == "Project with Team"
        # Note: team_id validation requires actual team in DB - deferred to integration tests

    # =====================================================================
    # Get Project Tests
    # =====================================================================

    def test_get_project_by_id_exists(self, manager, db_session, sample_project_db):
        """Test retrieving an existing project."""
        # Act
        result = manager.get_project_by_id(db_session, sample_project_db.id)

        # Assert
        assert result is not None
        assert str(result.id) == sample_project_db.id
        assert result.name == sample_project_db.name

    def test_get_project_by_id_not_found(self, manager, db_session):
        """Test retrieving a non-existent project."""
        # Act
        result = manager.get_project_by_id(db_session, "nonexistent-id")

        # Assert
        assert result is None

    # =====================================================================
    # List Projects Tests
    # =====================================================================

    def test_get_all_projects_empty(self, manager, db_session):
        """Test listing projects when none exist."""
        # Act (as admin to bypass filtering)
        result = manager.get_all_projects(db_session, is_admin=True)

        # Assert
        assert result == []

    def test_get_all_projects_multiple(self, manager, db_session):
        """Test listing multiple projects."""
        # Arrange - Create 3 projects
        for i in range(3):
            project_db = ProjectDb(
                id=str(uuid.uuid4()),
                name=f"Project {i}",
                description=f"Description {i}",
                created_by="test-user",
                updated_by="test-user",
                extra_metadata='{}',
            )
            db_session.add(project_db)
        db_session.commit()

        # Act (as admin to see all projects)
        result = manager.get_all_projects(db_session, is_admin=True)

        # Assert
        assert len(result) == 3

    def test_get_all_projects_pagination(self, manager, db_session):
        """Test pagination for listing projects."""
        # Arrange - Create 10 projects
        for i in range(10):
            project_db = ProjectDb(
                id=str(uuid.uuid4()),
                name=f"Project {i}",
                created_by="test-user",
                updated_by="test-user",
                extra_metadata='{}',
            )
            db_session.add(project_db)
        db_session.commit()

        # Act (as admin with pagination)
        result = manager.get_all_projects(db_session, skip=0, limit=5, is_admin=True)

        # Assert
        assert len(result) == 5

    # =====================================================================
    # Update Project Tests
    # =====================================================================

    def test_update_project_success(self, manager, db_session, sample_project_db):
        """Test successful project update."""
        # Arrange
        project_update = ProjectUpdate(
            name="Updated Name",
            description="Updated description",
        )

        # Act
        result = manager.update_project(
            db_session, sample_project_db.id, project_update, current_user_id="user1"
        )

        # Assert
        assert result is not None
        assert result.name == "Updated Name"
        assert result.description == "Updated description"

    def test_update_project_not_found(self, manager, db_session):
        """Test updating non-existent project raises NotFoundError."""
        # Arrange
        project_update = ProjectUpdate(name="Updated")

        # Act & Assert
        from src.common.errors import NotFoundError
        with pytest.raises(NotFoundError):
            manager.update_project(
                db_session, "nonexistent-id", project_update, current_user_id="user1"
            )

    # =====================================================================
    # Delete Project Tests
    # =====================================================================

    def test_delete_project_success(self, manager, db_session, sample_project_db):
        """Test successful project deletion."""
        # Act
        result = manager.delete_project(db_session, sample_project_db.id)

        # Assert
        assert result is not None
        
        # Verify project is deleted
        deleted = manager.get_project_by_id(db_session, sample_project_db.id)
        assert deleted is None

    def test_delete_project_not_found(self, manager, db_session):
        """Test deleting non-existent project raises NotFoundError."""
        # Act & Assert
        from src.common.errors import NotFoundError
        with pytest.raises(NotFoundError):
            manager.delete_project(db_session, "nonexistent-id")

    # =====================================================================
    # Team Assignment Tests (Require actual team setup - deferred to integration tests)
    # =====================================================================

    def test_get_project_teams_no_team(self, manager, db_session, sample_project_db):
        """Test getting teams for a project with no team assigned."""
        # Act
        result = manager.get_project_teams(db_session, sample_project_db.id)

        # Assert
        # Project with no team should return empty list or handle gracefully
        assert isinstance(result, list)

    # =====================================================================
    # User Access Tests (Complex - require Settings, Teams setup)
    # =====================================================================

    def test_check_user_project_access_no_access(self, manager, db_session, sample_project_db):
        """Test checking user access when they have no access."""
        # Act
        result = manager.check_user_project_access(
            db_session, "user@example.com", [], sample_project_db.id
        )

        # Assert
        # User with no groups and project with no team should have no access
        assert result is False

    def test_get_user_projects_group_named_admin_is_not_admin(
        self, manager, db_session, sample_project_db
    ):
        """A group whose name contains "admin" gets only its team projects; the
        data product routes also resolve a caller's project scope this way."""
        result = manager.get_user_projects(
            db_session, "user@example.com", ["billing-admin-viewers"]
        )
        assert sample_project_db.id not in {p.id for p in result.projects}

        admin = manager.get_user_projects(db_session, "user@example.com", ["admins"], is_admin=True)
        assert sample_project_db.id in {p.id for p in admin.projects}

    # =====================================================================
    # Summary Tests
    # =====================================================================

    def test_get_projects_summary_empty(self, manager, db_session):
        """Test getting project summary when no projects exist."""
        # Act
        result = manager.get_projects_summary(db_session)

        # Assert
        assert result == []

    def test_get_projects_summary_with_projects(self, manager, db_session):
        """Test getting project summary with projects."""
        # Arrange - Create 2 projects
        for i in range(2):
            project_db = ProjectDb(
                id=str(uuid.uuid4()),
                name=f"Project {i}",
                created_by="test-user",
                updated_by="test-user",
                extra_metadata='{}',
            )
            db_session.add(project_db)
        db_session.commit()

        # Act
        result = manager.get_projects_summary(db_session)

        # Assert
        assert len(result) == 2

    # =====================================================================
    # Error Handling Tests
    # =====================================================================

    def test_create_project_with_invalid_data(self, manager, db_session):
        """Test creating project with minimal data."""
        # Arrange
        project_data = ProjectCreate(name="Minimal Project")

        # Act
        result = manager.create_project(db_session, project_data, current_user_id="user1")

        # Assert
        assert result is not None
        assert result.name == "Minimal Project"

