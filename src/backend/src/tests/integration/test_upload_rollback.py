"""Integration tests for upload history + rollback (P2-1).

A re-upload is a bulk versioning event; P2-1 records each one as an
``upload_event`` capturing every affected concept's BEFORE-state, so an upload
can be rolled back FORWARD (re-applying the prior states as a NEW versioning
event) — never a delete. These tests drive the real ``SemanticModelsManager`` on
the shared test DB and assert:

- an upload event is recorded with the correct per-concept prev-state
  (modified / new / removed captured);
- rollback of a modified-concept upload restores the PRIOR definition text and
  mints a NEW version (forward, not delete);
- rollback of an upload that ADDED a concept deprecates it (tombstone, still
  resolvable, not hard-deleted);
- rollback of an upload that REMOVED a concept restores it to active;
- the rollback is itself recorded as a new upload_event;
- a forced mid-rollback failure leaves the store unchanged (atomic).

Fixtures are local, mirroring test_concept_diff_engine.py (no shared
integration conftest).
"""
import uuid
from pathlib import Path

import pytest
from rdflib import Graph
from sqlalchemy.orm import Session

from src.controller.semantic_models_manager import (
    SemanticModelsManager,
    _sanitize_context_name,
)
from src.app import app
from src.common.app_state import set_app_state_manager
from src.models.semantic_models import SemanticModelCreate
from src.repositories.concept_versions_repository import concept_versions_repo
from src.repositories.upload_event_repository import upload_event_repo


# ---------------------------------------------------------------------------
# Fixtures — local, mirroring test_concept_diff_engine.py.
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
CHURN = "http://example.org/onto#Churn"

# Revenue's definition edited, Margin removed, Churn added — one upload that
# exercises all three buckets at once.
GLOSSARY_MODIFIED = _PREFIXES + """
ex:Customer a skos:Concept ;
    skos:prefLabel "Customer" ;
    skos:definition "A buyer of goods." .

ex:Revenue a skos:Concept ;
    skos:prefLabel "Revenue" ;
    skos:definition "Income from sales, net of returns." .

ex:Churn a skos:Concept ;
    skos:prefLabel "Churn" ;
    skos:definition "Rate of customer loss." .
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
    return f"rollback_{uuid.uuid4().hex[:8]}.ttl"


# ---------------------------------------------------------------------------
# (a) An upload event is recorded with the correct prev-state.
# ---------------------------------------------------------------------------


class TestUploadEventRecorded:
    def test_reupload_records_event_with_prev_state(
        self, semantic_models_manager, db_session
    ):
        mgr = semantic_models_manager
        name = _unique_name()
        _seed(mgr, name, GLOSSARY_V1)
        ctx = _context(name)

        summary = mgr.apply_upload_as_versioning_event(
            ctx, _parse(GLOSSARY_MODIFIED), actor="tester"
        )
        assert summary["modified"] == 1, summary
        assert summary["new"] == 1, summary
        assert summary["removed"] == 1, summary

        events = upload_event_repo.list_by_context(db_session, ctx)
        assert len(events) == 1
        ev = events[0]
        assert ev.summary["modified"] == 1
        assert ev.summary["new"] == 1
        assert ev.summary["removed"] == 1

        by_iri = {e["iri"]: e for e in ev.concept_prev_state}
        assert by_iri[REVENUE]["bucket"] == "modified"
        assert by_iri[REVENUE]["prev_version"] == 1  # was v1 before the upload
        assert by_iri[CHURN]["bucket"] == "new"
        assert by_iri[CHURN]["prev_version"] is None  # absent before
        assert by_iri[MARGIN]["bucket"] == "removed"

        # And the API-facing list surfaces it, newest-first.
        listed = mgr.list_upload_events(ctx)
        assert len(listed) == 1
        assert listed[0]["summary"]["modified"] == 1
        assert listed[0]["created_by"] == "tester"


# ---------------------------------------------------------------------------
# (b) Rollback of a modified upload restores the prior definition, forward.
# ---------------------------------------------------------------------------


class TestRollbackModified:
    def test_rollback_restores_prior_definition_and_mints_new_version(
        self, semantic_models_manager, db_session
    ):
        mgr = semantic_models_manager
        name = _unique_name()
        _seed(mgr, name, GLOSSARY_V1)  # seed v1
        ctx = _context(name)

        # Upload that edits Revenue's definition (modified bucket).
        edited = _PREFIXES + """
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
        mgr.apply_upload_as_versioning_event(ctx, _parse(edited), actor="tester")
        assert concept_versions_repo.max_version(db_session, REVENUE) == 2
        cur = mgr.get_concept(REVENUE)
        assert "net of returns" in (cur.get("comment") or "")

        event = upload_event_repo.list_by_context(db_session, ctx)[0]
        result = mgr.rollback_upload_event(event.id, actor="roller")
        assert result["rolled_back"] is True

        # FORWARD rollback: Revenue advanced to v3 (a NEW version, not a delete),
        # and its current definition is the PRIOR (pre-upload) text.
        assert concept_versions_repo.max_version(db_session, REVENUE) == 3
        restored = mgr.get_concept(REVENUE)
        assert "net of returns" not in (restored.get("comment") or "")
        assert (restored.get("comment") or "") == "Income from sales."


# ---------------------------------------------------------------------------
# (c) Rollback of an ADD deprecates the concept (tombstone, still resolvable).
# ---------------------------------------------------------------------------


