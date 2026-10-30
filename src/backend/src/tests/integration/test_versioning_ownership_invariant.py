"""ACCEPTANCE gate for the concept-version OWNERSHIP INVARIANT fix.

Root cause (repro'd 2026-08-14): a versioned concept's live triples must all be
owned by its CURRENT concept_version (or be genuinely-shared/unowned metadata).
Three write paths violated this:

  * ``create_concept`` stamped rows with v1.id (CORRECT), but
  * ``update_concept`` (draft edit) re-added rewritten rows as NULL-owned, and
  * ``update_concept_status`` (status walk / publish button) did the same.
  * ``publish_concept_version`` then copied only the source-version-owned rows to
    v2, leaving the NULL-owned edits dangling and, in the worst case, minting an
    EMPTY v2 -> the concept dropped out of ``list_current`` (the served graph
    builder) and VANISHED from the UI though the DB still had it current.

This suite pins the invariant end-to-end through the real REST routes:

  1. INVARIANT — after any edit/status-walk, every live SKOS row for the subject
     is owned by the current concept_version (no NULL-owned concept payload rows;
     genuinely-shared metadata is out of scope — concepts don't emit any here).
  2. NO DUPLICATE FIELD — after draft-edit-then-publish, the served graph has
     exactly ONE definition (the edited one folded into v2), not two.
  3. NO VANISH — the exact user sequence (create -> draft edit -> version publish
     x2) keeps the concept present in ``list_current`` AND the served graph with
     a NON-EMPTY triple set at every step.
  4. VERSION NOT HARDCODED — the version-info / concept read reflects the real
     current version number (2 after one publish), never a frozen "1.0.0".
"""
import uuid
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
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
    def _make(prefix="OwnInv"):
        r = client.post("/api/knowledge/collections", json={
            "label": f"{prefix} {uuid.uuid4().hex[:8]}", "collection_type": "glossary",
            "scope_level": "enterprise", "description": "ownership invariant test",
        })
        assert r.status_code == 200, r.text
        return r.json()

    return _make


def _make_concept(client, coll_iri, label, definition):
    r = client.post("/api/knowledge/concepts", json={
        "collection_iri": coll_iri, "label": label, "definition": definition,
    })
    assert r.status_code == 200, r.text
    b = r.json()
    return b.get("iri") or (b.get("concept") or {}).get("iri")


# Predicates that carry CONCEPT PAYLOAD (as opposed to genuinely-shared graph
# metadata). Every one of these, when present for a versioned subject, MUST be
# owned by a concept_version — never NULL.
_SKOS = "http://www.w3.org/2004/02/skos/core#"
_ONTOS = "http://ontos.app/ontology#"
_PAYLOAD_PREDS = {
    _SKOS + "prefLabel", _SKOS + "definition", _SKOS + "altLabel",
    _SKOS + "example", _SKOS + "broader", _SKOS + "narrower", _SKOS + "related",
    _ONTOS + "status",
}


def _subject_rows(db, iri):
    from src.db_models.rdf_triples import RdfTripleDb
    return db.query(RdfTripleDb).filter(RdfTripleDb.subject_uri == iri).all()


def _assert_no_null_owned_payload(db, iri, phase):
    """INVARIANT 1: no payload row for a versioned subject is NULL-owned."""
    from src.repositories.concept_versions_repository import concept_versions_repo
    versioned = concept_versions_repo.list_versions(db, iri)
    if not versioned:
        return  # not versioned yet — invariant doesn't apply
    offenders = [
        r for r in _subject_rows(db, iri)
        if r.concept_version_id is None and r.predicate_uri in _PAYLOAD_PREDS
    ]
    assert not offenders, (
        f"[{phase}] {len(offenders)} NULL-owned payload rows for {iri}: "
        + ", ".join(sorted({o.predicate_uri.rsplit('#', 1)[-1] for o in offenders}))
    )


def _present_in_served_graph(manager, db, iri):
    """Concept is present iff list_current returns rows for it AND they are in
    the served in-memory graph."""
    from rdflib import URIRef
    from src.repositories.rdf_triples_repository import rdf_triples_repo
    in_current = [t for t in rdf_triples_repo.list_current(db) if t.subject_uri == iri]
    in_graph = list(manager._graph.triples((URIRef(iri), None, None)))
    return len(in_current) > 0, len(in_graph) > 0


