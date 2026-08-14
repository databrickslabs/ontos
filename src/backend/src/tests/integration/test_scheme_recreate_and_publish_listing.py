"""ACCEPTANCE gate for two live cbv2b production bugs (2026-08-14).

BUG A — publishing a concept blanked its ENTIRE scheme in Explore.
    Root cause: ``_compute_all_concepts`` constructed every OntologyConcept inside
    ONE try/except wrapping the whole context loop. ``update_concept_status`` writes
    ``status='published'`` (also 'certified'/'archived'), but the ``ConceptStatus``
    enum lacked those members, so the Pydantic ValidationError from ONE concept was
    swallowed by the broad except and EVERY concept in the scheme vanished from the
    grouped listing. Fix: add the missing enum members + a per-concept guard so one
    bad concept can never blank the whole context.

BUG B — recreating a same-named scheme+concept failed ("Failed to create concept").
    Root cause: ``delete_collection`` deleted rdf_triples but NOT the concept_version
    rows. Those orphaned rows (keyed by concept IRI) then collided with the unique
    constraints when a same-named concept was recreated with the identical IRI. Fix:
    delete_collection now also removes the collection's concept_version rows, and
    create_concept self-heals any PRE-EXISTING orphans (version rows with no backing
    rdf_triples) before minting v1.
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
from src.models.ontology import ConceptStatus


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
    def _make(label: str = None, prefix: str = "Recreate"):
        r = client.post("/api/knowledge/collections", json={
            "label": label or f"{prefix} {uuid.uuid4().hex[:8]}",
            "collection_type": "glossary",
            "scope_level": "enterprise",
            "description": "scheme recreate + publish listing test",
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
    """Group key used by get_grouped_concepts (source_context = IRI suffix)."""
    return coll_iri.split(":")[-1]


# ---------------------------------------------------------------------------
# BUG A
# ---------------------------------------------------------------------------

def test_published_status_enum_constructs():
    """ConceptStatus must know every literal the state machine writes."""
    assert ConceptStatus("published") == ConceptStatus.PUBLISHED
    assert ConceptStatus("certified") == ConceptStatus.CERTIFIED
    assert ConceptStatus("archived") == ConceptStatus.ARCHIVED


def test_publishing_one_concept_does_not_blank_scheme(
    client, make_collection, semantic_models_manager, db_session
):
    coll = make_collection()
    coll_iri = coll["iri"]
    suffix = _bucket_key(coll_iri)

    iri_a = _make_concept(client, coll_iri, "Customer", "a party we sell to")
    iri_b = _make_concept(client, coll_iri, "Prospect", "a potential customer")
    q = quote(iri_a, safe="")

    # Walk the status machine to 'published' via the real routes.
    assert client.post(
        f"/api/knowledge/concepts/by-iri/submit-review?iri={q}", json={}
    ).status_code == 200
    assert client.post(
        f"/api/knowledge/concepts/by-iri/approve?iri={q}"
    ).status_code == 200
    assert client.post(
        f"/api/knowledge/concepts/by-iri/publish?iri={q}"
    ).status_code == 200

    # Force a fresh recompute from the graph (the cold 'computing live' path).
    semantic_models_manager._invalidate_cache()

    grouped = semantic_models_manager.get_grouped_concepts()
    labels = sorted(c.label for c in grouped.get(suffix, []))
    # BUG A regression: the published concept must NOT drop the whole scheme.
    assert labels == ["Customer", "Prospect"], (
        f"publishing blanked the scheme; got {labels} for bucket {suffix!r}"
    )


# ---------------------------------------------------------------------------
# BUG B
# ---------------------------------------------------------------------------

def test_recreate_same_named_scheme_and_concept(
    client, make_collection, semantic_models_manager, db_session
):
    from src.repositories.concept_versions_repository import concept_versions_repo

    label = f"Recreate {uuid.uuid4().hex[:8]}"
    coll = make_collection(label=label)
    coll_iri = coll["iri"]
    concept_iri = _make_concept(client, coll_iri, "Customer", "v1")

    # Sanity: it is versioned.
    assert concept_versions_repo.list_versions(db_session, concept_iri)

    # Delete the whole scheme.
    assert semantic_models_manager.delete_collection(coll_iri, deleted_by="tester") is True

    # BUG B regression: no orphaned concept_version rows must remain.
    assert concept_versions_repo.list_versions(db_session, concept_iri) == [], (
        "delete_collection left orphaned concept_version rows behind"
    )

    # Re-create a scheme with the SAME label -> SAME sanitized IRI, then the SAME
    # concept label -> SAME concept IRI. This must succeed, not IntegrityError.
    coll2 = make_collection(label=label)
    assert coll2["iri"] == coll_iri, "same label must yield the same sanitized IRI"
    concept_iri2 = _make_concept(client, coll_iri, "Customer", "v1 again")
    assert concept_iri2 == concept_iri

    semantic_models_manager._invalidate_cache()
    grouped = semantic_models_manager.get_grouped_concepts()
    labels = [c.label for c in grouped.get(_bucket_key(coll_iri), [])]
    assert "Customer" in labels, f"recreated concept missing from listing: {labels}"


def test_create_concept_self_heals_orphaned_version_rows(
    client, make_collection, semantic_models_manager, db_session
):
    """Pre-existing orphan (version row with NO backing rdf_triples) must be
    cleaned so the concept can be recreated without a manual DB fix."""
    from src.repositories.concept_versions_repository import concept_versions_repo

    coll = make_collection()
    coll_iri = coll["iri"]

    # Manufacture an orphan: a concept_version row for an IRI that has NO triples.
    orphan_iri = f"{coll_iri}/customer"
    concept_versions_repo.create_version(
        db_session, iri=orphan_iri, version=1, is_current=True, status="draft"
    )
    db_session.commit()
    assert concept_versions_repo.list_versions(db_session, orphan_iri)

    # Creating the concept with that same IRI must succeed (orphan self-healed).
    result = semantic_models_manager.create_concept(
        collection_iri=coll_iri, label="Customer", definition="fresh", created_by="tester"
    )
    assert result is not None
    assert (result.get("iri") or (result.get("concept") or {}).get("iri")) == orphan_iri

    # Exactly one CURRENT version now (the freshly-minted v1), not a duplicate.
    versions = concept_versions_repo.list_versions(db_session, orphan_iri)
    current = [v for v in versions if v.is_current]
    assert len(current) == 1, f"expected one current version, got {len(current)}"
