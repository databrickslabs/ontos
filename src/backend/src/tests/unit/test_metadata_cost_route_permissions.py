"""Metadata and cost routes authorize each entity kind with the feature that owns it.

Regression (review of #1092): every metadata and cost route checked ``data-domains``,
so write access to domains allowed notes, links, documents and cost items on data
products, contracts, policies and assets.
"""
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.common.api_errors import coded_http_exception_handler
from src.common.authorization import get_user_details_from_sdk
from src.common.config import get_settings
from src.common.dependencies import get_current_user_details_for_audit, get_db
from src.common.features import ACCESS_LEVEL_ORDER, FeatureAccessLevel
from src.common.manager_dependencies import get_audit_manager, get_auth_manager, get_metadata_manager
from src.common.workspace_client import get_workspace_client
from src.controller.costs_manager import CostsManager
from src.controller.metadata_manager import MetadataManager, SHARED_ENTITY_ID, NotSharedAssetError, SharedScopeNotAllowedError
from src.models.costs import CostItem, CostItemCreate
from src.models.metadata import (
    METADATA_ENTITY_FEATURES, DocumentCreate, LinkCreate, MetadataAttachmentCreate, RichText, RichTextCreate,
)
from src.models.users import UserInfo
from src.routes import costs_routes, metadata_routes

RW = FeatureAccessLevel.READ_WRITE


class _FakeAuthManager:
    def __init__(self, permissions):
        self._permissions = permissions

    def get_user_effective_permissions(self, groups, team_role_override, user_email=None):
        return self._permissions

    def has_permission(self, permissions, feature, level):
        held = permissions.get(feature, FeatureAccessLevel.NONE)
        return ACCESS_LEVEL_ORDER[held] >= ACCESS_LEVEL_ORDER[level]


def _rich_text(entity_type="data_product"):
    now = datetime.utcnow()
    return RichText(
        id=uuid.uuid4(), entity_id="e1", entity_type=entity_type, title="t",
        content_markdown="c", created_at=now, updated_at=now,
    )


def _cost_item(entity_type="asset"):
    now = datetime.utcnow()
    return CostItem(
        id=uuid.uuid4(), entity_id="e1", entity_type=entity_type, cost_center="STORAGE",
        amount_cents=100, currency="USD", start_month="2026-10-01", created_at=now, updated_at=now,
    )


@pytest.fixture
def metadata_manager():
    return MagicMock()


@pytest.fixture
def costs_manager():
    return MagicMock()


@pytest.fixture
def make_client(metadata_manager, costs_manager):
    def _make(permissions):
        app = FastAPI()
        app.include_router(metadata_routes.router)
        app.include_router(costs_routes.router)
        app.state.teams_manager = None
        app.state.settings_manager = None
        user = UserInfo(email="u@example.com", username="u", user="U", ip="127.0.0.1", groups=["g"])

        async def _user():
            return user

        def _db():
            yield MagicMock()

        app.dependency_overrides[get_user_details_from_sdk] = _user
        app.dependency_overrides[get_current_user_details_for_audit] = _user
        app.dependency_overrides[get_auth_manager] = lambda: _FakeAuthManager(permissions)
        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_audit_manager] = lambda: MagicMock()
        app.dependency_overrides[get_metadata_manager] = lambda: metadata_manager
        app.dependency_overrides[costs_routes.get_costs_manager] = lambda: costs_manager
        app.dependency_overrides[get_settings] = lambda: MagicMock()
        app.dependency_overrides[get_workspace_client] = lambda: MagicMock()
        app.add_exception_handler(StarletteHTTPException, coded_http_exception_handler)
        return TestClient(app)
    return _make


def _note(entity_type="data_product"):
    return {"entity_id": "e1", "entity_type": entity_type, "title": "t", "content_markdown": "c"}


