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

from src.common.authorization import get_user_details_from_sdk
from src.common.dependencies import get_current_user_details_for_audit, get_db
from src.common.features import ACCESS_LEVEL_ORDER, FeatureAccessLevel
from src.common.manager_dependencies import get_audit_manager, get_auth_manager, get_metadata_manager
from src.controller.costs_manager import CostsManager
from src.controller.metadata_manager import MetadataManager
from src.models.costs import CostItem, CostItemCreate
from src.models.metadata import METADATA_ENTITY_FEATURES, DocumentCreate, LinkCreate, RichText, RichTextCreate
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
        ("team", "teams"),
        ("project", "projects"),
    ])
    def test_reads_need_the_owning_feature(self, make_client, metadata_manager, entity_type, feature):
        metadata_manager.list_links.return_value = []

        denied = make_client({"data-domains": FeatureAccessLevel.ADMIN})
        assert denied.get(f"/api/entities/{entity_type}/links?entity_id=e1").status_code == 403

        allowed = make_client({feature: FeatureAccessLevel.READ_ONLY})
        assert allowed.get(f"/api/entities/{entity_type}/links?entity_id=e1").status_code == 200

    def test_unknown_entity_type_is_rejected(self, make_client):
        client = make_client({"data-domains": FeatureAccessLevel.ADMIN})

        assert client.get("/api/entities/bogus/rich-texts?entity_id=e1").status_code == 400


class TestRecordRoutes:
    def test_update_checks_the_records_entity_feature(self, make_client, metadata_manager):
        record_id = str(uuid.uuid4())
        metadata_manager.get_record_entity_type.return_value = "data_contract"
        client = make_client({"data-domains": RW})

        resp = client.put(f"/api/rich-texts/{record_id}", json={"title": "x"})

        assert resp.status_code == 403
        metadata_manager.get_record_entity_type.assert_called_once_with(
            metadata_manager.get_record_entity_type.call_args.args[0], kind="rich_text", id=record_id,
        )
        metadata_manager.update_rich_text.assert_not_called()

    def test_delete_with_the_owning_feature_goes_through(self, make_client, metadata_manager):
        metadata_manager.get_record_entity_type.return_value = "asset"
        metadata_manager.delete_link.return_value = True
        client = make_client({"assets": RW})

        assert client.delete(f"/api/links/{uuid.uuid4()}").status_code == 204
        metadata_manager.delete_link.assert_called_once()

    def test_missing_record_is_404(self, make_client, metadata_manager):
        metadata_manager.get_record_entity_type.return_value = None
        client = make_client({"data-domains": FeatureAccessLevel.ADMIN})

        resp = client.get(f"/api/documents/{uuid.uuid4()}")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Document not found"

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

        assert manager.get_record_entity_type(db_session, kind="rich_text", id=note.id) == "data_product"
        assert manager.get_record_entity_type(db_session, kind="link", id=link.id) == "asset"
        assert manager.get_record_entity_type(db_session, kind="document", id=doc.id) == "concept"
        # A record of another kind with the same id space is not found under the wrong kind.
        assert manager.get_record_entity_type(db_session, kind="link", id=note.id) is None
        assert manager.get_record_entity_type(db_session, kind="rich_text", id=uuid.uuid4()) is None

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
