"""Concepts saved before new entries were stamped Draft carry no ``ontos:status``.

In a governed (editable, collection-backed) scheme they already behave as
drafts on submit/edit/delete, so the read payload reports ``"draft"`` for
concept/class/individual/term entries. Properties and read-only sources
(bundled/system ontologies, file taxonomies) keep ``None``. Display default
only: no triple is written.
"""
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rdflib import Literal, URIRef
from rdflib.namespace import OWL, RDF, SKOS
from sqlalchemy.orm import Session

from src.app import app
from src.common.app_state import set_app_state_manager
from src.controller.semantic_models_manager import ONTOS, SemanticModelsManager


@pytest.fixture
def smm(db_session: Session, tmp_path: Path):
    data_dir = tmp_path / "sm_data"
    (data_dir / "cache").mkdir(parents=True, exist_ok=True)
    (data_dir / "taxonomies").mkdir(parents=True, exist_ok=True)
    m = SemanticModelsManager(db=db_session, data_dir=data_dir)
    app.state.semantic_models_manager = m
    set_app_state_manager("semantic_models_manager", m)

    class _Noop:
        def sync_asset_types(self, *a, **k):
            return {"created": 0, "updated": 0}

        def log_action(self, *a, **k):
            return None

        def log_event(self, *a, **k):
            return None

    app.state.ontology_schema_manager = _Noop()
    app.state.audit_manager = _Noop()
    yield m
    for attr in ("semantic_models_manager", "ontology_schema_manager", "audit_manager"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)


def _strip_status(smm, coll_iri, concept_iri):
    """Simulate a concept saved before the Draft stamp: drop ontos:status."""
    ctx = smm._graph.get_context(URIRef(coll_iri))
    ctx.remove((URIRef(concept_iri), ONTOS.status, None))
    assert smm._get_literal(ctx, URIRef(concept_iri), ONTOS.status) is None


def _grouped_status(smm, bucket_key, iri):
    smm._invalidate_cache()
    for c in smm.get_grouped_concepts().get(bucket_key, []):
        if c.iri == iri:
            return c.status
    raise AssertionError(f"{iri} not in grouped bucket {bucket_key!r}")


def test_missing_status_reported_as_draft_in_editable_scheme(client: TestClient, smm):
    r = client.post("/api/knowledge/collections", json={
        "label": f"Legacy {uuid.uuid4().hex[:6]}", "collection_type": "glossary",
        "scope_level": "enterprise", "description": "status default",
    })
    assert r.status_code == 200, r.text
    coll = r.json()["iri"]
    bucket = coll.split(":")[-1]

    concept = smm.create_concept(coll, "Legacy Customer", definition="a party")
    klass = smm.create_concept(coll, "Legacy Asset", concept_type="class")
    prop = smm.create_concept(coll, "legacy owns", concept_type="property")
    for c in (concept, klass, prop):
        _strip_status(smm, coll, c["iri"])

    # get_concept (knowledge CRUD) and get_concept_details share the metadata path.
    assert smm.get_concept(concept["iri"])["status"] == "draft"
    assert smm.get_concept(klass["iri"])["status"] == "draft"
    assert smm.get_concept_details(concept["iri"]).status == "draft"
    # Properties are not governed entries: no default.
    assert smm.get_concept(prop["iri"])["status"] is None

    # concepts-grouped (Explore) path.
    assert _grouped_status(smm, bucket, concept["iri"]) == "draft"
    assert _grouped_status(smm, bucket, klass["iri"]) == "draft"
    assert _grouped_status(smm, bucket, prop["iri"]) is None

    # Display only: the graph still carries no status triple.
    ctx = smm._graph.get_context(URIRef(coll))
    assert smm._get_literal(ctx, URIRef(concept["iri"]), ONTOS.status) is None

    # An explicit stored status is never overridden.
    ctx.add((URIRef(concept["iri"]), ONTOS.status, Literal("under_review")))
    assert smm.get_concept(concept["iri"])["status"] == "under_review"


def test_read_only_source_keeps_null_status(smm):
    ctx_name = f"urn:ontology:bundled-{uuid.uuid4().hex[:6]}"
    ctx = smm._graph.get_context(URIRef(ctx_name))
    iri = f"http://example.org/bundled/{uuid.uuid4().hex[:6]}#Thing"
    ctx.add((URIRef(iri), RDF.type, OWL.Class))
    ctx.add((URIRef(iri), SKOS.prefLabel, Literal("Bundled Thing")))

    assert smm.get_concept(iri)["status"] is None
    smm._invalidate_cache()
    found = [
        c for bucket in smm.get_grouped_concepts().values() for c in bucket if c.iri == iri
    ]
    assert found and found[0].status is None