class TestEntityRoutes:
    def test_domain_write_access_does_not_allow_notes_on_products(self, make_client, metadata_manager):
        client = make_client({"data-domains": RW})

        resp = client.post("/api/entities/data_product/rich-texts?entity_id=e1", json=_note())

        assert resp.status_code == 403
        metadata_manager.create_rich_text.assert_not_called()

    def test_product_write_access_allows_notes_on_products(self, make_client, metadata_manager):
        metadata_manager.create_rich_text.return_value = _rich_text()
        client = make_client({"data-products": RW})

        resp = client.post("/api/entities/data_product/rich-texts?entity_id=e1", json=_note())

        assert resp.status_code == 201
        metadata_manager.create_rich_text.assert_called_once()

    @pytest.mark.parametrize("entity_type, feature", [
        ("data_product", "data-products"),
        ("data_contract", "data-contracts"),
        ("asset", "assets"),
        ("dataset", "assets"),
        ("concept", "semantic-models"),
        ("collection", "semantic-models"),
        ("compliance_policy", "compliance"),
    ])
    def test_reads_need_the_owning_feature(self, make_client, metadata_manager, entity_type, feature):
        metadata_manager.list_links.return_value = []

        denied = make_client({"data-domains": FeatureAccessLevel.ADMIN})
        assert denied.get(f"/api/entities/{entity_type}/links?entity_id=e1").status_code == 403

        allowed = make_client({feature: FeatureAccessLevel.READ_ONLY})
        assert allowed.get(f"/api/entities/{entity_type}/links?entity_id=e1").status_code == 200

    def test_unknown_entity_type_is_rejected(self, make_client):
        client = make_client({"data-domains": FeatureAccessLevel.ADMIN})

        resp = client.get("/api/entities/bogus/rich-texts?entity_id=e1")

        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "unsupported_entity_type"


class TestSharedScopeOnEntityRoutes:
    """Library records are created only on /metadata/shared; entity-scoped creates refuse the shared scope."""

    def test_product_writer_cannot_create_a_library_note(self, make_client, metadata_manager):
        client = make_client({"data-products": RW})

        resp = client.post("/api/entities/data_product/rich-texts?entity_id=e1", json={**_note(), "is_shared": True})

        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "shared_scope_not_allowed"
        metadata_manager.create_rich_text.assert_not_called()

    def test_shared_entity_id_is_refused_for_notes(self, make_client, metadata_manager):
        client = make_client({"data-products": RW})

        resp = client.post(
            f"/api/entities/data_product/rich-texts?entity_id={SHARED_ENTITY_ID}",
            json={**_note(), "entity_id": SHARED_ENTITY_ID},
        )

        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "shared_scope_not_allowed"
        metadata_manager.create_rich_text.assert_not_called()

    def test_product_writer_cannot_create_a_library_link(self, make_client, metadata_manager):
        client = make_client({"data-products": RW})
        link = {"entity_id": "e1", "entity_type": "data_product", "title": "t", "url": "https://example.com", "is_shared": True}

        resp = client.post("/api/entities/data_product/links?entity_id=e1", json=link)

        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "shared_scope_not_allowed"
        metadata_manager.create_link.assert_not_called()

    def test_shared_entity_id_is_refused_for_documents(self, make_client, metadata_manager):
        client = make_client({"data-products": RW})

        resp = client.post(
            f"/api/entities/data_product/documents?entity_id={SHARED_ENTITY_ID}",
            data={"title": "t"},
            files={"file": ("a.txt", b"x", "text/plain")},
        )

        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "shared_scope_not_allowed"
        metadata_manager.create_document_record.assert_not_called()

    def test_entity_scoped_note_on_a_real_entity_still_works(self, make_client, metadata_manager):
        metadata_manager.create_rich_text.return_value = _rich_text()
        client = make_client({"data-products": RW})

        resp = client.post("/api/entities/data_product/rich-texts?entity_id=e1", json={**_note(), "is_shared": False})

        assert resp.status_code == 201


