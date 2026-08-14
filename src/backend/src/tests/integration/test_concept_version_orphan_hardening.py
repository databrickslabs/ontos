"""STRUCTURAL hardening against orphaned concept_version rows (2026-08-14).

Two prongs behind the "Failed to create concept" clash and the "Upload apply
failed" 500:

  PRONG A — close the remaining delete paths that LEAVE orphans:
    * ``delete_concept`` now deletes the concept's version rows (delete_by_iri).
    * ``delete`` (semantic-model delete) now deletes the context's version rows
      (delete_for_collection on the ``urn:semantic-model:*`` context).

  PRONG B — a single new-concept mint chokepoint (``_mint_new_concept_version``)
    self-heals orphaned leftovers and mints max_version+1, so no fresh-v1 caller
    can collide on the unique constraints regardless of leftover rows.
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
    def _make(label: str = None, prefix: str = "OrphanHarden"):
        r = client.post("/api/knowledge/collections", json={
            "label": label or f"{prefix} {uuid.uuid4().hex[:8]}",
            "collection_type": "glossary",
            "scope_level": "enterprise",
            "description": "concept_version orphan-hardening test",
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


def _bucket_key(coll_iri: str) -> str:
    return coll_iri.split(":")[-1]


# ---------------------------------------------------------------------------
# PRONG A.1 — delete_concept leaves NO orphaned version rows.
# ---------------------------------------------------------------------------

def test_delete_concept_leaves_no_orphaned_version_rows(
    client, make_collection, semantic_models_manager, db_session
):
    from src.repositories.concept_versions_repository import concept_versions_repo

    coll = make_collection()
    coll_iri = coll["iri"]
    concept_iri = _make_concept(client, coll_iri, "Customer", "a draft concept")

    # A freshly created draft concept is versioned.
    assert concept_versions_repo.list_versions(db_session, concept_iri)

    assert semantic_models_manager.delete_concept(concept_iri, deleted_by="tester") is True

    assert concept_versions_repo.list_versions(db_session, concept_iri) == [], (
        "delete_concept left orphaned concept_version rows behind"
    )


# ---------------------------------------------------------------------------
# PRONG A.2 — delete_semantic_model path.
#
# The manager-level semantic-model delete (``delete``) requires a persisted
# SemanticModelDb row (repo/file setup) that the integration fixtures here do
# not provide. We therefore SKIP the full-path assertion and instead unit-assert
# the underlying repo call (delete_for_collection) removes prefixed rows — the
# exact wiring the code change now performs on the ``urn:semantic-model:*``
# context. The code change itself is still in place in ``delete``.
# ---------------------------------------------------------------------------

def test_delete_semantic_model_removes_prefixed_version_rows(
    semantic_models_manager, db_session
):
    from src.repositories.concept_versions_repository import concept_versions_repo

    context_name = f"urn:semantic-model:{uuid.uuid4().hex[:8]}"

    in_model_a = f"{context_name}/Customer"
    in_model_b = f"{context_name}/Prospect"
    # A sibling context that must NOT be touched (prefix must be exact).
    other = f"urn:semantic-model:{uuid.uuid4().hex[:8]}/Customer"

    for iri in (in_model_a, in_model_b, other):
        concept_versions_repo.create_version(
            db_session, iri=iri, version=1, is_current=True, status="active"
        )
    db_session.commit()

    removed = concept_versions_repo.delete_for_collection(db_session, context_name)
    db_session.commit()

    assert removed == 2
    assert concept_versions_repo.list_versions(db_session, in_model_a) == []
    assert concept_versions_repo.list_versions(db_session, in_model_b) == []
    # Sibling context untouched.
    assert concept_versions_repo.list_versions(db_session, other)


# ---------------------------------------------------------------------------
# PRONG A + B — recreate a concept after deleting it (structural guarantee).
# ---------------------------------------------------------------------------

def test_recreate_concept_after_delete_concept(
    client, make_collection, semantic_models_manager, db_session
):
    from src.repositories.concept_versions_repository import concept_versions_repo

    coll = make_collection()
    coll_iri = coll["iri"]

    concept_iri = _make_concept(client, coll_iri, "Customer", "v1")
    assert semantic_models_manager.delete_concept(concept_iri, deleted_by="tester") is True
    assert concept_versions_repo.list_versions(db_session, concept_iri) == []

    # Recreate the SAME concept in the SAME (still-existing) scheme -> SAME IRI.
    concept_iri2 = _make_concept(client, coll_iri, "Customer", "v1 again")
    assert concept_iri2 == concept_iri

    semantic_models_manager._invalidate_cache()
    grouped = semantic_models_manager.get_grouped_concepts()
    labels = [c.label for c in grouped.get(_bucket_key(coll_iri), [])]
    assert "Customer" in labels, f"recreated concept missing from listing: {labels}"


# ---------------------------------------------------------------------------
# PRONG B — the chokepoint self-heals an orphan and mints exactly one current v1.
# ---------------------------------------------------------------------------

def test_mint_new_concept_version_self_heals_orphan(
    semantic_models_manager, db_session
):
    from src.repositories.concept_versions_repository import concept_versions_repo

    iri = "urn:ontology:harden-test/thing"
    context_name = f"urn:context:{uuid.uuid4().hex[:8]}"

    # Seed an orphaned version row (IRI with NO backing rdf_triples).
    concept_versions_repo.create_version(
        db_session, iri=iri, version=1, is_current=True, status="active"
    )
    db_session.commit()
    assert concept_versions_repo.list_versions(db_session, iri)

    v1 = semantic_models_manager._mint_new_concept_version(
        iri, context_name, actor="tester", status="active"
    )
    db_session.commit()

    assert v1.is_current is True
    versions = concept_versions_repo.list_versions(db_session, iri)
    assert len(versions) == 1, f"expected exactly one version row, got {len(versions)}"
    assert versions[0].is_current is True
