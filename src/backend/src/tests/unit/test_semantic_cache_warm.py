"""Regression tests for semantic-models cache warming / persistence.

Two defects made every dashboard request recompute SPARQL over the whole graph
(the reported post-redeploy slowness):

1. ``on_models_changed`` rebuilt the caches (files + in-memory) and then
   immediately called ``_invalidate_cache()``, deleting exactly what it had just
   built. Any concept/link mutation therefore wiped every cache tier.
2. The read paths (``get_taxonomies`` / ``get_taxonomy_stats`` /
   ``get_grouped_concepts``) recomputed live on a miss but never repopulated the
   caches, so the miss recurred on every subsequent request.

These tests pin the fixed behaviour: mutations leave the caches warm, and a cold
read self-heals both cache tiers from the (always-fresh) singleton graph.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from rdflib import Graph

from src.controller.semantic_models_manager import SemanticModelsManager


# Minimal SKOS taxonomy so the compute paths return non-trivial data.
CONCEPT_TTL = """
@prefix ex: <http://example.org/gloss/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

ex:Customer a skos:Concept ; skos:prefLabel "Customer" .
ex:Order a skos:Concept ; skos:prefLabel "Order" .
"""


@pytest.fixture
def manager(db_session, tmp_path):
    """A manager whose graph is seeded directly (no DB rebuild)."""
    with patch.object(SemanticModelsManager, "rebuild_graph_from_enabled", lambda self: None):
        mgr = SemanticModelsManager(db_session, data_dir=tmp_path)
    # Seed a real graph context so _compute_* returns data.
    ctx = mgr._graph.get_context("urn:taxonomy:demo")
    g = Graph()
    g.parse(data=CONCEPT_TTL, format="turtle")
    for triple in g:
        ctx.add(triple)
    return mgr


def _cache_files(mgr) -> list[str]:
    cache_dir = mgr._data_dir / "cache"
    if not cache_dir.exists():
        return []
    return sorted(p.name for p in cache_dir.glob("*.json"))


def test_cold_read_warms_both_tiers(manager):
    """A cold stats read repopulates in-memory + file caches (defect #2)."""
    assert manager._cached_stats is None

    stats = manager.get_taxonomy_stats()
    assert stats is not None

    # In-memory tier warmed.
    assert manager._cached_stats is not None
    assert manager._cached_concepts is not None
    assert manager._cached_taxonomies is not None

    # Persistent tier written.
    assert "stats.json" in _cache_files(manager)
    assert "concepts_all.json" in _cache_files(manager)
    assert "taxonomies.json" in _cache_files(manager)


def test_second_read_hits_cache_no_recompute(manager):
    """After warming, subsequent reads must not recompute from the graph."""
    manager.get_grouped_concepts()  # warms
    assert manager._cached_concepts is not None

    # If a second read recomputed, it would call _build_persistent_caches_atomic
    # again. Assert it does NOT.
    with patch.object(
        manager, "_build_persistent_caches_atomic",
        side_effect=AssertionError("recomputed on warm cache"),
    ):
        grouped = manager.get_grouped_concepts()
    assert grouped  # still returns data from the warm cache


def test_on_models_changed_leaves_cache_warm(manager):
    """on_models_changed must NOT destroy the caches it rebuilt (defect #1).

    Here rebuild_graph_from_enabled is patched to warm the caches (mirroring the
    real rebuild's final _build_persistent_caches_atomic step). The regression is
    that on_models_changed used to null them afterwards.
    """
    def fake_rebuild(self):
        self._build_persistent_caches_atomic()

    with patch.object(SemanticModelsManager, "rebuild_graph_from_enabled", fake_rebuild):
        manager.on_models_changed()

    assert manager._cached_stats is not None, "on_models_changed destroyed the cache"
    assert manager._cached_concepts is not None
    assert manager._cached_taxonomies is not None
    assert "stats.json" in _cache_files(manager)


def test_invalidate_then_read_rewarms(manager):
    """Explicit invalidation (from incremental CRUD) self-heals on next read."""
    manager.get_taxonomy_stats()  # warm
    assert manager._cached_stats is not None

    manager._invalidate_cache()
    assert manager._cached_stats is None
    assert _cache_files(manager) == []  # files deleted

    # Next read must rewarm both tiers rather than recompute forever.
    stats = manager.get_taxonomy_stats()
    assert stats is not None
    assert manager._cached_stats is not None
    assert "stats.json" in _cache_files(manager)