class TestRecordRoutes:
    def test_update_checks_the_records_entity_feature(self, make_client, metadata_manager):
        record_id = str(uuid.uuid4())
        metadata_manager.get_record_scope.return_value = ("data_contract", False)
        client = make_client({"data-domains": RW})

        resp = client.put(f"/api/rich-texts/{record_id}", json={"title": "x"})

        assert resp.status_code == 403
        assert metadata_manager.get_record_scope.call_args.kwargs == {"kind": "rich_text", "id": record_id}
        metadata_manager.update_rich_text.assert_not_called()

    def test_delete_with_the_owning_feature_goes_through(self, make_client, metadata_manager):
        metadata_manager.get_record_scope.return_value = ("asset", False)
        metadata_manager.delete_link.return_value = True
        client = make_client({"assets": RW})

        assert client.delete(f"/api/links/{uuid.uuid4()}").status_code == 204
        metadata_manager.delete_link.assert_called_once()

    def test_missing_record_is_404(self, make_client, metadata_manager):
        metadata_manager.get_record_scope.return_value = None
        client = make_client({"data-domains": FeatureAccessLevel.ADMIN})

        resp = client.get(f"/api/documents/{uuid.uuid4()}")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Document not found"

    def test_shared_records_are_authorized_by_the_library_feature(self, make_client, metadata_manager):
        # A shared note created from a product page keeps entity_type data_product.
        metadata_manager.get_record_scope.return_value = ("data_product", True)
        metadata_manager.delete_rich_text.return_value = True

        assert make_client({"data-products": RW}).delete(f"/api/rich-texts/{uuid.uuid4()}").status_code == 403
        assert make_client({"data-domains": RW}).delete(f"/api/rich-texts/{uuid.uuid4()}").status_code == 204

    def test_a_non_uuid_id_is_404_without_a_lookup(self, make_client, metadata_manager):
        assert make_client({"data-domains": RW}).put("/api/links/not-a-uuid", json={"title": "x"}).status_code == 404
        metadata_manager.get_record_scope.assert_not_called()

    def test_merged_metadata_with_contracts_needs_contract_access(self, make_client, metadata_manager):
        metadata_manager.get_merged_metadata.return_value = {
            "entity_id": "e1", "entity_type": "data_product", "rich_texts": [], "links": [], "documents": [],
        }
        url = "/api/entities/data_product/metadata/merged?entity_id=e1&contract_ids=c1"

        assert make_client({"data-products": FeatureAccessLevel.READ_ONLY}).get(url).status_code == 403
        metadata_manager.get_merged_metadata.assert_not_called()

    def test_attaching_a_non_shared_asset_is_refused(self, make_client, metadata_manager):
        metadata_manager.get_record_scope.return_value = ("data_product", False)
        metadata_manager.attach_shared_asset.side_effect = NotSharedAssetError("Only shared library assets can be attached")
        client = make_client({"data-products": RW})

        resp = client.post(
            "/api/entities/data_product/attachments?entity_id=e1",
            json={"asset_type": "rich_text", "asset_id": str(uuid.uuid4())},
        )

        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "not_shared_asset"

    def test_merged_metadata_refuses_the_shared_id(self, make_client, metadata_manager):
        client = make_client({"data-products": FeatureAccessLevel.READ_ONLY})

        resp = client.get(f"/api/entities/data_product/metadata/merged?entity_id={SHARED_ENTITY_ID}")

        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "shared_scope_not_allowed"
        metadata_manager.get_merged_metadata.assert_not_called()

    def test_merged_metadata_refuses_the_shared_id_as_a_contract(self, make_client, metadata_manager):
        client = make_client({"data-products": FeatureAccessLevel.READ_ONLY, "data-contracts": FeatureAccessLevel.READ_ONLY})

        resp = client.get(
            f"/api/entities/data_product/metadata/merged?entity_id=e1&contract_ids=c1,{SHARED_ENTITY_ID}",
        )

        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "shared_scope_not_allowed"
        metadata_manager.get_merged_metadata.assert_not_called()

    def test_attaching_to_the_shared_id_is_refused(self, make_client, metadata_manager):
        client = make_client({"data-products": RW})

        resp = client.post(
            f"/api/entities/data_product/attachments?entity_id={SHARED_ENTITY_ID}",
            json={"asset_type": "rich_text", "asset_id": str(uuid.uuid4())},
        )

        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "shared_scope_not_allowed"
        metadata_manager.attach_shared_asset.assert_not_called()

    def test_attaching_a_library_note_needs_library_read_access(self, make_client, metadata_manager):
        # Attached library notes are readable on the entity, so the attacher needs library read access.
        metadata_manager.get_record_scope.return_value = ("data_product", True)
        url = "/api/entities/compliance_policy/attachments?entity_id=e1"
        body = {"asset_type": "rich_text", "asset_id": str(uuid.uuid4())}

        assert make_client({"compliance": RW}).post(url, json=body).status_code == 403
        metadata_manager.attach_shared_asset.assert_not_called()

        # Past the gate, the manager's answer is the response (a stand-in refusal keeps the mock serialisable).
        metadata_manager.attach_shared_asset.side_effect = NotSharedAssetError("Only shared library assets can be attached")
        resp = make_client({"compliance": RW, "data-domains": FeatureAccessLevel.READ_ONLY}).post(url, json=body)
        assert resp.status_code == 400
        metadata_manager.attach_shared_asset.assert_called_once()

    def test_attaching_a_malformed_asset_id_is_a_coded_400(self, make_client, metadata_manager):
        client = make_client({"data-products": RW})

        resp = client.post(
            "/api/entities/data_product/attachments?entity_id=e1",
            json={"asset_type": "rich_text", "asset_id": "not-a-uuid"},
        )

        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "not_shared_asset"
        metadata_manager.attach_shared_asset.assert_not_called()

    def test_shared_library_keeps_the_domain_feature(self, make_client, metadata_manager):
        metadata_manager.list_shared_assets.return_value = SimpleNamespace(
            rich_texts=[], links=[], documents=[], total_count=0,
        )
        assert make_client({"data-products": RW}).get("/api/metadata/shared").status_code == 403


