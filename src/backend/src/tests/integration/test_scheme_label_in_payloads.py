"""Scheme rename is reflected wherever a scheme is labelled from its key.

Concepts carry their scheme as a raw ``source_context`` key (for an uploaded
file this is the file name). Two backend payloads used that key as the
display name, so a renamed scheme kept showing its old key:

  * ``get_coverage_metrics``: each ``CoverageSchemeRow.label`` now comes from
    the scheme's collection record (``scheme`` stays the key, it is the id the
    frontend uses in pending-suggestions URLs);
  * ``submit_concept_for_review``: the approval payload now carries
    ``source_label`` next to ``source_context`` when the scheme has a record,
    and it reaches the approval notification's ``full_payload``.
"""
import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rdflib import Literal, URIRef
from rdflib.namespace import RDF, RDFS, SKOS
from sqlalchemy.orm import Session

from src.app import app
from src.common.app_state import set_app_state_manager
from src.controller.semantic_models_manager import ONTOS, SemanticModelsManager
from src.controller.workflows_manager import WorkflowsManager
from src.db_models.notifications import NotificationDb

WORKFLOW_NAME = "Concept Reviewer Approval (Default)"

RENAMED_IRI = "urn:glossary:upload-2024-q3.ttl"
RENAMED_KEY = "upload-2024-q3.ttl"
NO_RECORD_IRI = "urn:glossary:orphan-source"
NO_RECORD_KEY = "orphan-source"
UNASSIGNED_IRI = "urn:custom-context:loose"


@pytest.fixture
def smm(db_session: Session, tmp_path: Path, mock_workspace_client):
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


def _add_concepts(manager, iri, prefix, n):
    ctx = manager._graph.get_context(URIRef(iri))
    for i in range(n):
        concept = URIRef(f"http://example.org/{prefix}/c{i}")
        ctx.add((concept, RDF.type, SKOS.Concept))
        ctx.add((concept, SKOS.prefLabel, Literal(f"{prefix} {i}")))


def _add_record(manager, iri, label):
    meta = manager._graph.get_context(URIRef("urn:meta:sources"))
    coll = URIRef(iri)
    meta.add((coll, RDF.type, ONTOS.KnowledgeCollection))
    meta.add((coll, RDFS.label, Literal(label)))
    meta.add((coll, ONTOS.collectionType, Literal("glossary")))
    meta.add((coll, ONTOS.isEditable, Literal("true")))


@pytest.fixture
def seeded(smm):
    _add_record(smm, RENAMED_IRI, "Quarterly Glossary")
    _add_concepts(smm, RENAMED_IRI, "renamed", 2)
    _add_concepts(smm, NO_RECORD_IRI, "orphan", 2)
    _add_concepts(smm, UNASSIGNED_IRI, "loose", 1)
    # Grouping reads the in-memory concept cache; refresh it after seeding.
    smm._cached_concepts = smm._compute_all_concepts()
    return smm


class _LinksStub:
    def __init__(self, db):
        self._db = db


def _rows(manager, db_session):
    resp = manager.get_coverage_metrics(_LinksStub(db_session))
    return {r.scheme: r for r in resp.schemes}


# --- coverage rows ---------------------------------------------------------


def test_coverage_row_uses_collection_label_and_keeps_key(seeded, db_session):
    rows = _rows(seeded, db_session)
    assert rows[RENAMED_KEY].label == "Quarterly Glossary"
    assert rows[RENAMED_KEY].scheme == RENAMED_KEY


def test_coverage_row_follows_rename(seeded, db_session):
    meta = seeded._graph.get_context(URIRef("urn:meta:sources"))
    meta.set((URIRef(RENAMED_IRI), RDFS.label, Literal("Renamed Glossary")))
    rows = _rows(seeded, db_session)
    assert rows[RENAMED_KEY].label == "Renamed Glossary"
    assert rows[RENAMED_KEY].scheme == RENAMED_KEY


def test_coverage_row_without_record_falls_back_to_key(seeded, db_session):
    rows = _rows(seeded, db_session)
    assert rows[NO_RECORD_KEY].label == NO_RECORD_KEY


def test_coverage_unassigned_label_stays_none(seeded, db_session):
    rows = _rows(seeded, db_session)
    assert "Unassigned" in rows
    assert rows["Unassigned"].label is None


# --- submit payload --------------------------------------------------------


def _make_draft_concept(client: TestClient, label: str):
    r = client.post("/api/knowledge/collections", json={
        "label": f"Scheme Label {uuid.uuid4().hex[:8]}", "collection_type": "glossary",
        "scope_level": "enterprise", "description": "scheme label payload test",
    })
    assert r.status_code == 200, r.text
    coll = r.json()
    r = client.post("/api/knowledge/concepts", json={
        "collection_iri": coll["iri"], "label": label, "definition": "def",
    })
    assert r.status_code == 200, r.text
    b = r.json()
    return coll, b.get("iri") or (b.get("concept") or {}).get("iri")


def _capture_entity_data(monkeypatch):
    captured = {}

    class _Registry:
        def on_request_status_change(self, **kwargs):
            captured.update(kwargs.get("entity_data") or {})
            return []

    import src.common.workflow_triggers as wt
    monkeypatch.setattr(wt, "get_trigger_registry", lambda db: _Registry())
    return captured


def _payload(n) -> dict:
    p = n.action_payload or {}
    return json.loads(p) if isinstance(p, str) else p


def test_submit_payload_carries_source_label_into_full_payload(client, smm, db_session):
    WorkflowsManager(db=db_session).load_from_yaml()
    coll, iri = _make_draft_concept(client, "Customer")
    smm.update_collection(coll["iri"], label="Renamed Scheme")

    out = smm.submit_concept_for_review(
        concept_iri=iri, reviewer_email="reviewer@example.com",
        submitted_by="author@example.com",
    )
    assert out["governed"] is True

    notes = [
        n for n in db_session.query(NotificationDb).filter(
            NotificationDb.action_type == "workflow_approval"
        ).all()
        if _payload(n).get("entity_id") == iri
        and _payload(n).get("workflow_name") == WORKFLOW_NAME
    ]
    assert len(notes) == 1
    full = _payload(notes[0])["full_payload"]
    assert full["source_context"] == coll["iri"]
    assert full["source_label"] == "Renamed Scheme"


def test_submit_payload_omits_source_label_without_record(client, smm, monkeypatch):
    coll, iri = _make_draft_concept(client, "Revenue")
    # Drop the scheme's collection record; its concepts stay in place.
    meta = smm._graph.get_context(URIRef("urn:meta:sources"))
    meta.remove((URIRef(coll["iri"]), None, None))
    smm._invalidate_cache()
    captured = _capture_entity_data(monkeypatch)

    smm.submit_concept_for_review(
        concept_iri=iri, reviewer_email=None, submitted_by="author@example.com",
    )
    assert captured["source_context"] == coll["iri"]
    assert "source_label" not in captured


def test_submit_survives_label_lookup_failure(client, smm, monkeypatch):
    _, iri = _make_draft_concept(client, "Margin")
    captured = _capture_entity_data(monkeypatch)

    def _boom():
        raise RuntimeError("meta read failed")

    monkeypatch.setattr(smm, "_scheme_labels_by_source_key", _boom)
    smm.submit_concept_for_review(
        concept_iri=iri, reviewer_email=None, submitted_by="author@example.com",
    )
    assert "source_context" in captured
    assert "source_label" not in captured
