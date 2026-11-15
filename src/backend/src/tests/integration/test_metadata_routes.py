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

    @pytest.fixture
    def asset_id(self, db_session: Session) -> str:
        """An existing asset: the metadata routes answer 404 for an unknown one (#1342)."""
        from src.db_models.assets import AssetDb, AssetTypeDb

        asset_type = AssetTypeDb(name="Dashboard (metadata routes)", category="analytics")
        db_session.add(asset_type)
        db_session.flush()
        asset = AssetDb(name="sales", asset_type_id=asset_type.id)
        db_session.add(asset)
        db_session.flush()
        return str(asset.id)

    def test_create_rich_text_for_asset(self, client: TestClient, asset_id):
        response = client.post(
            "/api/entities/asset/rich-texts",
            params={"entity_id": asset_id},
            json={
                "entity_id": asset_id, "entity_type": "asset", "title": "Note",
                "content_markdown": "Body",
            },
        )
        assert response.status_code == 201, response.text

        listed = client.get("/api/entities/asset/rich-texts", params={"entity_id": asset_id})
        assert [rt["id"] for rt in listed.json()] == [response.json()["id"]]

    def test_create_link_for_asset(self, client: TestClient, asset_id):
        response = client.post(
            "/api/entities/asset/links",
            params={"entity_id": asset_id},
            json={
                "entity_id": asset_id, "entity_type": "asset", "title": "Link",
                "url": "https://example.com",
            },
        )
        assert response.status_code == 201, response.text

    def test_upload_document_for_asset(self, client: TestClient, mock_ws, asset_id):
        response = client.post(
            "/api/entities/asset/documents",
            params={"entity_id": asset_id},
            data={"title": "Snapshot"},
            files={"file": ("snapshot.png", b"\x89PNG", "image/png")},
        )
        assert response.status_code == 201, response.text
        assert response.json()["entity_type"] == "asset"
        mock_ws.files.upload.assert_called_once()

    def test_uploaded_library_documents_are_listed_in_the_shared_library(self, client: TestClient, mock_ws):
        response = client.post(
            "/api/metadata/shared/documents",
            data={"title": "Glossary handbook", "level": "10", "inheritable": "false"},
            files={"file": ("handbook.pdf", b"%PDF", "application/pdf")},
        )
        assert response.status_code == 201, response.text
        created = response.json()
        assert created["is_shared"] is True
        assert (created["level"], created["inheritable"]) == (10, False)

        shared = client.get("/api/metadata/shared")
        assert shared.status_code == 200, shared.text
        assert created["id"] in [d["id"] for d in shared.json()["documents"]]

    def _assert_own_files(self, documents, mock_ws, base_dir, filename):
        """Each document has a file of its own at ``<base_dir>/<uuid>/<filename>``.

        It keeps the uploaded file name, and its directory is the one created.
        """
        import re

        paths = [d["storage_path"] for d in documents]
        assert len(set(paths)) == len(paths), paths
        uploads = mock_ws.files.upload.call_args_list
        assert [c.args[0] for c in uploads] == paths
        assert all(c.kwargs.get("overwrite") is False for c in uploads)
        created = [c.args[0] for c in mock_ws.files.create_directory.call_args_list]
        own_file = re.compile(rf"/Volumes/c/s/v/{re.escape(base_dir)}/[0-9a-f]{{32}}/{re.escape(filename)}")
        for document, path in zip(documents, paths, strict=True):
            assert own_file.fullmatch(path), path
            assert path.rsplit("/", 1)[0] in created
            assert document["original_filename"] == filename

    def test_same_file_name_on_one_entity_keeps_both_files(self, client: TestClient, mock_ws, asset_id):
        """#1691: a second upload with the same file name doesn't overwrite the first one's file."""
        documents = []
        for title in ("Snapshot Monday", "Snapshot Tuesday"):
            response = client.post(
                "/api/entities/asset/documents",
                params={"entity_id": asset_id},
                data={"title": title},
                files={"file": ("snapshot.png", b"\x89PNG", "image/png")},
            )
            assert response.status_code == 201, response.text
            documents.append(response.json())

        self._assert_own_files(documents, mock_ws, f"uploads/asset/{asset_id}", "snapshot.png")

    def test_same_file_name_in_the_shared_library_keeps_both_files(self, client: TestClient, mock_ws):
        """#1691: two library documents with the same file name keep their own files."""
        documents = []
        for title in ("Handbook 2025", "Handbook 2026"):
            response = client.post(
                "/api/metadata/shared/documents",
                data={"title": title},
                files={"file": ("handbook.pdf", b"%PDF", "application/pdf")},
            )
            assert response.status_code == 201, response.text
            documents.append(response.json())

        self._assert_own_files(documents, mock_ws, "uploads/__shared__", "handbook.pdf")

    def test_shared_upload_rejects_an_invalid_request_before_writing(self, client: TestClient, mock_ws):
        response = client.post(
            "/api/metadata/shared/documents",
            data={"title": "Handbook", "level": "1000"},
            files={"file": ("handbook.pdf", b"%PDF", "application/pdf")},
        )
        assert response.status_code == 422, response.text
        mock_ws.files.upload.assert_not_called()

    @pytest.mark.parametrize("url, record", [
        ("/api/entities/asset/documents", "create_document_record"),
        ("/api/metadata/shared/documents", "create_shared_document_record"),
    ])
    def test_a_file_whose_row_isnt_stored_is_deleted(
        self, client: TestClient, mock_ws, asset_id, monkeypatch, url, record,
    ):
        from src.controller.metadata_manager import MetadataManager

        def _fail(*_args, **_kwargs):
            raise RuntimeError("database down")

        monkeypatch.setattr(MetadataManager, record, _fail)
        response = client.post(
            url,
            params={"entity_id": asset_id} if "entities" in url else None,
            data={"title": "Snapshot"},
            files={"file": ("snapshot.png", b"\x89PNG", "image/png")},
        )
        assert response.status_code == 500, response.text
        uploaded = mock_ws.files.upload.call_args.args[0]
        mock_ws.files.delete.assert_called_once_with(uploaded)
        mock_ws.files.delete_directory.assert_called_once_with(uploaded.rsplit("/", 1)[0])


    def test_upload_document_rejects_unknown_entity_type_before_writing(self, client: TestClient, mock_ws):
        response = client.post(
            "/api/entities/not_an_entity/documents",
            params={"entity_id": "x-1"},
            data={"title": "Snapshot"},
            files={"file": ("snapshot.png", b"\x89PNG", "image/png")},
        )
        assert response.status_code == 422, response.text
        mock_ws.files.upload.assert_not_called()