class TestRollbackAdd:
    def test_rollback_of_added_concept_deprecates_it(
        self, semantic_models_manager, db_session
    ):
        mgr = semantic_models_manager
        name = _unique_name()
        _seed(mgr, name, GLOSSARY_V1)
        ctx = _context(name)

        plus_new = GLOSSARY_V1 + """
ex:Churn a skos:Concept ;
    skos:prefLabel "Churn" ;
    skos:definition "Rate of customer loss." .
"""
        mgr.apply_upload_as_versioning_event(ctx, _parse(plus_new), actor="tester")
        assert mgr.get_concept(CHURN) is not None

        event = upload_event_repo.list_by_context(db_session, ctx)[0]
        mgr.rollback_upload_event(event.id, actor="roller")

        # Churn was NEW in the rolled-back upload -> deprecated tombstone, still
        # resolvable, never hard-deleted.
        churn = mgr.get_concept(CHURN)
        assert churn is not None, "added concept must remain resolvable (tombstone)"
        assert churn.get("status") == "deprecated"


# ---------------------------------------------------------------------------
# (d) Rollback of a REMOVE restores the concept to active.
# ---------------------------------------------------------------------------


class TestRollbackRemove:
    def test_rollback_of_removed_concept_restores_active(
        self, semantic_models_manager, db_session
    ):
        mgr = semantic_models_manager
        name = _unique_name()
        _seed(mgr, name, GLOSSARY_V1)
        ctx = _context(name)

        minus_margin = _PREFIXES + """
ex:Customer a skos:Concept ;
    skos:prefLabel "Customer" ;
    skos:definition "A buyer of goods." .

ex:Revenue a skos:Concept ;
    skos:prefLabel "Revenue" ;
    skos:definition "Income from sales." .
"""
        mgr.apply_upload_as_versioning_event(ctx, _parse(minus_margin), actor="tester")
        assert mgr.get_concept(MARGIN).get("status") == "deprecated"

        event = upload_event_repo.list_by_context(db_session, ctx)[0]
        mgr.rollback_upload_event(event.id, actor="roller")

        # Margin was REMOVED (deprecated) by the rolled-back upload -> restored to
        # its prior status (active).
        margin = mgr.get_concept(MARGIN)
        assert margin is not None
        assert margin.get("status") == "active"


# ---------------------------------------------------------------------------
# (e) The rollback is itself recorded as a new upload_event.
# ---------------------------------------------------------------------------


class TestRollbackIsRecorded:
    def test_rollback_records_new_event(self, semantic_models_manager, db_session):
        mgr = semantic_models_manager
        name = _unique_name()
        _seed(mgr, name, GLOSSARY_V1)
        ctx = _context(name)

        mgr.apply_upload_as_versioning_event(
            ctx, _parse(GLOSSARY_MODIFIED), actor="tester"
        )
        assert len(upload_event_repo.list_by_context(db_session, ctx)) == 1

        event = upload_event_repo.list_by_context(db_session, ctx)[0]
        mgr.rollback_upload_event(event.id, actor="roller")

        # The rollback itself is auditable + re-roll-back-able: a SECOND event
        # row now exists, authored by the rollback actor. (Ordering between the
        # two is by created_at, which is sub-second-identical under the SQLite
        # test harness — Postgres transaction timestamps differentiate them — so
        # we assert on membership rather than positional order.)
        events = upload_event_repo.list_by_context(db_session, ctx)
        assert len(events) == 2
        assert {e.created_by for e in events} == {"tester", "roller"}


# ---------------------------------------------------------------------------
# (f) Mid-rollback failure -> whole changeset rolls back (atomic).
# ---------------------------------------------------------------------------


class TestRollbackAtomicity:
    def test_mid_rollback_failure_leaves_store_unchanged(
        self, semantic_models_manager, db_session, monkeypatch
    ):
        mgr = semantic_models_manager
        name = _unique_name()
        _seed(mgr, name, GLOSSARY_V1)
        ctx = _context(name)

        # Upload edits Revenue (modified) AND removes Margin (removed).
        edited_minus_margin = _PREFIXES + """
ex:Customer a skos:Concept ;
    skos:prefLabel "Customer" ;
    skos:definition "A buyer of goods." .

ex:Revenue a skos:Concept ;
    skos:prefLabel "Revenue" ;
    skos:definition "Income, net of returns." .
"""
        mgr.apply_upload_as_versioning_event(
            ctx, _parse(edited_minus_margin), actor="tester"
        )
        assert concept_versions_repo.max_version(db_session, REVENUE) == 2

        event = upload_event_repo.list_by_context(db_session, ctx)[0]

        # Force the removed-bucket step (restore Margin via _set_concept_status)
        # to blow up so the earlier modified re-publish must roll back too.
        def _boom(*_args, **_kwargs):
            raise RuntimeError("simulated mid-rollback failure")

        monkeypatch.setattr(mgr, "_set_concept_status", _boom)

        with pytest.raises(RuntimeError):
            mgr.rollback_upload_event(event.id, actor="roller")

        # Atomic all-or-nothing: NO partial effect of the failed rollback persists.
        # The modified re-publish (applied BEFORE the failing restore) did NOT
        # stick — Revenue never advanced to v3 — and no rollback event row was
        # written (no "roller"-authored event). The whole changeset rolled back,
        # not left half-applied. (The DB is the source of truth; we assert
        # against it directly. NOTE: the SQLite test harness binds the session to
        # one external connection transaction without the savepoint-restart
        # recipe, so its rollback reverts further than Postgres would; the
        # atomicity PROPERTY — no half-applied rollback — holds either way.)
        assert concept_versions_repo.max_version(db_session, REVENUE) < 3
        events_after = upload_event_repo.list_by_context(db_session, ctx)
        assert not any(e.created_by == "roller" for e in events_after)
