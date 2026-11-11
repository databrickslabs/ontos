"""Link candidates for the Add Relationship dialog: every target type a relationship can point to.

Regression (#956, #957, #959): the dialog only searched assets, so "Belongs to Domain"
and "Has Concepts" offered nothing. ``GET /api/suggestions/link-candidates`` now serves
domains, products, contracts, teams, projects and ontology concepts too, each behind
the read permission of the feature that owns it.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.common.authorization import get_user_details_from_sdk
from src.common.dependencies import get_db
from src.common.features import ACCESS_LEVEL_ORDER, FeatureAccessLevel
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.data_domains import DataDomain
from src.db_models.teams import TeamDb
from src.models.users import UserInfo
from src.routes import suggestion_routes

RO = FeatureAccessLevel.READ_ONLY
ALL_READ = {
    feature: RO for feature in (
        "assets", "data-domains", "data-products", "data-contracts",
        "semantic-models", "teams", "projects",
    )
}


class _FakeAuthManager:
    def __init__(self, permissions):
        self._permissions = permissions

    def get_user_effective_permissions(self, groups, team_role_override, user_email=None):
        return self._permissions

    def has_permission(self, permissions, feature, level):
        held = permissions.get(feature, FeatureAccessLevel.NONE)
        return ACCESS_LEVEL_ORDER[held] >= ACCESS_LEVEL_ORDER[level]


class _FakeSemanticModels:
    """The two calls link-candidates makes for OntologyConcept."""

    def __init__(self, concepts):
        self._concepts = concepts
        self.calls = []

    def search_concepts_by_type(self, text_filter, concept_types, limit=50, source_context=None):
        self.calls.append((text_filter, tuple(concept_types), limit))
        needle = (text_filter or "").lower()
        rows = [c for c in self._concepts if needle in c["label"].lower() or needle in c["value"].lower()]
        return rows[:limit]

    def get_collections(self):
        return [
            {"iri": "urn:glossary:retail", "label": "Retail Glossary", "source_key": "retail"},
            {"iri": "urn:taxonomy:ontos-ontology", "label": "Ontos Ontology", "source_key": "ontos-ontology"},
        ]


CONCEPTS = [
    {"value": "urn:glossary:retail/customer", "label": "Customer", "type": "concept", "source_context": "retail"},
    {"value": "urn:glossary:retail/customer-address", "label": "Customer Address", "type": "concept", "source_context": "retail"},
    # The app's own metamodel classes are not business concepts to link to.
    {"value": "http://ontos.app/ontology#Customer", "label": "Customer", "type": "class", "source_context": "ontos-ontology"},
]


@pytest.fixture
def make_client(db_session):
    def _make(permissions=ALL_READ, concepts=CONCEPTS):
        app = FastAPI()
        app.include_router(suggestion_routes.router)
        app.state.authorization_manager = _FakeAuthManager(permissions)
        app.state.settings_manager = None
        app.state.teams_manager = None
        app.state.semantic_models_manager = _FakeSemanticModels(concepts)
        user = UserInfo(email="u@example.com", username="u", user="U", ip="127.0.0.1", groups=["g"])

        async def _user():
            return user

        def _db():
            yield db_session

        app.dependency_overrides[get_user_details_from_sdk] = _user
        app.dependency_overrides[get_db] = _db
        return TestClient(app), app
    return _make


def _domains(db_session, *names):
    for name in names:
        db_session.add(DataDomain(name=name, created_by="seed"))
    db_session.commit()


def _assets(db_session, type_name, *names):
    asset_type = AssetTypeDb(name=type_name, category="data")
    db_session.add(asset_type)
    db_session.flush()
    for name in names:
        db_session.add(AssetDb(name=name, asset_type_id=asset_type.id, status="active"))
    db_session.commit()


def _candidates(client, **params):
    resp = client.get("/api/suggestions/link-candidates", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestDomains:
    def test_browse_lists_domains_without_a_query(self, make_client, db_session):
        _domains(db_session, "Sales", "Finance", "Marketing")
        client, _ = make_client()

        data = _candidates(client, target_type="DataDomain", limit=50)

        assert [c["name"] for c in data["candidates"]] == ["Finance", "Marketing", "Sales"]
        assert {c["entity_type"] for c in data["candidates"]} == {"DataDomain"}
        assert data["total"] == 3

    def test_search_filters_domains_by_name(self, make_client, db_session):
        _domains(db_session, "Sales", "Finance", "Sales Ops")
        client, _ = make_client()

        names = [c["name"] for c in _candidates(client, target_type="DataDomain", query="sales")["candidates"]]

        assert set(names) == {"Sales", "Sales Ops"}

    def test_domain_candidates_need_domain_read_access(self, make_client, db_session):
        _domains(db_session, "Sales")
        client, _ = make_client(permissions={"assets": RO})

        assert client.get("/api/suggestions/link-candidates", params={"target_type": "DataDomain"}).status_code == 403


class TestConcepts:
    def test_concepts_carry_label_collection_and_iri(self, make_client):
        client, _ = make_client()

        data = _candidates(client, target_type="OntologyConcept", query="customer")

        assert [(c["id"], c["name"], c["context"]) for c in data["candidates"]] == [
            ("urn:glossary:retail/customer", "Customer", "Retail Glossary"),
            ("urn:glossary:retail/customer-address", "Customer Address", "Retail Glossary"),
        ]
        assert {c["entity_type"] for c in data["candidates"]} == {"OntologyConcept"}

    def test_browse_lists_concepts_and_skips_property_types(self, make_client):
        client, app = make_client()

        data = _candidates(client, target_type="OntologyConcept", limit=50)

        assert len(data["candidates"]) == 2
        _, types, _ = app.state.semantic_models_manager.calls[-1]
        assert "property" not in types

    def test_total_counts_every_match_not_the_page(self, make_client):
        client, _ = make_client()

        data = _candidates(client, target_type="OntologyConcept", limit=1)

        assert (len(data["candidates"]), data["total"]) == (1, 2)

    def test_concept_candidates_need_concept_read_access(self, make_client):
        client, _ = make_client(permissions={"assets": RO})

        assert client.get(
            "/api/suggestions/link-candidates", params={"target_type": "OntologyConcept"},
        ).status_code == 403


class TestAssets:
    def test_asset_types_match_by_label_or_local_name(self, make_client, db_session):
        _assets(db_session, "Logical Attribute", "customer_id", "order_id")
        client, _ = make_client()

        by_local = _candidates(client, target_type="LogicalAttribute")
        by_label = _candidates(client, target_type="Logical Attribute")

        assert sorted(c["name"] for c in by_local["candidates"]) == ["customer_id", "order_id"]
        assert by_local["candidates"] == by_label["candidates"]

    def test_generic_asset_target_lists_assets_of_every_type(self, make_client, db_session):
        _assets(db_session, "Table", "orders")
        _assets(db_session, "View", "orders_v")
        client, _ = make_client()

        names = {c["name"] for c in _candidates(client, target_type="Asset")["candidates"]}

        assert names == {"orders", "orders_v"}

    def test_asset_candidates_need_asset_read_access(self, make_client, db_session):
        _assets(db_session, "Table", "orders")
        client, _ = make_client(permissions={"data-domains": RO})

        assert client.get("/api/suggestions/link-candidates", params={"target_type": "Table"}).status_code == 403


class TestOtherTypes:
    def test_teams_are_candidates(self, make_client, db_session):
        db_session.add(TeamDb(name="Data Platform", created_by="t", updated_by="t", extra_metadata="{}"))
        db_session.commit()
        client, _ = make_client()

        assert [c["name"] for c in _candidates(client, target_type="Team")["candidates"]] == ["Data Platform"]

    def test_unknown_target_type_returns_no_candidates(self, make_client):
        client, _ = make_client()

        assert _candidates(client, target_type="Ownership") == {"candidates": [], "total": 0}

    def test_errors_do_not_leak_exception_text(self, make_client, monkeypatch):
        client, app = make_client()

        def boom(*args, **kwargs):
            raise RuntimeError("secret connection string")

        monkeypatch.setattr(app.state.semantic_models_manager, "search_concepts_by_type", boom)
        resp = client.get("/api/suggestions/link-candidates", params={"target_type": "OntologyConcept"})

        assert resp.status_code == 500
        assert "secret" not in resp.text
