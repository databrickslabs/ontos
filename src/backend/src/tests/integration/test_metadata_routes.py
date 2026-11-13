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


class TestAssetMetadataRoutes:
    """The asset detail view renders the metadata panel with entity_type="asset"."""

    @pytest.fixture
    def mock_ws(self, monkeypatch):
        """Workspace client for uploads, via get_workspace_client's MOCK_WORKSPACE_CLIENT hook."""
        import time
        from unittest.mock import MagicMock
        from src.common import workspace_client
        from src.controller.metadata_manager import MetadataManager

        ws = MagicMock()
        monkeypatch.setenv("MOCK_WORKSPACE_CLIENT", "true")
        monkeypatch.setitem(workspace_client._CLIENT_CACHE, "mock_ws", (ws, "mock", time.time()))
        monkeypatch.setattr(MetadataManager, "ensure_volume_path", lambda self, ws, settings, base_dir: "/Volumes/c/s/v")
        return ws

    def test_create_rich_text_for_asset(self, client: TestClient):
        response = client.post(
            "/api/entities/asset/rich-texts",
            params={"entity_id": "asset-1"},
            json={"entity_id": "asset-1", "entity_type": "asset", "title": "Note", "content_markdown": "Body"},
        )
        assert response.status_code == 201, response.text

        listed = client.get("/api/entities/asset/rich-texts", params={"entity_id": "asset-1"})
        assert [rt["id"] for rt in listed.json()] == [response.json()["id"]]

    def test_create_link_for_asset(self, client: TestClient):
        response = client.post(
            "/api/entities/asset/links",
            params={"entity_id": "asset-1"},
            json={"entity_id": "asset-1", "entity_type": "asset", "title": "Link", "url": "https://example.com"},
        )
        assert response.status_code == 201, response.text

    def test_upload_document_for_asset(self, client: TestClient, mock_ws):
        response = client.post(
            "/api/entities/asset/documents",
            params={"entity_id": "asset-1"},
            data={"title": "Snapshot"},
            files={"file": ("snapshot.png", b"\x89PNG", "image/png")},
        )
        assert response.status_code == 201, response.text
        assert response.json()["entity_type"] == "asset"
        mock_ws.files.upload.assert_called_once()

    def test_upload_document_rejects_unknown_entity_type_before_writing(self, client: TestClient, mock_ws):
        response = client.post(
            "/api/entities/not_an_entity/documents",
            params={"entity_id": "x-1"},
            data={"title": "Snapshot"},
            files={"file": ("snapshot.png", b"\x89PNG", "image/png")},
        )
        assert response.status_code == 400, response.text
        assert response.json()["detail"]["code"] == "unsupported_entity_type"
        mock_ws.files.upload.assert_not_called()
