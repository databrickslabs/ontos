"""Integration tests for the file-upload diff engine (P0-4).

A re-upload of a semantic-model file is a BULK VERSIONING EVENT, not a blind
delete-replace. These tests drive the real ``SemanticModelsManager`` on the
shared test DB and assert the P0-4 acceptance criteria:

- a BYTE-IDENTICAL re-upload of a blank-node-heavy OWL file (owl:Restriction)
  mints ZERO new versions — the URDNA2015 canonicalization proof;
- a re-upload that changes exactly one concept's definition mints exactly one
  new version (v2); the other concepts are untouched;
- a concept ADDED in the re-upload appears as v1;
- a concept REMOVED but still referenced (entity_semantic_links) is DEPRECATED
  (not retired / hard-deleted) and stays resolvable, with the reference intact;
- a concept REMOVED and unreferenced is DEPRECATED/tombstoned, never hard-deleted;
- a mid-apply failure rolls back the whole changeset (store unchanged, atomic).

Fixtures are local, mirroring test_concept_versioning.py (there is no shared
integration conftest).
"""
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph
from sqlalchemy.orm import Session

from src.app import app
from src.controller.semantic_models_manager import (
    SemanticModelsManager,
    _sanitize_context_name,
)
from src.common.app_state import set_app_state_manager
from src.models.semantic_models import SemanticModelCreate
from src.repositories.concept_versions_repository import concept_versions_repo
from src.repositories.rdf_triples_repository import rdf_triples_repo


# ---------------------------------------------------------------------------
# Fixtures — local, mirroring test_concept_versioning.py.
# ---------------------------------------------------------------------------


@pytest.fixture
def semantic_models_manager(db_session: Session, tmp_path: Path):
    """SemanticModelsManager on the test session + tmp data dir, published on
    app.state so route dependencies resolve."""
    data_dir = tmp_path / "sm_data"
    (data_dir / "cache").mkdir(parents=True, exist_ok=True)
    (data_dir / "taxonomies").mkdir(parents=True, exist_ok=True)

    manager = SemanticModelsManager(db=db_session, data_dir=data_dir)
    app.state.semantic_models_manager = manager
    set_app_state_manager("semantic_models_manager", manager)

    class _NoopOSM:
        def sync_asset_types(self, *_args, **_kwargs):
            return {"created": 0, "updated": 0}

    app.state.ontology_schema_manager = _NoopOSM()

    class _NoopAudit:
        def log_action(self, *_args, **_kwargs):
            return None

        def log_event(self, *_args, **_kwargs):
            return None

    app.state.audit_manager = _NoopAudit()

    yield manager

    for attr in ("semantic_models_manager", "ontology_schema_manager", "audit_manager"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)


# ---------------------------------------------------------------------------
# Fixture ontologies + helpers.
# ---------------------------------------------------------------------------

_PREFIXES = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <http://example.org/onto#> .
"""

# Blank-node-heavy OWL: an owl:Restriction anonymous class expression. On every
# parse the restriction gets a fresh blank-node label, so a naive set-diff would
# flag it as changed. URDNA2015 canonicalization makes it stable.
BNODE_TTL = _PREFIXES + """
ex:Wine a owl:Class ;
    skos:prefLabel "Wine" ;
    skos:definition "A fermented grape beverage." ;
    rdfs:subClassOf [ a owl:Restriction ;
        owl:onProperty ex:hasMaker ;
        owl:someValuesFrom ex:Winery ] .

ex:Winery a owl:Class ;
    skos:prefLabel "Winery" ;
    skos:definition "A place that makes wine." .

ex:hasMaker a owl:ObjectProperty ;
    skos:prefLabel "has maker" .
"""

WINE = "http://example.org/onto#Wine"
WINERY = "http://example.org/onto#Winery"
HASMAKER = "http://example.org/onto#hasMaker"

# Three plain glossary concepts.
GLOSSARY_V1 = _PREFIXES + """
ex:Customer a skos:Concept ;
    skos:prefLabel "Customer" ;
    skos:definition "A buyer of goods." .

ex:Revenue a skos:Concept ;
    skos:prefLabel "Revenue" ;
    skos:definition "Income from sales." .

ex:Margin a skos:Concept ;
    skos:prefLabel "Margin" ;
    skos:definition "Revenue minus cost." .
"""

CUSTOMER = "http://example.org/onto#Customer"
REVENUE = "http://example.org/onto#Revenue"
MARGIN = "http://example.org/onto#Margin"

# Same three, but Revenue's definition is edited.
GLOSSARY_REVENUE_EDITED = _PREFIXES + """
ex:Customer a skos:Concept ;
    skos:prefLabel "Customer" ;
    skos:definition "A buyer of goods." .

