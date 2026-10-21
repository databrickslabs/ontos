"""
Integration tests for tags API endpoints
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


class TestTagsRoutes:
    """Integration tests for tags API endpoints."""

    @pytest.fixture
    def sample_namespace_data(self):
        """Sample namespace data for testing."""
        return {
            "name": "test-namespace",
            "description": "Test namespace for integration testing",
        }

    @pytest.fixture
    def sample_tag_data(self):
        """Sample tag data for testing."""
        return {
            "namespace_name": "test-namespace",
            "name": "test-tag",
            "description": "Test tag",
        }

    @pytest.fixture
    def created_tag(self, client: TestClient, sample_namespace_data, sample_tag_data):
        """A tag in its own namespace, created through the API."""
        namespace = client.post("/api/tags/namespaces", json=sample_namespace_data)
        assert namespace.status_code == 201, namespace.text
        response = client.post("/api/tags", json=sample_tag_data)
        assert response.status_code == 201, response.text
        return response.json()

    def test_get_namespaces(self, client: TestClient, db_session: Session):
        """Test getting tag namespaces."""
        response = client.get("/api/tags/namespaces")
        assert response.status_code == 200
        # Should return list of namespaces
        assert isinstance(response.json(), list)

    def test_create_namespace(self, client: TestClient, db_session: Session, sample_namespace_data):
        """Test creating a tag namespace."""
        response = client.post("/api/tags/namespaces", json=sample_namespace_data)
        assert response.status_code in [200, 201]
        data = response.json()
        assert "name" in data or "id" in data

    def test_get_tags_for_namespace(self, client: TestClient, db_session: Session):
        """Test getting tags for a namespace."""
        response = client.get("/api/tags/namespace/test-namespace")
        assert response.status_code in [200, 404]

    def test_create_tag(self, client: TestClient, db_session: Session, created_tag):
        """Test creating a tag."""
        assert created_tag["name"] == "test-tag"
        assert created_tag["description"] == "Test tag"

        fetched = client.get(f"/api/tags/{created_tag['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["name"] == "test-tag"

    def test_assign_tag_to_entity(self, client: TestClient, db_session: Session, created_tag):
        """Test assigning a tag to an entity."""
        response = client.post(
            "/api/entities/data_product/test-product-123/tags:add",
            params={"tag_id": created_tag["id"]},
        )
        assert response.status_code == 200, response.text
        assigned = response.json()
        assert assigned["tag_id"] == created_tag["id"]
        assert assigned["fully_qualified_name"] == "test-namespace/test-tag"

    def test_get_tags_for_entity(self, client: TestClient, db_session: Session, created_tag):
        """Test getting tags for an entity."""
        client.post(
            "/api/entities/data_product/test-product-123/tags:add",
            params={"tag_id": created_tag["id"]},
        ).raise_for_status()

        response = client.get("/api/entities/data_product/test-product-123/tags")
        assert response.status_code == 200
        assert [t["tag_id"] for t in response.json()] == [created_tag["id"]]

        other = client.get("/api/entities/data_product/another-product/tags")
        assert other.status_code == 200
        assert other.json() == []

    def test_remove_tag_from_entity(self, client: TestClient, db_session: Session):
        """Test removing a tag from an entity."""
        response = client.delete("/api/tags/entity/data_product/test-product-123/namespace/test/tag/test-tag")
        assert response.status_code in [200, 204, 404]

    def test_create_namespace_validation_error(self, client: TestClient):
        """Test namespace creation with invalid data."""
        invalid_data = {}
        response = client.post("/api/tags/namespaces", json=invalid_data)
        assert response.status_code == 422

