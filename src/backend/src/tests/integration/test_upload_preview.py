"""Integration tests for steward upload preview + confirm (P1-0).

A file re-upload no longer auto-applies. Instead ``preview_upload`` computes the
concept-level diff, stashes the incoming content, and applies NOTHING; the
steward later applies it via ``confirm_upload(preview_token)``, which runs the
EXISTING ``apply_upload_as_versioning_event`` primitive and consumes the stash.

These tests drive the real ``SemanticModelsManager`` on the shared test DB and
assert:
  - preview returns correct buckets + reference_count and applies NOTHING
    (concept versions unchanged after preview);
  - confirm(token) applies exactly what the preview described (modified→v2,
    new→v1, removed→deprecated);
  - a second confirm with the same token fails (stash is single-use);
  - an unknown token raises.

Fixtures are local, mirroring test_concept_diff_engine.py (no shared conftest).
"""
import uuid
from pathlib import Path

import pytest
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
# Fixtures — local, mirroring test_concept_diff_engine.py.
# ---------------------------------------------------------------------------


@pytest.fixture
def semantic_models_manager(db_session: Session, tmp_path: Path):
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
# Fixture ontologies + helpers (mirrors test_concept_diff_engine.py).
# ---------------------------------------------------------------------------

_PREFIXES = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <http://example.org/onto#> .
"""

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

# Revenue edited (modified), Churn added (new), Margin removed (removed).
GLOSSARY_MIXED = _PREFIXES + """
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
    return f"preview_{uuid.uuid4().hex[:8]}.ttl"


# ---------------------------------------------------------------------------
# (a) preview returns correct buckets + reference_count and applies NOTHING.
# ---------------------------------------------------------------------------


class TestPreviewAppliesNothing:
    def test_preview_buckets_and_no_apply(self, semantic_models_manager, db_session):
        from src.repositories.semantic_links_repository import entity_semantic_links_repo

        mgr = semantic_models_manager
        name = _unique_name()
        _seed(mgr, name, GLOSSARY_V1)
        ctx = _context(name)

        # A real UC reference to Margin so removed carries reference_count > 0.
        entity_semantic_links_repo.create(
            db_session,
            obj_in={
                "entity_id": f"main.e2e.tbl_{uuid.uuid4().hex[:6]}",
                "entity_type": "uc_table",
                "iri": MARGIN,
            },
        )
        db_session.commit()

        preview = mgr.preview_upload(ctx, _parse(GLOSSARY_MIXED))

        assert preview["summary"]["modified"] == 1, preview
        assert preview["summary"]["new"] == 1, preview
        assert preview["summary"]["removed"] == 1, preview

        assert [e["iri"] for e in preview["modified"]] == [REVENUE]
        assert [e["iri"] for e in preview["new"]] == [CHURN]
        removed = {e["iri"]: e for e in preview["removed"]}
        assert MARGIN in removed
        assert removed[MARGIN]["reference_count"] >= 1

        assert preview["preview_token"]

        # Applies NOTHING: no concept advanced past v1, Margin not deprecated,
        # Churn does not exist.
        assert concept_versions_repo.max_version(db_session, REVENUE) <= 1
        assert concept_versions_repo.max_version(db_session, CUSTOMER) <= 1
        assert concept_versions_repo.max_version(db_session, MARGIN) <= 1
        assert mgr.get_concept(CHURN) is None
        margin = mgr.get_concept(MARGIN)
        assert margin is not None
        assert margin.get("status") != "deprecated"


# ---------------------------------------------------------------------------
# (b) confirm(token) applies exactly what the preview described.
# ---------------------------------------------------------------------------


class TestConfirmApplies:
    def test_confirm_applies_diff(self, semantic_models_manager, db_session):
        mgr = semantic_models_manager
        name = _unique_name()
        _seed(mgr, name, GLOSSARY_V1)
        ctx = _context(name)

        preview = mgr.preview_upload(ctx, _parse(GLOSSARY_MIXED))
        token = preview["preview_token"]

        summary = mgr.confirm_upload(token, actor="tester")
        assert summary["modified"] == 1, summary
        assert summary["new"] == 1, summary
        assert summary["removed"] == 1, summary

        # modified -> v2
        assert concept_versions_repo.max_version(db_session, REVENUE) == 2
        current = mgr.get_concept(REVENUE)
        assert "net of returns" in (current.get("comment") or current.get("definition") or "")
        # new -> v1
        assert concept_versions_repo.max_version(db_session, CHURN) == 1
        churn = mgr.get_concept(CHURN)
        assert churn is not None
        assert (churn.get("label") or "") == "Churn"
        # removed -> deprecated (tombstone, still resolvable)
        margin = mgr.get_concept(MARGIN)
        assert margin is not None
        assert margin.get("status") == "deprecated"


# ---------------------------------------------------------------------------
# (c) a second confirm with the same token fails (single-use stash).
# ---------------------------------------------------------------------------


class TestTokenSingleUse:
    def test_second_confirm_fails(self, semantic_models_manager, db_session):
        mgr = semantic_models_manager
        name = _unique_name()
        _seed(mgr, name, GLOSSARY_V1)
        ctx = _context(name)

        preview = mgr.preview_upload(ctx, _parse(GLOSSARY_MIXED))
        token = preview["preview_token"]

        mgr.confirm_upload(token, actor="tester")

        with pytest.raises(ValueError):
            mgr.confirm_upload(token, actor="tester")


# ---------------------------------------------------------------------------
# (d) unknown token raises.
# ---------------------------------------------------------------------------


class TestUnknownToken:
    def test_unknown_token_raises(self, semantic_models_manager):
        mgr = semantic_models_manager
        with pytest.raises(ValueError):
            mgr.confirm_upload(str(uuid.uuid4()), actor="tester")