ex:Revenue a skos:Concept ;
    skos:prefLabel "Revenue" ;
    skos:definition "Income from sales, net of returns." .

ex:Margin a skos:Concept ;
    skos:prefLabel "Margin" ;
    skos:definition "Revenue minus cost." .
"""

# Same three + a new concept.
GLOSSARY_PLUS_NEW = _PREFIXES + """
ex:Customer a skos:Concept ;
    skos:prefLabel "Customer" ;
    skos:definition "A buyer of goods." .

ex:Revenue a skos:Concept ;
    skos:prefLabel "Revenue" ;
    skos:definition "Income from sales." .

ex:Margin a skos:Concept ;
    skos:prefLabel "Margin" ;
    skos:definition "Revenue minus cost." .

ex:Churn a skos:Concept ;
    skos:prefLabel "Churn" ;
    skos:definition "Rate of customer loss." .
"""

CHURN = "http://example.org/onto#Churn"

# Margin removed from the file.
GLOSSARY_MINUS_MARGIN = _PREFIXES + """
ex:Customer a skos:Concept ;
    skos:prefLabel "Customer" ;
    skos:definition "A buyer of goods." .

ex:Revenue a skos:Concept ;
    skos:prefLabel "Revenue" ;
    skos:definition "Income from sales." .
