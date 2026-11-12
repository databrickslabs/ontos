"""Link candidates for the Add Relationship dialog: every target type a relationship can point to.

Regression (#956, #957, #959): the dialog only searched assets, so "Belongs to Domain"
and "Has Concepts" offered nothing. ``GET /api/suggestions/link-candidates`` now serves
domains, products, contracts, teams, projects and ontology concepts too, each behind
the read permission of the feature that owns it.
"""

import pytest
from types import SimpleNamespace

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

    def _scheme_labels_by_source_key(self):
        return {"retail": "Retail Glossary", "ontos-ontology": "Ontos Ontology"}


CONCEPTS = [
    {"value": "urn:glossary:retail/customer", "label": "Customer", "type": "concept", "source_context": "retail"},
    {"value": "urn:glossary:retail/customer-address", "label": "Customer Address", "type": "concept", "source_context": "retail"},
    # The app's own metamodel classes are not business concepts to link to.
    {"value": "http://ontos.app/ontology#Customer", "label": "Customer", "type": "class", "source_context": "ontos-ontology"},
]


@pytest.fixture
def make_client(db_session):
    def _make(permissions=ALL_READ, concepts=CONCEPTS, email="u@example.com", groups=("g",)):
        from pathlib import Path
        from unittest.mock import MagicMock

        from databricks.sdk import WorkspaceClient

        from src.controller.data_contracts_manager import DataContractsManager
        from src.controller.data_products_manager import DataProductsManager

        app = FastAPI()
        app.include_router(suggestion_routes.router)
        app.state.authorization_manager = _FakeAuthManager(permissions)
        app.state.settings_manager = None
        app.state.teams_manager = None
        app.state.semantic_models_manager = _FakeSemanticModels(concepts)
        app.state.data_products_manager = DataProductsManager(
            db=db_session, ws_client=MagicMock(spec=WorkspaceClient))
        app.state.data_contracts_manager = DataContractsManager(data_dir=Path("/tmp"))
        user = UserInfo(email=email, username="u", user="U", ip="127.0.0.1", groups=list(groups))

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

    def test_the_best_match_survives_the_page_cut(self, make_client):
        concepts = [
            {"value": f"urn:glossary:retail/{n}", "label": label, "type": "concept", "source_context": "retail"}
            for n, label in (("a", "Active Customer"), ("b", "B2B Customer"), ("c", "Customer"))
        ]
        client, _ = make_client(concepts=concepts)

        data = _candidates(client, target_type="OntologyConcept", query="customer", limit=1)

        assert [c["name"] for c in data["candidates"]] == ["Customer"]

    @pytest.mark.parametrize("spelling", ["Data Domain", "http://ontos.app/ontology#DataDomain"])
    def test_other_spellings_of_a_target_type(self, make_client, db_session, spelling):
        _domains(db_session, "Sales")
        client, _ = make_client(permissions={"data-domains": RO})

        assert [c["name"] for c in _candidates(client, target_type=spelling)["candidates"]] == ["Sales"]

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


PRODUCT_READ = {"data-products": RO}
CONTRACT_READ = {"data-contracts": RO}


def _product(db_session, name, status, **fields):
    import uuid as _uuid
    from src.db_models.data_products import DataProductDb

    pid = str(_uuid.uuid4())
    db_session.add(DataProductDb(id=pid, name=name, version="1.0.0", status=status,
                                 version_family_id=pid, **fields))
    db_session.commit()
    return pid


def _contract(db_session, name, status, **fields):
    import uuid as _uuid
    from src.db_models.data_contracts import DataContractDb

    cid = str(_uuid.uuid4())
    db_session.add(DataContractDb(id=cid, name=name, version="1.0.0", status=status,
                                  version_family_id=cid, created_by="seed", **fields))
    db_session.commit()
    return cid


def _team_with_member(db_session, member_email):
    import uuid as _uuid
    from src.db_models.teams import TeamMemberDb

    team = TeamDb(id=str(_uuid.uuid4()), name=f"team-{_uuid.uuid4().hex[:6]}",
                  created_by="t", updated_by="t", extra_metadata="{}")
    db_session.add(team)
    db_session.flush()
    db_session.add(TeamMemberDb(team_id=team.id, member_type="user",
                                member_identifier=member_email, added_by="seed"))
    db_session.commit()
    return team.id


