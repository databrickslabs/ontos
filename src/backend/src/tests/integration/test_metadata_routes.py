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
        assert response.status_code == 422, response.text
        mock_ws.files.upload.assert_not_called()


class TestMergedMetadataSourceAccess:
    """/metadata/merged only inherits from contracts and assets the caller may open."""

    @pytest.fixture
    def product(self, db_session: Session):
        from uuid import uuid4
        from src.db_models.assets import AssetDb, AssetTypeDb
        from src.db_models.data_contracts import DataContractDb
        from src.db_models.data_products import DataProductDb, OutputPortDb
        from src.db_models.metadata import RichTextMetadataDb

        product = DataProductDb(
            id=str(uuid4()), name="Orders", status="active", max_level_inheritance=99,
        )
        draft = DataContractDb(
            id=str(uuid4()), name="team-b-draft", version="0.1.0", status="draft",
            version_family_id=str(uuid4()), owner_team_id="team-b",
        )
        db_session.add_all([product, draft])
        dashboard_type = (
            db_session.query(AssetTypeDb).filter(AssetTypeDb.name == "Dashboard").first()
        )
        if dashboard_type is None:  # seeded at startup; create it if the seed is absent
            dashboard_type = AssetTypeDb(id=uuid4(), name="Dashboard")
            db_session.add(dashboard_type)
        db_session.flush()
        dashboard = AssetDb(
            id=uuid4(), name="Overview", asset_type_id=dashboard_type.id,
            location="https://bi/overview",
        )
        db_session.add(dashboard)
        db_session.flush()
        db_session.add_all([
            OutputPortDb(
                id=str(uuid4()), product_id=product.id, name="p", version="1.0.0",
                contract_id=draft.id,
            ),
            OutputPortDb(
                id=str(uuid4()), product_id=product.id, name="d", version="1.0.0",
                asset_identifier="https://bi/overview",
            ),
            RichTextMetadataDb(
                id=uuid4(), entity_type="data_contract", entity_id=draft.id, title="Draft terms",
                content_markdown="x", level=50, inheritable=True,
            ),
            RichTextMetadataDb(
                id=uuid4(), entity_type="asset", entity_id=str(dashboard.id),
                title="Dashboard notes",
                content_markdown="x", level=50, inheritable=True,
            ),
        ])
        db_session.flush()
        return product

    @pytest.fixture
    def access(self, monkeypatch):
        """Set the caller's contracts-admin and assets READ_WRITE rights."""
        from src.app import app
        from src.controller import teams_manager as tm
        from src.routes import assets_routes
        from src.routes.business_lineage_routes import contracts_feature_admin

        monkeypatch.setattr(tm.teams_manager, "get_teams_for_user", lambda db, email, groups: [])

        def set_access(*, contracts_admin: bool, assets_rw: bool):
            async def admin_override():
                return contracts_admin
            app.dependency_overrides[contracts_feature_admin] = admin_override
            monkeypatch.setattr(
                assets_routes, "_user_has_assets_feature", lambda request, user, level: assets_rw,
            )

        yield set_access
        app.dependency_overrides.pop(contracts_feature_admin, None)

    def _titles(self, client: TestClient, product) -> list:
        response = client.get(
            "/api/entities/data_product/metadata/merged", params={"entity_id": product.id},
        )
        assert response.status_code == 200, response.text
        return [rt["title"] for rt in response.json()["rich_texts"]]

    def test_consumer_does_not_inherit_unreadable_sources(
        self, client: TestClient, product, access, monkeypatch,
    ):
        from src.controller.assets_manager import AssetsManager

        access(contracts_admin=False, assets_rw=False)
        # The dashboard is not linked to any product the caller can access
        monkeypatch.setattr(
            AssetsManager, "resolve_accessible_asset_ids", lambda self, db, **kw: [],
        )
        assert self._titles(client, product) == []

    def test_privileged_caller_inherits_all_sources(self, client: TestClient, product, access):
        access(contracts_admin=True, assets_rw=True)
        assert sorted(self._titles(client, product)) == ["Dashboard notes", "Draft terms"]
