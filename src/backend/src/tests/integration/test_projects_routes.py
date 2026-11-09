"""
Integration tests for projects API endpoints
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


class TestProjectsRoutes:
    """Integration tests for projects API endpoints."""

    @pytest.fixture
    def sample_project_data(self):
        """Sample project data for testing."""
        return {
            "name": "Test Project",
            "description": "A test project for integration testing",
            "status": "active",
        }

    def test_list_projects(self, client: TestClient, db_session: Session):
        """Test getting projects list."""
        response = client.get("/api/projects")
        assert response.status_code == 200
        # Response should be a list
        assert isinstance(response.json(), list)

    def test_create_project(self, client: TestClient, db_session: Session, sample_project_data):
        """Test creating a project."""
        response = client.post("/api/projects", json=sample_project_data)
        assert response.status_code == 201

        data = response.json()
        assert data["name"] == "Test Project"
        assert data["description"] == "A test project for integration testing"
        assert "id" in data
        assert "created_at" in data

    def test_create_project_duplicate_name(self, client: TestClient, db_session: Session, sample_project_data):
        """Test creating project with duplicate name should fail."""
        # Create first project
        response1 = client.post("/api/projects", json=sample_project_data)
        assert response1.status_code == 201

        # Try to create duplicate
        response2 = client.post("/api/projects", json=sample_project_data)
        assert response2.status_code == 409  # Conflict

    def test_get_project_by_id(self, client: TestClient, db_session: Session, sample_project_data):
        """Test getting a specific project by ID."""
        # Create project first
        create_response = client.post("/api/projects", json=sample_project_data)
        project_id = create_response.json()["id"]

        # Get the project
        response = client.get(f"/api/projects/{project_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Project"

    def test_get_project_not_found(self, client: TestClient, db_session: Session):
        """Test getting a non-existent project."""
        response = client.get("/api/projects/nonexistent-id")
        assert response.status_code == 404

    def test_update_project(self, client: TestClient, db_session: Session, sample_project_data):
        """Test updating a project."""
        # Create project first
        create_response = client.post("/api/projects", json=sample_project_data)
        project_id = create_response.json()["id"]

        # Update the project
        update_data = {
            "name": "Updated Project Name",
            "description": "Updated description",
        }
        response = client.put(f"/api/projects/{project_id}", json=update_data)
        assert response.status_code == 200
        assert response.json()["name"] == "Updated Project Name"

    def test_delete_project(self, client: TestClient, db_session: Session, sample_project_data):
        """Test deleting a project."""
        # Create project first
        create_response = client.post("/api/projects", json=sample_project_data)
        project_id = create_response.json()["id"]

        # Delete the project
        response = client.delete(f"/api/projects/{project_id}")
        assert response.status_code == 200

        # Verify it's deleted
        get_response = client.get(f"/api/projects/{project_id}")
        assert get_response.status_code == 404

    def test_projects_pagination(self, client: TestClient, db_session: Session):
        """Test project listing with pagination."""
        # Create multiple projects
        for i in range(5):
            client.post("/api/projects", json={
                "name": f"Project {i}",
                "description": f"Description {i}",
                "status": "active",
            })

        # Test first page
        response = client.get("/api/projects?skip=0&limit=3")
        assert response.status_code == 200
        data = response.json()
        assert len(data) <= 3

    def test_create_project_validation_error(self, client: TestClient):
        """Test project creation with invalid data."""
        invalid_data = {
            "description": "Missing name field"
        }
        response = client.post("/api/projects", json=invalid_data)
        assert response.status_code == 422

    def test_get_project_summary(self, client: TestClient, db_session: Session, sample_project_data):
        """Test getting project summary (GET /api/projects/summary lists every project)."""
        # Create project first
        create_response = client.post("/api/projects", json=sample_project_data)
        project_id = create_response.json()["id"]

        # Get project summary
        response = client.get("/api/projects/summary")
        assert response.status_code == 200
        summary = next((p for p in response.json() if p["id"] == project_id), None)
        assert summary is not None
        assert summary["name"] == "Test Project"
        assert summary["team_count"] == 0