"""


def _parse(ttl: str) -> Graph:
    g = Graph()
    g.parse(data=ttl, format="turtle")
    return g


def _seed(manager: SemanticModelsManager, name: str, ttl: str, actor: str = "tester"):
    """First-ever upload: create the model + import + build the served graph."""
    data = SemanticModelCreate(
        name=name,
        format="skos",
        content_text=ttl,
        original_filename=name,
        content_type="text/turtle",
        size_bytes=len(ttl),
        enabled=True,
    )
    m = manager.create(data, created_by=actor)
    manager.rebuild_graph_from_enabled()
    return m


def _context(name: str) -> str:
    return f"urn:semantic-model:{_sanitize_context_name(name)}"


def _unique_name() -> str:
    return f"diff_{uuid.uuid4().hex[:8]}.ttl"


# ---------------------------------------------------------------------------
# (a) Byte-identical re-upload with blank nodes -> ZERO new versions.
# ---------------------------------------------------------------------------


class TestByteIdenticalReupload:
    def test_bnode_heavy_reupload_mints_zero_versions(
        self, semantic_models_manager, db_session
    ):
        mgr = semantic_models_manager
        name = _unique_name()
        _seed(mgr, name, BNODE_TTL)
        ctx = _context(name)

        summary = mgr.apply_upload_as_versioning_event(ctx, _parse(BNODE_TTL), actor="tester")

        # THE canonicalization proof: nothing modified/new/removed.
        assert summary["modified"] == 0, summary
        assert summary["new"] == 0, summary
        assert summary["removed"] == 0, summary
        assert summary["unchanged"] >= 3, summary  # Wine, Winery, hasMaker

        # And no concept advanced to v2.
        for iri in (WINE, WINERY, HASMAKER):
            assert concept_versions_repo.max_version(db_session, iri) <= 1, iri


# ---------------------------------------------------------------------------
# (b) One definition changed -> exactly one new version.
# ---------------------------------------------------------------------------


class TestSingleConceptModified:
    def test_one_change_one_new_version(self, semantic_models_manager, db_session):
        mgr = semantic_models_manager
        name = _unique_name()
        _seed(mgr, name, GLOSSARY_V1)
        ctx = _context(name)

        summary = mgr.apply_upload_as_versioning_event(
            ctx, _parse(GLOSSARY_REVENUE_EDITED), actor="tester"
        )
        assert summary["modified"] == 1, summary
        assert summary["new"] == 0, summary
        assert summary["removed"] == 0, summary

        # Only Revenue advanced to v2; the others did not get a v2.
        assert concept_versions_repo.max_version(db_session, REVENUE) == 2
        assert concept_versions_repo.max_version(db_session, CUSTOMER) <= 1
        assert concept_versions_repo.max_version(db_session, MARGIN) <= 1

        # The current definition is the edited one; the frozen v1 keeps the old.
        current = mgr.get_concept(REVENUE)
        assert "net of returns" in (current.get("comment") or "")
        v1 = mgr.get_concept_version_detail(REVENUE, 1)
        assert v1 is not None
        assert "net of returns" not in (v1.get("definition") or "")


# ---------------------------------------------------------------------------
# (c) New concept -> v1.
# ---------------------------------------------------------------------------


class TestNewConcept:
    def test_added_concept_appears_as_v1(self, semantic_models_manager, db_session):
        mgr = semantic_models_manager
        name = _unique_name()
        _seed(mgr, name, GLOSSARY_V1)
        ctx = _context(name)

        summary = mgr.apply_upload_as_versioning_event(
            ctx, _parse(GLOSSARY_PLUS_NEW), actor="tester"
        )
        assert summary["new"] == 1, summary
        assert summary["modified"] == 0, summary
        assert summary["removed"] == 0, summary

        assert concept_versions_repo.max_version(db_session, CHURN) == 1
        churn = mgr.get_concept(CHURN)
        assert churn is not None
        assert (churn.get("label") or "") == "Churn"


# ---------------------------------------------------------------------------
# (d) Removed but referenced -> deprecated, still resolvable, ref survives.
# ---------------------------------------------------------------------------


class TestRemovedReferenced:
    def test_removed_referenced_is_deprecated_not_deleted(
        self, semantic_models_manager, db_session
    ):
        from src.repositories.semantic_links_repository import entity_semantic_links_repo

        mgr = semantic_models_manager
        name = _unique_name()
        _seed(mgr, name, GLOSSARY_V1)
        ctx = _context(name)

        # Create a real UC reference to Margin.
        entity_semantic_links_repo.create(
            db_session,
            obj_in={
                "entity_id": f"main.e2e.tbl_{uuid.uuid4().hex[:6]}",
                "entity_type": "uc_table",
                "iri": MARGIN,
            },
        )
        db_session.commit()
        assert entity_semantic_links_repo.count_for_iri(db_session, MARGIN) > 0

        summary = mgr.apply_upload_as_versioning_event(
            ctx, _parse(GLOSSARY_MINUS_MARGIN), actor="tester"
        )
        assert summary["removed"] == 1, summary

        # Margin is deprecated, NOT hard-deleted: still resolvable.
        margin = mgr.get_concept(MARGIN)
        assert margin is not None, "removed concept must remain resolvable (tombstone)"
        assert margin.get("status") == "deprecated"

        # The reference survives (deprecate must not touch links).
        assert entity_semantic_links_repo.count_for_iri(db_session, MARGIN) > 0


# ---------------------------------------------------------------------------
# (e) Removed and unreferenced -> deprecated tombstone, no hard delete.
# ---------------------------------------------------------------------------


class TestRemovedUnreferenced:
    def test_removed_unreferenced_is_deprecated_tombstone(
        self, semantic_models_manager, db_session
    ):
        mgr = semantic_models_manager
        name = _unique_name()
        _seed(mgr, name, GLOSSARY_V1)
        ctx = _context(name)

        assert mgr.reference_count(MARGIN) == 0

        summary = mgr.apply_upload_as_versioning_event(
            ctx, _parse(GLOSSARY_MINUS_MARGIN), actor="tester"
        )
        assert summary["removed"] == 1, summary

        # Deprecated tombstone, never hard-deleted: concept + triples remain.
        margin = mgr.get_concept(MARGIN)
        assert margin is not None
        assert margin.get("status") == "deprecated"
        assert rdf_triples_repo.list_by_subject(db_session, MARGIN), "triples must remain"


# ---------------------------------------------------------------------------
# (f) Mid-apply failure -> whole changeset rolls back (atomic).
# ---------------------------------------------------------------------------


class TestAtomicRollback:
    def test_mid_apply_failure_leaves_store_unchanged(
        self, semantic_models_manager, db_session, monkeypatch
    ):
        mgr = semantic_models_manager
        name = _unique_name()
        _seed(mgr, name, GLOSSARY_V1)
        ctx = _context(name)

        # Re-upload that edits Revenue (modified, applied first) AND removes
        # Margin (removed, applied later). Force the REMOVED step to blow up so
        # the earlier MODIFIED publish must roll back too.
        edited_minus_margin = _PREFIXES + """
ex:Customer a skos:Concept ;
    skos:prefLabel "Customer" ;
    skos:definition "A buyer of goods." .

ex:Revenue a skos:Concept ;
    skos:prefLabel "Revenue" ;
    skos:definition "Income, net of returns." .
"""

        def _boom(*_args, **_kwargs):
            raise RuntimeError("simulated mid-apply failure")

        monkeypatch.setattr(mgr, "deprecate_concept", _boom)

        with pytest.raises(RuntimeError):
            mgr.apply_upload_as_versioning_event(
                ctx, _parse(edited_minus_margin), actor="tester"
            )

        # Atomic rollback proof: the MODIFIED bucket (applied BEFORE the failing
        # REMOVED bucket) did NOT persist — Revenue never advanced to v2. The
        # whole changeset was rolled back, not left half-applied. (The DB is the
        # source of truth; we assert against it directly.)
        assert concept_versions_repo.max_version(db_session, REVENUE) <= 1