class TestDocumentDeleteRemovesItsFile:
    """Deleting one document deletes its uploaded file once the delete commits (#1691)."""

    @pytest.fixture
    def files(self, mock_workspace_client):
        mock_workspace_client.files.reset_mock()
        mock_workspace_client.files.delete.side_effect = None
        return mock_workspace_client.files

    def _document(self, db_session: Session, storage_path: str, **kwargs) -> str:
        from src.db_models.metadata import DocumentMetadataDb

        row = DocumentMetadataDb(
            entity_type="data_domain", entity_id="__shared__", is_shared=True, title="Handbook",
            original_filename="handbook.pdf", storage_path=storage_path, **kwargs,
        )
        db_session.add(row)
        db_session.flush()
        return str(row.id)

    def test_the_file_and_its_upload_directory_go(self, client: TestClient, db_session: Session, files):
        upload_dir = f"/Volumes/c/s/v/uploads/__shared__/{'a' * 32}"
        doc_id = self._document(db_session, f"{upload_dir}/handbook.pdf")

        response = client.delete(f"/api/documents/{doc_id}")

        assert response.status_code == 204, response.text
        files.delete.assert_called_once_with(f"{upload_dir}/handbook.pdf")
        files.delete_directory.assert_called_once_with(upload_dir)

    def test_a_file_two_older_documents_share_stays_until_the_last_one_goes(
        self, client: TestClient, db_session: Session, files,
    ):
        """Before #1691, same-named uploads shared one file in the base directory."""
        shared_path = "/Volumes/c/s/v/uploads/__shared__/handbook.pdf"
        first = self._document(db_session, shared_path)
        second = self._document(db_session, shared_path)

        assert client.delete(f"/api/documents/{first}").status_code == 204
        files.delete.assert_not_called()

        assert client.delete(f"/api/documents/{second}").status_code == 204
        files.delete.assert_called_once_with(shared_path)
        files.delete_directory.assert_not_called()  # the base directory isn't the upload's own

    def test_an_imported_documents_source_file_is_never_deleted(
        self, client: TestClient, db_session: Session, files,
    ):
        source = "/Volumes/main/docs/context/glossary.md"
        doc_id = self._document(db_session, source, source_path=source, content_hash="h")

        assert client.delete(f"/api/documents/{doc_id}").status_code == 204
        files.delete.assert_not_called()


