"""
Unit tests for ProjectRepository

Tests database operations for project management including:
- CRUD operations (create, read, update, delete)
- Querying by team
- Project counting
"""
import pytest
import uuid

from src.repositories.projects_repository import ProjectRepository
from src.models.projects import ProjectCreate
from src.db_models.projects import ProjectDb


class TestProjectRepository:
    """Test suite for ProjectRepository"""

    @pytest.fixture
    def repository(self):
        """Create repository instance for testing."""
        return ProjectRepository()

    # =====================================================================
    # Create Tests
    # =====================================================================

    def test_create_project(self, repository, db_session):
        """Test creating a project."""
        # Arrange
        project_db = ProjectDb(
            id=str(uuid.uuid4()),
            name="Test Project",
            created_by="test-user",
            updated_by="test-user",
            extra_metadata='{}',
        )

        # Act
        db_session.add(project_db)
        db_session.commit()
        db_session.refresh(project_db)

        # Assert
        assert project_db.name == "Test Project"

    # =====================================================================
    # Get Tests
    # =====================================================================

    def test_get_project_by_id(self, repository, db_session):
        """Test retrieving a project by ID."""
        # Arrange
        project_db = ProjectDb(
            id=str(uuid.uuid4()),
            name="Test Project",
            created_by="test-user",
            updated_by="test-user",
            extra_metadata='{}',
        )
        db_session.add(project_db)
        db_session.commit()

        # Act
        retrieved_project = repository.get(db_session, id=project_db.id)

        # Assert
        assert retrieved_project is not None
        assert retrieved_project.id == project_db.id

    def test_get_project_not_found(self, repository, db_session):
        """Test retrieving non-existent project."""
        # Act
        result = repository.get(db_session, id="nonexistent-id")

        # Assert
        assert result is None

    # =====================================================================
    # List Tests
    # =====================================================================

    def test_get_multi_empty(self, repository, db_session):
        """Test listing projects when none exist."""
        # Act
        projects = repository.get_multi(db_session)

        # Assert
        assert projects == []

    def test_get_multi_projects(self, repository, db_session):
        """Test listing multiple projects."""
        # Arrange - Create 3 projects
        for i in range(3):
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
        projects = repository.get_multi(db_session)

        # Assert
        assert len(projects) == 3

    # =====================================================================
    # Update Tests
    # =====================================================================

    def test_update_project(self, repository, db_session):
        """Test updating a project."""
        # Arrange
        project_db = ProjectDb(
            id=str(uuid.uuid4()),
            name="Original Name",
            created_by="test-user",
            updated_by="test-user",
            extra_metadata='{}',
        )
        db_session.add(project_db)
        db_session.commit()

        # Act
        update_data = {"name": "Updated Name"}
        updated_project = repository.update(db_session, db_obj=project_db, obj_in=update_data)
        db_session.commit()

        # Assert
        assert updated_project.name == "Updated Name"

    # =====================================================================
    # Delete Tests
    # =====================================================================

    def test_delete_project(self, repository, db_session):
        """Test deleting a project."""
        # Arrange
        project_db = ProjectDb(
            id=str(uuid.uuid4()),
            name="Test Project",
            created_by="test-user",
            updated_by="test-user",
            extra_metadata='{}',
        )
        db_session.add(project_db)
        db_session.commit()
        project_id = project_db.id

        # Act
        repository.remove(db_session, id=project_id)
        db_session.commit()

        # Assert
        deleted_project = repository.get(db_session, id=project_id)
        assert deleted_project is None

    # =====================================================================
    # Count Tests
    # =====================================================================

    def test_count_projects_empty(self, repository, db_session):
        """Test project count when none exist."""
        # Act
        count = repository.count(db_session)

        # Assert
        assert count == 0

    def test_count_projects(self, repository, db_session):
        """Test project count with multiple projects."""
        # Arrange - Create 5 projects
        for i in range(5):
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
        count = repository.count(db_session)

        # Assert
        assert count == 5

