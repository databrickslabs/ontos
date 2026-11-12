"""ACCEPTANCE gate for two data-correctness fixes in SemanticModelsManager.

BUG D3 — vocabulary/meta IRIs leak into a concept's parent list.
    A malformed `skos:broader owl:Class` triple (bad data) surfaced owl:Class as
    a "parent" and the UI rendered a dead link. RDF/RDFS/OWL/SKOS vocabulary IRIs
    (owl:Class, owl:Thing, rdfs:*, skos:*) are NEVER valid parents. All parent
    read paths must filter them while still returning REAL concept parents.

BUG D9 — a class set to "under_review" showed a blank/active status.
    ``get_concept_version_info`` preferred the concept_version ROW's lifecycle
    status ("active"/"superseded") and shadowed the governance status the user
    set in the graph (ONTOS.status = "under_review"). The returned ``status``
    must reflect the GOVERNANCE status from the graph, falling back to the
    version-row status only when the graph carries none.
"""
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rdflib import URIRef, Literal
from rdflib.namespace import SKOS, OWL
from sqlalchemy.orm import Session

from src.app import app
from src.controller.semantic_models_manager import SemanticModelsManager
from src.common.app_state import set_app_state_manager


@pytest.fixture
def semantic_models_manager(db_session: Session, tmp_path: Path):
    data_dir = tmp_path / "sm_data"
    (data_dir / "cache").mkdir(parents=True, exist_ok=True)
    (data_dir / "taxonomies").mkdir(parents=True, exist_ok=True)
    manager = SemanticModelsManager(db=db_session, data_dir=data_dir)
    app.state.semantic_models_manager = manager
    set_app_state_manager("semantic_models_manager", manager)

    class _Noop:
        def sync_asset_types(self, *a, **k):
            return {"created": 0, "updated": 0}

        def log_action(self, *a, **k):
            return None

        def log_event(self, *a, **k):
            return None

    app.state.ontology_schema_manager = _Noop()
    app.state.audit_manager = _Noop()
    yield manager
    for attr in ("semantic_models_manager", "ontology_schema_manager", "audit_manager"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)


@pytest.fixture
def make_collection(client: TestClient, semantic_models_manager):
    def _make(prefix="ParentFilter"):
        r = client.post("/api/knowledge/collections", json={
            "label": f"{prefix} {uuid.uuid4().hex[:8]}", "collection_type": "glossary",
            "scope_level": "enterprise", "description": "parent-filter/status-source test",
        })
        assert r.status_code == 200, r.text
        return r.json()

    return _make


def _make_concept(client, coll_iri, label, definition="def"):
    r = client.post("/api/knowledge/concepts", json={
        "collection_iri": coll_iri, "label": label, "definition": definition,
    })
    assert r.status_code == 200, r.text
    b = r.json()
    return b.get("iri") or (b.get("concept") or {}).get("iri")


_W3 = "http://www.w3.org/"


# --------------------------------------------------------------------------- #
# BUG D3
# --------------------------------------------------------------------------- #
def test_get_concept_parent_list_excludes_vocab_iris_keeps_real_parent(
    client, make_collection, semantic_models_manager, db_session
):
    coll = make_collection()
    child_iri = _make_concept(client, coll["iri"], "Customer")
    parent_iri = _make_concept(client, coll["iri"], "Party")

    # Attach a bad `skos:broader -> owl:Class` triple (vocab IRI = never a
    # parent) AND a good `skos:broader -> Party` triple (a real concept) to the
    # collection context that get_concept reads from.
    coll_ctx = semantic_models_manager._graph.get_context(URIRef(coll["iri"]))
    child_uri = URIRef(child_iri)
    coll_ctx.add((child_uri, SKOS.broader, OWL.Class))
    coll_ctx.add((child_uri, SKOS.broader, URIRef(parent_iri)))

    concept = semantic_models_manager.get_concept(child_iri)
    assert concept is not None
    parents = concept["parent_concepts"]

    # No RDF/RDFS/OWL/SKOS vocabulary IRI (owl:Class, owl:Thing, ...) leaks in.
    vocab = [p for p in parents if str(p).startswith(_W3)]
    assert not vocab, f"vocabulary IRIs leaked into parent_concepts: {vocab}"

    # The REAL parent is still present.
    assert parent_iri in parents, f"real parent {parent_iri} missing from {parents}"


def test_list_and_details_parent_lists_exclude_vocab_iris(
    client, make_collection, semantic_models_manager, db_session
):
    """_compute_all_concepts (list) and get_concept_details must filter too."""
    coll = make_collection()
    child_iri = _make_concept(client, coll["iri"], "Account")
    parent_iri = _make_concept(client, coll["iri"], "Asset")

    coll_ctx = semantic_models_manager._graph.get_context(URIRef(coll["iri"]))
    child_uri = URIRef(child_iri)
    coll_ctx.add((child_uri, SKOS.broader, OWL.Class))
    coll_ctx.add((child_uri, SKOS.broader, OWL.Thing))
    coll_ctx.add((child_uri, SKOS.broader, URIRef(parent_iri)))

    # get_concept_details path
    details = semantic_models_manager.get_concept_details(child_iri)
    assert details is not None
    d_parents = list(details.parent_concepts or [])
    assert not [p for p in d_parents if str(p).startswith(_W3)], d_parents
    assert parent_iri in d_parents

    # _compute_all_concepts (Explore list) path
    all_concepts = semantic_models_manager._compute_all_concepts()
    match = next((c for c in all_concepts if c.iri == child_iri), None)
    assert match is not None, "child concept missing from list"
    l_parents = list(match.parent_concepts or [])
    assert not [p for p in l_parents if str(p).startswith(_W3)], l_parents
    assert parent_iri in l_parents


# --------------------------------------------------------------------------- #
# BUG D9
# --------------------------------------------------------------------------- #
def test_version_info_status_reflects_graph_governance_status(
    client, make_collection, semantic_models_manager, db_session
):
    coll = make_collection()
    iri = _make_concept(client, coll["iri"], "Product")

    # create_concept minted a v1 concept_version row with lifecycle status
    # "active". Walk the GRAPH governance status to "under_review".
    semantic_models_manager.update_concept_status(iri, "under_review", updated_by="tester")

    # Sanity: the concept read (graph ONTOS.status) already returns under_review.
    assert semantic_models_manager.get_concept(iri)["status"] == "under_review"

    # A version row with lifecycle status "active" must NOT shadow the
    # governance status. version-info must report the graph status.
    info = semantic_models_manager.get_concept_version_info(iri)
    assert info is not None
    assert info["status"] == "under_review", (
        f"version-info status must be the governance status 'under_review', "
        f"not the version-row lifecycle status: {info}"
    )