def test_ownership_invariant_survives_status_walk(client, make_collection, semantic_models_manager, db_session):
    coll = make_collection()
    iri = _make_concept(client, coll["iri"], "Customer", "v1 def")
    q = quote(iri, safe="")
    _assert_no_null_owned_payload(db_session, iri, "after create")

    # draft edit
    r = client.patch(f"/api/knowledge/concepts/by-iri?iri={q}", json={"definition": "edited draft def"})
    assert r.status_code == 200, r.text
    _assert_no_null_owned_payload(db_session, iri, "after draft edit")

    # status walk: submit-review -> approve -> publish (the buttons the user used)
    assert client.post(f"/api/knowledge/concepts/by-iri/submit-review?iri={q}", json={}).status_code == 200
    _assert_no_null_owned_payload(db_session, iri, "after submit-review")
    assert client.post(f"/api/knowledge/concepts/by-iri/approve?iri={q}").status_code == 200
    _assert_no_null_owned_payload(db_session, iri, "after approve")
    assert client.post(f"/api/knowledge/concepts/by-iri/publish?iri={q}").status_code == 200
    _assert_no_null_owned_payload(db_session, iri, "after publish(status)")

    cur, graph = _present_in_served_graph(semantic_models_manager, db_session, iri)
    assert cur and graph, "concept must remain visible after the status walk"


def test_no_vanish_and_no_duplicate_after_draft_edit_then_version_publish(
    client, make_collection, semantic_models_manager, db_session
):
    coll = make_collection()
    iri = _make_concept(client, coll["iri"], "Customer", "v1 def")
    q = quote(iri, safe="")

    # draft edit rewrites the definition
    assert client.patch(f"/api/knowledge/concepts/by-iri?iri={q}",
                        json={"definition": "edited draft def"}).status_code == 200

    # version-engine publish (the "mint a new version" knob) — v2
    r = client.post("/api/semantic-models/concepts/version/publish",
                    json={"iri": iri, "changes": {"definition": "v2 published def"}})
    assert r.status_code == 200, r.text
    assert r.json().get("new_version") == 2

    # INVARIANT holds after publish
    _assert_no_null_owned_payload(db_session, iri, "after version publish")

    # NO VANISH
    cur, graph = _present_in_served_graph(semantic_models_manager, db_session, iri)
    assert cur and graph, "concept vanished from served graph after version publish"

    # NO DUPLICATE FIELD: served graph has exactly one definition = the published one.
    from rdflib import URIRef
    from rdflib.namespace import SKOS
    defs = [str(o) for o in semantic_models_manager._graph.objects(URIRef(iri), SKOS.definition)]
    assert defs == ["v2 published def"], f"expected single published definition, got {defs}"

    # second publish -> v3, still present, still single definition
    r = client.post("/api/semantic-models/concepts/version/publish",
                    json={"iri": iri, "changes": {"definition": "v3 def"}})
    assert r.status_code == 200 and r.json().get("new_version") == 3, r.text
    _assert_no_null_owned_payload(db_session, iri, "after 2nd version publish")
    cur, graph = _present_in_served_graph(semantic_models_manager, db_session, iri)
    assert cur and graph, "concept vanished after 2nd version publish"
    defs = [str(o) for o in semantic_models_manager._graph.objects(URIRef(iri), SKOS.definition)]
    assert defs == ["v3 def"], f"expected single v3 definition, got {defs}"


def test_version_number_is_not_hardcoded_after_publish(client, make_collection, semantic_models_manager, db_session):
    coll = make_collection()
    iri = _make_concept(client, coll["iri"], "Revenue", "money in")
    q = quote(iri, safe="")
    r = client.post("/api/semantic-models/concepts/version/publish",
                    json={"iri": iri, "changes": {"definition": "money recognized"}})
    assert r.status_code == 200, r.text

    info = client.get(f"/api/semantic-models/concepts/version?iri={q}").json()
    assert info.get("current_version") == 2, f"version-info must show real current version 2: {info}"

    # The concept read must NOT report a frozen "1.0.0" once past v1.
    concept = client.get(f"/api/knowledge/concepts/by-iri?iri={q}").json()
    reported = str(concept.get("version") or "")
    assert reported not in ("1.0.0", "1"), (
        f"concept read still reports hardcoded version {reported!r} after publish"
    )
