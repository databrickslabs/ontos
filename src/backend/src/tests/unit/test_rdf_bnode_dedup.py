"""Regression tests for blank-node import idempotency.

Blank nodes in imported ontologies (OWL restrictions, SHACL shapes, rdf:Lists)
used to be skolemised with rdflib's RANDOM per-parse identifier, so re-importing
the same content produced brand-new URIs that never matched the uq_rdf_triple
constraint — every re-import duplicated the triples without bound (the reported
40k-50k bloat). `_import_graph_to_db` now canonicalises blank nodes (RGDA1)
before persisting, so identical content yields identical rows and re-imports
are true no-ops.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from rdflib import Graph

import src.repositories.rdf_triples_repository as rdf_repo_mod
from src.controller.semantic_models_manager import SemanticModelsManager
from src.repositories.rdf_triples_repository import rdf_triples_repo


# Ontology fragment with nested blank nodes: an OWL restriction and two SHACL
# property shapes. These are exactly the constructs that bloated in production.
BNODE_TTL = """
@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix sh: <http://www.w3.org/ns/shacl#> .

ex:Person a owl:Class ;
    rdfs:subClassOf [ a owl:Restriction ;
        owl:onProperty ex:hasParent ;
        owl:someValuesFrom ex:Person ] .

ex:PersonShape a sh:NodeShape ;
    sh:property [ sh:path ex:name ; sh:minCount 1 ] ,
                [ sh:path ex:age ; sh:datatype ex:int ] .
"""


@pytest.fixture
def manager_no_rebuild(db_session, tmp_path):
    with patch.object(SemanticModelsManager, "rebuild_graph_from_enabled", lambda self: None):
        yield SemanticModelsManager(db_session, data_dir=tmp_path)


def _import(manager: SemanticModelsManager, context: str) -> int:
    g = Graph()
    g.parse(data=BNODE_TTL, format="turtle")
    return manager._import_graph_to_db(
        graph=g,
        context_name=context,
        source_type="upload",
        source_identifier="bnode-test.ttl",
        created_by="tester",
    )


def test_reimport_of_bnode_ontology_is_idempotent(manager_no_rebuild):
    """Re-importing identical blank-node content inserts nothing the 2nd time."""
    context = "urn:test:bnode-idempotent"

    first = _import(manager_no_rebuild, context)
    assert first > 0, "first import should insert all triples"

    total_after_first = rdf_triples_repo.count_by_context(manager_no_rebuild._db, context)

    second = _import(manager_no_rebuild, context)
    third = _import(manager_no_rebuild, context)

    assert second == 0, "second import must be a no-op (canonical bnode ids)"
    assert third == 0, "third import must be a no-op"

    total_after_third = rdf_triples_repo.count_by_context(manager_no_rebuild._db, context)
    assert total_after_third == total_after_first, "row count must not grow on re-import"


def test_skolemized_bnode_uris_are_stable_across_parses(manager_no_rebuild):
    """The skolem URIs persisted for identical content are identical across imports."""
    ctx_a = "urn:test:bnode-stable-a"
    ctx_b = "urn:test:bnode-stable-b"

    _import(manager_no_rebuild, ctx_a)
    _import(manager_no_rebuild, ctx_b)

    def bnode_local_ids(context: str) -> set[str]:
        rows = rdf_triples_repo.list_by_context(manager_no_rebuild._db, context)
        ids: set[str] = set()
        prefix = f"urn:ontos:bnode:{context}:"
        for r in rows:
            for value in (r.subject_uri, r.object_value):
                if value.startswith(prefix):
                    ids.add(value[len(prefix):])
        return ids

    ids_a = bnode_local_ids(ctx_a)
    ids_b = bnode_local_ids(ctx_b)

    assert ids_a, "expected skolemized blank nodes to be persisted"
    # Same content parsed twice must yield the same canonical bnode local-ids.
    assert ids_a == ids_b


class TestBloatDiagnostics:
    """The threshold-gated forensic snapshot for the unexplained triple bloat."""

    @pytest.fixture(autouse=True)
    def _reset_throttle(self):
        # Each test controls threshold/interval explicitly; clear the module
        # throttle so ordering between tests doesn't matter.
        rdf_repo_mod._diag_last_run_monotonic = 0.0
        yield
        rdf_repo_mod._diag_last_run_monotonic = 0.0

    def _seed(self, db, n: int) -> None:
        triples = [
            {
                "subject_uri": f"urn:test:s{i}",
                "predicate_uri": "urn:test:p",
                "object_value": f"urn:test:o{i}",
                "object_is_uri": True,
                "context_name": "urn:test:diag",
            }
            for i in range(n)
        ]
        rdf_triples_repo.add_triples_bulk(db, triples)

    def test_no_op_below_threshold(self, db_session, monkeypatch):
        # Very high threshold so the (small) test table is always under it,
        # regardless of rows other tests left in the session-scoped DB.
        monkeypatch.setattr(rdf_repo_mod, "_DIAG_THRESHOLD", 10_000_000)
        monkeypatch.setattr(rdf_repo_mod, "_DIAG_INTERVAL_S", 0)
        self._seed(db_session, 10)
        rdf_repo_mod._diag_last_run_monotonic = 0.0

        with patch.object(rdf_repo_mod.logger, "warning") as warn:
            rdf_triples_repo.maybe_log_bloat_diagnostics(db_session, trigger="test")
        warn.assert_not_called()

    def test_disabled_when_threshold_zero(self, db_session, monkeypatch):
        monkeypatch.setattr(rdf_repo_mod, "_DIAG_THRESHOLD", 0)  # disabled
        monkeypatch.setattr(rdf_repo_mod, "_DIAG_INTERVAL_S", 0)
        self._seed(db_session, 20)

        with patch.object(rdf_repo_mod.logger, "warning") as warn:
            rdf_triples_repo.maybe_log_bloat_diagnostics(db_session, trigger="test")
        warn.assert_not_called()

    def test_fires_above_threshold_then_throttles(self, db_session, monkeypatch):
        monkeypatch.setattr(rdf_repo_mod, "_DIAG_THRESHOLD", 5)
        monkeypatch.setattr(rdf_repo_mod, "_DIAG_INTERVAL_S", 300)  # long throttle
        self._seed(db_session, 20)  # above 5
        # add_triples_bulk already ran the diagnostic during seeding and armed
        # the throttle; reset so this test controls the timing explicitly.
        rdf_repo_mod._diag_last_run_monotonic = 0.0

        with patch.object(rdf_repo_mod.logger, "warning") as warn:
            rdf_triples_repo.maybe_log_bloat_diagnostics(db_session, trigger="first")
            first_calls = warn.call_count
            # Second call within the throttle window must NOT re-run the snapshot.
            rdf_triples_repo.maybe_log_bloat_diagnostics(db_session, trigger="second")
            second_calls = warn.call_count

        assert first_calls > 0, "snapshot must emit warnings above threshold"
        assert second_calls == first_calls, "throttle must suppress the immediate re-run"
