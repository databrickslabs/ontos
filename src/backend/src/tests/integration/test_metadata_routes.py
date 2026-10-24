"""
Integration tests for metadata API endpoints
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


class TestMetadataRoutes:
    """Integration tests for metadata API endpoints."""

    @pytest.fixture
    def sample_rich_text_data(self):
        """Sample rich text metadata for testing."""
        return {
            "entity_id": "test-entity-123",
            "entity_type": "data_product",
            "title": "Test Documentation",
            "short_description": "Short description",
            "content_markdown": "# Test Content\nThis is test markdown content.",
        }

    @pytest.fixture
    def sample_link_data(self):
        """Sample link metadata for testing."""
        return {
            "entity_id": "test-entity-456",
            "entity_type": "data_contract",
            "title": "Related Link",
            "short_description": "Link description",
            "url": "https://example.com/related",
        }

    @pytest.fixture
    def created_rich_text(self, client: TestClient, sample_rich_text_data):
        response = client.post(
            "/api/entities/data_product/rich-texts",
            params={"entity_id": "test-entity-123"},
            json=sample_rich_text_data,
        )
        assert response.status_code == 201, response.text
        return response.json()

    def test_get_metadata_for_entity(self, client: TestClient, created_rich_text):
        """Test getting all metadata for an entity."""
        response = client.get(
            "/api/entities/data_product/metadata/merged", params={"entity_id": "test-entity-123"}
        )
        assert response.status_code == 200
        data = response.json()
        assert [rt["id"] for rt in data["rich_texts"]] == [created_rich_text["id"]]
        assert data["links"] == []
        assert data["documents"] == []

    def test_create_rich_text(self, client: TestClient, db_session: Session, sample_rich_text_data):
        """Test creating rich text metadata."""
        response = client.post(
            "/api/entities/data_product/rich-texts",
            params={"entity_id": "test-entity-123"},
            json=sample_rich_text_data,
        )
        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["title"] == "Test Documentation"

        listed = client.get(
            "/api/entities/data_product/rich-texts", params={"entity_id": "test-entity-123"}
        )
        assert [rt["id"] for rt in listed.json()] == [data["id"]]

    def test_create_link(self, client: TestClient, db_session: Session, sample_link_data):
        """Test creating link metadata."""
        response = client.post(
            "/api/entities/data_contract/links",
            params={"entity_id": "test-entity-456"},
            json=sample_link_data,
        )
        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["url"] == "https://example.com/related"

        listed = client.get(
            "/api/entities/data_contract/links", params={"entity_id": "test-entity-456"}
        )
        assert [link["id"] for link in listed.json()] == [data["id"]]

    def test_update_rich_text(self, client: TestClient, created_rich_text):
        """Test updating rich text metadata."""
        update_data = {
            "title": "Updated Title",
            "content_markdown": "# Updated Content",
        }
        response = client.put(f"/api/rich-texts/{created_rich_text['id']}", json=update_data)
        assert response.status_code == 200
        assert response.json()["title"] == "Updated Title"
        assert response.json()["content_markdown"] == "# Updated Content"

    def test_delete_metadata(self, client: TestClient, created_rich_text):
        """Test deleting metadata."""
        response = client.delete(f"/api/rich-texts/{created_rich_text['id']}")
        assert response.status_code == 204

        listed = client.get(
            "/api/entities/data_product/rich-texts", params={"entity_id": "test-entity-123"}
        )
        assert listed.json() == []

    def test_create_rich_text_validation_error(self, client: TestClient):
        """Test rich text creation with invalid data."""
        invalid_data = {
            "title": "Missing required fields"
        }
        response = client.post(
            "/api/entities/data_product/rich-texts",
            params={"entity_id": "test-entity-123"},
            json=invalid_data,
        )
        assert response.status_code == 422
