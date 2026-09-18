"""ACCEPTANCE gate for the re-upload / diff-apply orphan-version self-heal.

BUG (repro'd via cbv2b app logs 2026-08-14): a diff-apply 500'd with
``sqlalchemy.exc.IntegrityError: duplicate key value violates unique constraint
"uq_concept_version_iri_version"`` and the whole atomic apply rolled back
("Upload apply failed; the store is unchanged").

Root cause: ``_import_new_concept_from_graph`` handles the diff's NEW-concept
bucket and unconditionally minted ``create_version(iri, version=1)`` preserving
the FILE-NATIVE IRI. If that exact IRI already had leftover concept_version rows
(a previously-deleted scheme sharing the IRI, a prior failed upload, or the same
IRI used in another context) the insert collided on
``uq_concept_version_iri_version`` / ``uq_concept_version_current_per_iri``.

Fix: apply the SAME orphan self-heal already used by ``create_concept`` to the
upload/versioning-event path (``_import_new_concept_from_graph`` and the shared
``_ensure_concept_version_v1``) so a diff-apply can never 500 on leftover rows.
"""
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph, URIRef, Literal
from rdflib.namespace import RDF, SKOS
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
    def _make(label: str = None, prefix: str = "OrphanHeal"):
        r = client.post("/api/knowledge/collections", json={
            "label": label or f"{prefix} {uuid.uuid4().hex[:8]}",
            "collection_type": "glossary",
            "scope_level": "enterprise",
            "description": "upload orphan-version self-heal test",
        })
        assert r.status_code == 200, r.text
        return r.json()

    return _make


def _concept_graph(iri: str, label: str = "Thing") -> Graph:
    g = Graph()
    g.add((URIRef(iri), RDF.type, SKOS.Concept))
    g.add((URIRef(iri), SKOS.prefLabel, Literal(label)))
    return g


# ---------------------------------------------------------------------------
# 1. ORPHAN-then-import via the helper directly.
# ---------------------------------------------------------------------------

def test_import_new_concept_self_heals_orphaned_version_rows(
    semantic_models_manager, db_session
):
    from src.repositories.concept_versions_repository import concept_versions_repo
    from src.repositories.rdf_triples_repository import rdf_triples_repo

    iri = "urn:ontology:orphan-test/thing"
    context_name = f"urn:context:{uuid.uuid4().hex[:8]}"

    # Manufacture an orphan: a concept_version row for an IRI with NO rdf_triples.
    concept_versions_repo.create_version(
        db_session, iri=iri, version=1, is_current=True, status="active"
    )
    db_session.commit()
    assert concept_versions_repo.list_versions(db_session, iri)

    g = _concept_graph(iri, "Thing")

    # This is the exact call the diff-apply makes for a NEW-bucket concept. It
    # must NOT raise an IntegrityError on the leftover (iri, version=1) row.
    semantic_models_manager._import_new_concept_from_graph(
        iri, g, context_name, actor="tester"
    )
    db_session.commit()

    # Exactly one CURRENT version, and its triples are present + owned.
    versions = concept_versions_repo.list_versions(db_session, iri)
    current = [v for v in versions if v.is_current]
    assert len(current) == 1, f"expected one current version, got {len(current)}"

    subject_rows = [
        t for t in rdf_triples_repo.list_by_subject(db_session, iri)
        if t.context_name == context_name
    ]
    assert subject_rows, "imported concept must have triples in this context"
    assert all(t.concept_version_id == current[0].id for t in subject_rows), (
        "every imported triple must be owned by the current concept_version"
    )


# ---------------------------------------------------------------------------
# 2. FULL PATH via apply_upload_as_versioning_event.
# ---------------------------------------------------------------------------

def test_apply_upload_recovers_from_orphaned_version_rows(
    make_collection, semantic_models_manager, db_session
):
    from src.repositories.concept_versions_repository import concept_versions_repo

    coll = make_collection()
    coll_iri = coll["iri"]

    # A file-native IRI that the incoming graph will introduce as a NEW concept.
    file_native_iri = "http://example.org/Customer"

    # Seed an orphaned concept_version row for that IRI (no rdf_triples in the
    # collection context). This is the exact collision that used to 500 the apply.
    concept_versions_repo.create_version(
        db_session, iri=file_native_iri, version=1, is_current=True, status="active"
    )
    db_session.commit()
    assert concept_versions_repo.list_versions(db_session, file_native_iri)

    g = _concept_graph(file_native_iri, "Customer")

    # KEY ASSERTION: no IntegrityError / no 500 — the atomic apply completes.
    summary = semantic_models_manager.apply_upload_as_versioning_event(
        context_name=coll_iri, incoming_graph=g, actor="tester"
    )
    assert summary is not None
    assert summary.get("new") == 1, f"the file-native IRI must be a NEW concept: {summary}"

    # The concept is now versioned (exactly one current version) and its triples
    # are present in the collection context.
    versions = concept_versions_repo.list_versions(db_session, file_native_iri)
    current = [v for v in versions if v.is_current]
    assert len(current) == 1, f"expected one current version, got {len(current)}"

    from src.repositories.rdf_triples_repository import rdf_triples_repo
    subject_rows = [
        t for t in rdf_triples_repo.list_by_subject(db_session, file_native_iri)
        if t.context_name == coll_iri
    ]
    assert subject_rows, "new concept must have triples in the collection context"