class TestCostRoutes:
    def test_domain_write_access_does_not_allow_costs_on_products(self, make_client, costs_manager):
        client = make_client({"data-domains": RW})
        payload = {
            "entity_id": "e1", "entity_type": "data_product", "cost_center": "STORAGE",
            "amount_cents": 100, "currency": "USD", "start_month": "2026-10-01",
        }

        resp = client.post("/api/entities/data_product/e1/cost-items", json=payload)

        assert resp.status_code == 403
        costs_manager.create.assert_not_called()

    def test_cost_item_update_checks_its_entity_feature(self, make_client, costs_manager):
        costs_manager.get_entity_type.return_value = "asset"
        costs_manager.update.return_value = _cost_item()

        assert make_client({"data-domains": RW}).put(
            f"/api/cost-items/{uuid.uuid4()}", json={"title": "x"},
        ).status_code == 403
        assert make_client({"assets": RW}).put(
            f"/api/cost-items/{uuid.uuid4()}", json={"title": "x"},
        ).status_code == 200

    def test_non_uuid_cost_item_is_404(self, make_client, costs_manager):
        assert make_client({"assets": RW}).put("/api/cost-items/nope", json={"title": "x"}).status_code == 404
        costs_manager.get_entity_type.assert_not_called()

    def test_missing_cost_item_is_404(self, make_client, costs_manager):
        costs_manager.get_entity_type.return_value = None

        assert make_client({"assets": RW}).delete(f"/api/cost-items/{uuid.uuid4()}").status_code == 404


def test_every_metadata_kind_maps_to_a_known_feature():
    from src.common.features import APP_FEATURES

    assert set(METADATA_ENTITY_FEATURES.values()) <= set(APP_FEATURES)


