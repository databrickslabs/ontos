"""
Integration tests for comments API endpoints
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


PROJECT_ID = "comments-test-project"


def _comments_url(entity_type: str, entity_id: str) -> str:
    return f"/api/entities/{entity_type}/{entity_id}/comments"


class TestCommentsRoutes:
    """Integration tests for comments API endpoints."""

    @pytest.fixture
    def sample_comment_data(self):
        """Sample comment data for testing."""
        return {
            "entity_id": "test-entity-123",
            "entity_type": "data_product",
            "title": "Test Comment",
            "comment": "This is a test comment",
            "audience": None,
        }

    @pytest.fixture
    def created_comment(self, client: TestClient, sample_comment_data):
        """A project-scoped comment: any user with write access may create one."""
        sample_comment_data["project_id"] = PROJECT_ID
        response = client.post(
            _comments_url("data_product", "test-entity-123"), json=sample_comment_data
        )
        assert response.status_code == 201, response.text
        return response.json()

    def test_get_comments_for_entity(self, client: TestClient, created_comment):
        """Test getting comments for an entity."""
        response = client.get(
            _comments_url("data_product", "test-entity-123"), params={"project_id": PROJECT_ID}
        )
        assert response.status_code == 200
        data = response.json()
        assert [c["id"] for c in data["comments"]] == [created_comment["id"]]
        assert data["comments"][0]["comment"] == "This is a test comment"

        other = client.get(
            _comments_url("data_product", "another-entity"), params={"project_id": PROJECT_ID}
        )
        assert other.status_code == 200
        assert other.json()["comments"] == []

    def test_create_comment(self, client: TestClient, db_session: Session, sample_comment_data):
        """Test creating a comment."""
        response = client.post(
            _comments_url("data_product", "test-entity-123"), json=sample_comment_data
        )
        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["title"] == "Test Comment"
        assert data["created_by"] == "test@example.com"

    def test_update_comment(self, client: TestClient, created_comment):
        """Test updating a comment."""
        update_data = {
            "title": "Updated Comment Title",
            "comment": "Updated comment text",
        }
        response = client.put(f"/api/comments/{created_comment['id']}", json=update_data)
        assert response.status_code == 200
        assert response.json()["title"] == "Updated Comment Title"
        assert response.json()["comment"] == "Updated comment text"

        fetched = client.get(f"/api/comments/{created_comment['id']}")
        assert fetched.json()["comment"] == "Updated comment text"

    def test_delete_comment(self, client: TestClient, created_comment):
        """Test deleting a comment."""
        response = client.delete(f"/api/comments/{created_comment['id']}")
        assert response.status_code == 204

        remaining = client.get(
            _comments_url("data_product", "test-entity-123"), params={"project_id": PROJECT_ID}
        )
        assert remaining.json()["comments"] == []

    def test_create_comment_with_audience(self, client: TestClient, db_session: Session):
        """Test creating a comment with specific audience."""
        comment_data = {
            "entity_id": "test-entity-456",
            "entity_type": "data_contract",
            "title": "Restricted Comment",
            "comment": "This comment is for specific groups only",
            "audience": ["admins", "data_stewards"],
            "project_id": PROJECT_ID,
        }
        response = client.post(_comments_url("data_contract", "test-entity-456"), json=comment_data)
        assert response.status_code == 201
        assert sorted(response.json()["audience"]) == ["admins", "data_stewards"]

    def test_create_comment_validation_error(self, client: TestClient):
        """Test comment creation with invalid data."""
        invalid_data = {
            "comment": "Missing required fields"
        }
        response = client.post(_comments_url("data_product", "test-entity-123"), json=invalid_data)
        assert response.status_code == 422
