"""REPRO: concept vanishes from served graph after status-walk + publish.

User report (2026-08-14): created 'Customer', edited it in draft, moved it
through statuses toward Publish; an error popped and after reload the concept
was GONE from Explore. We suspect a triple-ownership (concept_version_id)
mismatch that drops the concept out of list_current (the ONLY reader that
builds the served hot graph).

This test does NOT assert a fix yet — it DUMPS the DB + graph state at each
step so we can see exactly when/why the concept leaves list_current.
"""
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.app import app
from src.controller.semantic_models_manager import SemanticModelsManager
from src.common.app_state import set_app_state_manager


@pytest.fixture
def smm(db_session: Session, tmp_path: Path):
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


def _dump(tag, db_session, manager, iri):
    from src.repositories.rdf_triples_repository import rdf_triples_repo
    from src.repositories.concept_versions_repository import concept_versions_repo
    from src.db_models.rdf_triples import RdfTripleDb

    print(f"\n===== {tag} =====")
    rows = db_session.query(RdfTripleDb).filter(RdfTripleDb.subject_uri == iri).all()
    print(f"  rdf_triples rows for subject ({len(rows)}):")
    for r in rows:
        pred = r.predicate_uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        print(f"    cv_id={str(r.concept_version_id)[:8]:8}  {pred:14} = {r.object_value[:40]!r}")
    cvs = concept_versions_repo.list_versions(db_session, iri)
    print(f"  concept_version rows ({len(cvs)}):")
    for cv in cvs:
        print(f"    id={str(cv.id)[:8]}  v{cv.version}  is_current={cv.is_current}  status={cv.status}")
    current = rdf_triples_repo.list_current(db_session)
    in_current = [t for t in current if t.subject_uri == iri]
    print(f"  >>> subject present in list_current? {len(in_current) > 0} ({len(in_current)} triples)")
    concept_uri = iri
    from rdflib import URIRef
    in_graph = list(manager._graph.triples((URIRef(concept_uri), None, None)))
    print(f"  >>> subject present in served GRAPH? {len(in_graph) > 0} ({len(in_graph)} triples)")


def test_repro_status_walk_then_publish(client: TestClient, smm, db_session):
    # 1. create scheme + concept
    r = client.post("/api/knowledge/collections", json={
        "label": f"Repro {uuid.uuid4().hex[:6]}", "collection_type": "glossary",
        "scope_level": "enterprise", "description": "repro",
    })
    assert r.status_code == 200, r.text
    coll_iri = r.json()["iri"]

    r = client.post("/api/knowledge/concepts", json={
        "collection_iri": coll_iri, "label": "Customer", "definition": "v1 def",
    })
    assert r.status_code == 200, r.text
    iri = r.json().get("iri") or r.json().get("concept", {}).get("iri")
    _dump("AFTER CREATE", db_session, smm, iri)

    # 2. draft edit (update_concept) via canonical by-iri PATCH
    from urllib.parse import quote
    q = quote(iri, safe="")
    r = client.patch(f"/api/knowledge/concepts/by-iri?iri={q}",
                     json={"definition": "edited draft def"})
    print("draft edit status:", r.status_code, r.text[:120])
    _dump("AFTER DRAFT EDIT", db_session, smm, iri)

    # 3. submit-review -> approve -> publish (the exact UI status walk)
    r = client.post(f"/api/knowledge/concepts/by-iri/submit-review?iri={q}", json={})
    print("submit-review:", r.status_code, r.text[:120])
    _dump("AFTER SUBMIT-REVIEW", db_session, smm, iri)

    r = client.post(f"/api/knowledge/concepts/by-iri/approve?iri={q}")
    print("approve:", r.status_code, r.text[:120])
    _dump("AFTER APPROVE", db_session, smm, iri)

    r = client.post(f"/api/knowledge/concepts/by-iri/publish?iri={q}")
    print("publish:", r.status_code, r.text[:120])
    _dump("AFTER PUBLISH", db_session, smm, iri)


def test_repro_version_engine_publish_after_draft_edit(client: TestClient, smm, db_session):
    """The version-engine publish (the 'mint a new version' UI knob) AFTER a
    draft edit. draft-edit re-writes SKOS fields as NULL-owned; publish copies
    ONLY v1-owned rows to v2 then demotes v1. Does the concept survive in
    list_current?"""
    from urllib.parse import quote
    r = client.post("/api/knowledge/collections", json={
        "label": f"Repro2 {uuid.uuid4().hex[:6]}", "collection_type": "glossary",
        "scope_level": "enterprise", "description": "repro2",
    })
    coll_iri = r.json()["iri"]
    r = client.post("/api/knowledge/concepts", json={
        "collection_iri": coll_iri, "label": "Customer", "definition": "v1 def",
    })
    iri = r.json().get("iri") or r.json().get("concept", {}).get("iri")
    q = quote(iri, safe="")
    _dump("V2: AFTER CREATE", db_session, smm, iri)

    # draft edit -> rewrites definition as NULL-owned
    r = client.patch(f"/api/knowledge/concepts/by-iri?iri={q}",
                     json={"definition": "edited draft def"})
    print("draft edit:", r.status_code)
    _dump("V2: AFTER DRAFT EDIT", db_session, smm, iri)

    # version-engine publish (mint v2)
    r = client.post("/api/semantic-models/concepts/version/publish",
                    json={"iri": iri, "changes": {"definition": "v2 published def"}})
    print("version/publish:", r.status_code, r.text[:160])
    _dump("V2: AFTER VERSION PUBLISH", db_session, smm, iri)

    # Now a SECOND publish (mint v3) — the user published more than once
    r = client.post("/api/semantic-models/concepts/version/publish",
                    json={"iri": iri, "changes": {"definition": "v3 def"}})
    print("version/publish #2:", r.status_code, r.text[:160])
    _dump("V2: AFTER 2ND VERSION PUBLISH", db_session, smm, iri)