class TestRecordLookups:
    """The id-addressed routes authorize by these lookups, so check them on a real session."""

    def test_metadata_records_report_their_entity_kind(self, db_session):
        manager = MetadataManager()
        note = manager.create_rich_text(
            db_session, data=RichTextCreate(entity_id="p1", entity_type="data_product", title="t", content_markdown="c"),
            user_email="u@example.com",
        )
        link = manager.create_link(
            db_session, data=LinkCreate(entity_id="a1", entity_type="asset", title="t", url="https://example.com"),
            user_email="u@example.com",
        )
        doc = manager.create_document_record(
            db_session, data=DocumentCreate(entity_id="c1", entity_type="concept", title="t"),
            filename="f.txt", content_type="text/plain", size_bytes=1, storage_path="/x/f.txt",
            user_email="u@example.com",
        )

        assert manager.get_record_scope(db_session, kind="rich_text", id=note.id) == ("data_product", False)
        assert manager.get_record_scope(db_session, kind="link", id=link.id) == ("asset", False)
        assert manager.get_record_scope(db_session, kind="document", id=doc.id) == ("concept", False)
        # A record of another kind with the same id space is not found under the wrong kind.
        assert manager.get_record_scope(db_session, kind="link", id=note.id) is None
        assert manager.get_record_scope(db_session, kind="rich_text", id=uuid.uuid4()) is None

    def test_shared_records_and_attachments(self, db_session):
        manager = MetadataManager()
        shared = manager.create_shared_rich_text(
            db_session, data=RichTextCreate(entity_id="p1", entity_type="data_product", title="t", content_markdown="c"),
            user_email="u@example.com",
        )
        private = manager.create_rich_text(
            db_session, data=RichTextCreate(entity_id="x1", entity_type="compliance_policy", title="t", content_markdown="c"),
            user_email="u@example.com",
        )

        assert manager.get_record_scope(db_session, kind="rich_text", id=shared.id) == ("data_product", True)
        attached = manager.attach_shared_asset(
            db_session, entity_type="data_product", entity_id="p2",
            data=MetadataAttachmentCreate(asset_type="rich_text", asset_id=str(shared.id)), user_email="u@example.com",
        )
        assert attached.asset_id == str(shared.id)
        with pytest.raises(ValueError):
            manager.attach_shared_asset(
                db_session, entity_type="data_product", entity_id="p2",
                data=MetadataAttachmentCreate(asset_type="rich_text", asset_id=str(private.id)), user_email="u@example.com",
            )

    def test_manager_refuses_shared_scope_on_entity_creates(self, db_session):
        manager = MetadataManager()
        with pytest.raises(SharedScopeNotAllowedError):
            manager.create_rich_text(
                db_session,
                data=RichTextCreate(entity_id="p1", entity_type="data_product", title="t", content_markdown="c", is_shared=True),
                user_email="u@example.com",
            )
        with pytest.raises(SharedScopeNotAllowedError):
            manager.create_link(
                db_session,
                data=LinkCreate(entity_id=SHARED_ENTITY_ID, entity_type="data_product", title="t", url="https://example.com"),
                user_email="u@example.com",
            )

    def test_shared_records_are_not_listed_under_an_entity_kind(self, db_session):
        manager = MetadataManager()
        manager.create_shared_rich_text(
            db_session,
            data=RichTextCreate(entity_id="p1", entity_type="data_contract", title="t", content_markdown="c", inheritable=True),
            user_email="u@example.com",
        )

        assert manager.list_rich_texts(db_session, entity_type="data_contract", entity_id=SHARED_ENTITY_ID) == []
        merged = manager.get_merged_metadata(
            db_session, entity_type="data_product", entity_id=SHARED_ENTITY_ID, contract_ids=["c1", SHARED_ENTITY_ID],
        )
        assert merged.rich_texts == []
        merged_contract = manager.get_merged_metadata(
            db_session, entity_type="data_product", entity_id="p9", contract_ids=[SHARED_ENTITY_ID],
        )
        assert merged_contract.rich_texts == []

    def test_cost_items_report_their_entity_kind(self, db_session):
        manager = CostsManager()
        item = manager.create(
            db_session,
            data=CostItemCreate(entity_id="a1", entity_type="asset", cost_center="STORAGE",
                                amount_cents=100, currency="USD", start_month="2026-10-01"),
            user_email="u@example.com",
        )

        assert manager.get_entity_type(db_session, id=item.id) == "asset"
        assert manager.get_entity_type(db_session, id=uuid.uuid4()) is None


@pytest.mark.parametrize("entity_id, expected_safe", [
    ("e1b2", True),
    ("http://ontos.app/concept/Customer", False),
    ("urn:glossary:child", True),
])
def test_document_storage_segment(entity_id, expected_safe):
    segment = metadata_routes._storage_segment(entity_id)

    assert "/" not in segment and ".." not in segment
    assert (segment == entity_id) is expected_safe
    assert metadata_routes._storage_segment(entity_id) == segment  # stable for later uploads