class TestDocumentUploadInvalidVolume:
    """An unusable volume setting answers a coded 400 on both upload routes, not a 500."""

    @pytest.fixture(autouse=True)
    def invalid_volume(self, test_settings, monkeypatch):
        import time
        from unittest.mock import MagicMock
        from src.common import config as _config, workspace_client

        monkeypatch.setenv("MOCK_WORKSPACE_CLIENT", "true")
        monkeypatch.setitem(
            workspace_client._CLIENT_CACHE, "mock_ws", (MagicMock(), "mock", time.time())
        )
        test_settings.DATABRICKS_VOLUME = "a.b"
        # The upload routes read the process-wide settings
        monkeypatch.setattr(_config, "_settings", test_settings)

    @pytest.fixture
    def asset_id(self, db_session: Session) -> str:
        """An existing asset: the upload route answers 404 for an unknown one (#1354)."""
        from src.db_models.assets import AssetDb, AssetTypeDb

        asset_type = AssetTypeDb(name="Dashboard (volume upload)", category="analytics")
        db_session.add(asset_type)
        db_session.flush()
        asset = AssetDb(name="sales", asset_type_id=asset_type.id)
        db_session.add(asset)
        db_session.flush()
        return str(asset.id)

    def _assert_coded(self, response):
        assert response.status_code == 400, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "volume_invalid"
        assert detail["params"]["value"] == "a.b"

    def test_a_cleared_volume_answers_a_coded_400_not_a_500(
        self, client: TestClient, test_settings, asset_id, monkeypatch
    ):
        from src.common import authorization
        from src.common.features import FeatureAccessLevel

        async def _resolve(*_args, **_kwargs):
            rw = FeatureAccessLevel.READ_WRITE
            return {"data-domains": rw, "assets": rw}

        # With a volume set the routes fail before the permission checks; with none they don't.
        monkeypatch.setattr(authorization, "resolve_effective_permissions", _resolve)
        test_settings.DATABRICKS_VOLUME = None
        for url, extra in (
            ("/api/entities/asset/documents", {"params": {"entity_id": asset_id}}),
            ("/api/metadata/shared/documents", {}),
        ):
            response = client.post(
                url,
                data={"title": "Snapshot"},
                files={"file": ("snapshot.png", b"\x89PNG", "image/png")},
                **extra,
            )
            assert response.status_code == 400, response.text
            assert response.json()["detail"]["code"] == "volume_not_configured"

    def test_entity_document_upload(self, client: TestClient, asset_id):
        response = client.post(
            "/api/entities/asset/documents",
            params={"entity_id": asset_id},
            data={"title": "Snapshot"},
            files={"file": ("snapshot.png", b"\x89PNG", "image/png")},
        )
        self._assert_coded(response)

    def test_shared_document_upload(self, client: TestClient):
        response = client.post(
            "/api/metadata/shared/documents",
            data={"title": "Shared"},
            files={"file": ("shared.png", b"\x89PNG", "image/png")},
        )
        self._assert_coded(response)


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

    def test_explicit_contract_ids_go_through_the_read_check(
        self, client: TestClient, db_session: Session, product, access,
    ):
        from src.db_models.data_contracts import DataContractDb

        draft = db_session.query(DataContractDb).filter(DataContractDb.name == "team-b-draft").one()
        access(contracts_admin=False, assets_rw=False)
        response = client.get(
            "/api/entities/data_domain/metadata/merged",
            params={"entity_id": "d-1", "contract_ids": draft.id},
        )
        assert response.status_code == 200, response.text
        assert response.json()["rich_texts"] == []