def _names(client, target_type):
    return {c["name"] for c in _candidates(client, target_type=target_type, limit=100)["candidates"]}


class TestVisibility:
    """Candidates follow the list views' read rules, not just the feature level."""

    def test_product_readers_see_published_products_and_their_own_drafts(self, make_client, db_session):
        team_id = _team_with_member(db_session, "member@example.com")
        _product(db_session, "Published", "active")
        _product(db_session, "Someone's draft", "draft", draft_owner_id="other@example.com")
        _product(db_session, "Proposed", "proposed", draft_owner_id="other@example.com")
        _product(db_session, "My draft", "draft", draft_owner_id="me@example.com")
        _product(db_session, "Team draft", "draft", owner_team_id=team_id)

        reader, _ = make_client(permissions=PRODUCT_READ, email="me@example.com")
        member, _ = make_client(permissions=PRODUCT_READ, email="member@example.com")
        admin, _ = make_client(permissions={"data-products": FeatureAccessLevel.ADMIN}, email="admin@example.com")

        assert _names(reader, "DataProduct") == {"Published", "My draft"}
        assert _names(member, "DataProduct") == {"Published", "Team draft"}
        assert _names(admin, "DataProduct") == {
            "Published", "Someone's draft", "Proposed", "My draft", "Team draft"}

    def test_product_totals_count_only_visible_products(self, make_client, db_session):
        _product(db_session, "Published", "active")
        _product(db_session, "Hidden draft", "draft", draft_owner_id="other@example.com")
        reader, _ = make_client(permissions=PRODUCT_READ, email="me@example.com")

        data = _candidates(reader, target_type="DataProduct", query="d")

        assert ([c["name"] for c in data["candidates"]], data["total"]) == (["Published"], 1)

    def test_contract_readers_see_published_contracts_and_their_own_drafts(self, make_client, db_session):
        team_id = _team_with_member(db_session, "member@example.com")
        _contract(db_session, "Active contract", "active")
        _contract(db_session, "Someone's draft", "draft", draft_owner_id="other@example.com")
        _contract(db_session, "Proposed contract", "proposed", draft_owner_id="other@example.com")
        _contract(db_session, "My draft", "draft", draft_owner_id="me@example.com")
        _contract(db_session, "Team proposal", "proposed", owner_team_id=team_id)

        reader, _ = make_client(permissions=CONTRACT_READ, email="me@example.com")
        member, _ = make_client(permissions=CONTRACT_READ, email="member@example.com")
        admin, _ = make_client(permissions={"data-contracts": FeatureAccessLevel.ADMIN}, email="admin@example.com")

        assert _names(reader, "DataContract") == {"Active contract", "My draft"}
        assert _names(member, "DataContract") == {"Active contract", "Team proposal"}
        assert _names(admin, "DataContract") == {
            "Active contract", "Someone's draft", "Proposed contract", "My draft", "Team proposal"}

    def test_projects_come_from_the_callers_project_list(self, make_client, monkeypatch):
        from src.controller.projects_manager import projects_manager

        calls = []

        def fake_get_all_projects(db, *, user_identifier, user_groups, is_admin, **_):
            calls.append((user_identifier, list(user_groups), is_admin))
            return [SimpleNamespace(id="p1", name="Mine", description=None, status=None)]

        monkeypatch.setattr(projects_manager, "get_all_projects", fake_get_all_projects)
        client, _ = make_client(permissions={"projects": RO}, email="me@example.com", groups=("analysts",))

        assert _names(client, "Project") == {"Mine"}
        assert calls == [("me@example.com", ["analysts"], False)]

    def test_app_entity_graph_nodes_are_not_concept_candidates(self, make_client):
        concepts = CONCEPTS + [{
            "value": "urn:ontos:data_product:p-draft", "label": "Draft product node",
            "type": "individual", "source_context": "retail",
        }]
        client, _ = make_client(concepts=concepts)

        assert "Draft product node" not in _names(client, "OntologyConcept")
