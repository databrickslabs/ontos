"""Internal/system graphs must not leak into the RDF Sources list.

The `/api/semantic-models` route combines DB-backed models with computed
graph taxonomies. Internal named graphs (app entities, demo data, semantic
links, source-registry metadata, the rdflib default graph) are managed/computed
and have no uploadable file behind them, so surfacing them produces broken rows
whose Preview action 404s. This guards the route-level filter that strips them.
"""

import asyncio
from unittest.mock import MagicMock

from src.models.ontology import SemanticModel as SemanticModelOntology
from src.routes.semantic_models_routes import (
    INTERNAL_GRAPH_CONTEXTS,
    get_semantic_models,
)


def _call_endpoint(manager: MagicMock) -> dict:
    """Invoke the async route handler directly, bypassing FastAPI auth/DI."""
    return asyncio.run(get_semantic_models(manager=manager, _=True))


def test_internal_graphs_are_excluded_from_list() -> None:
    manager = MagicMock()
    # No DB-backed models in this scenario.
    manager.list.return_value = []
    # Computed taxonomies include internal graphs plus one real file taxonomy.
    manager.get_taxonomies.return_value = [
        SemanticModelOntology(name="urn:app-entities", source_type="external"),
        SemanticModelOntology(name="urn:demo", source_type="external"),
        SemanticModelOntology(name="urn:semantic-links", source_type="external"),
        SemanticModelOntology(name="urn:meta:sources", source_type="external"),
        SemanticModelOntology(name="foo", source_type="file", format="ttl"),
    ]
    manager.bundled_taxonomy_file_size_bytes.return_value = 123

    payload = _call_endpoint(manager)

    names = {m["name"] for m in payload["semantic_models"]}
    assert names == {"foo"}
    assert not (names & INTERNAL_GRAPH_CONTEXTS)


def test_internal_graph_contexts_cover_known_namespaces() -> None:
    for key in (
        "urn:meta:sources",
        "urn:semantic-links",
        "urn:x-rdflib:default",
        "urn:app-entities",
        "urn:demo",
    ):
        assert key in INTERNAL_GRAPH_CONTEXTS
