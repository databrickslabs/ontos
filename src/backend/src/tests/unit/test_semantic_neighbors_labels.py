"""SemanticModelsManager.neighbors: language-keyed labels for targets and predicates."""

from pathlib import Path
from unittest.mock import patch

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS, SKOS

from src.controller.semantic_models_manager import SemanticModelsManager

EX = "http://example.org/onto#"


@pytest.fixture
def manager(db_session):
    with patch.object(SemanticModelsManager, "rebuild_graph_from_enabled", lambda self: None):
        mgr = SemanticModelsManager(db_session, data_dir=Path("/tmp/ontos-test-semantic"))
    g = Graph()
    root, child, pred = URIRef(EX + "Root"), URIRef(EX + "Child"), URIRef(EX + "contains")
    g.add((child, RDFS.subClassOf, root))
    g.add((child, pred, root))
    g.add((child, SKOS.prefLabel, Literal("Filho", lang="pt")))
    g.add((child, RDFS.label, Literal("Child rdfs", lang="pt")))
    g.add((child, RDFS.label, Literal("Child rdfs en", lang="en")))
    g.add((pred, RDF.type, RDF.Property))
    g.add((pred, RDFS.label, Literal("contains substance", lang="en")))
    mgr._graph = g
    return mgr


def test_neighbors_carry_labels_for_target_and_predicate(manager):
    items = manager.neighbors(EX + "Root")
    by_pred = {i["predicate"]: i for i in items}
    sub = by_pred[str(RDFS.subClassOf)]
    assert sub["display"] == EX + "Child"
    # prefLabel wins over rdfs:label for the same language
    assert sub["displayLabels"] == {"pt": "Filho", "en": "Child rdfs en"}
    assert sub["predicateLabels"] == {}
    rel = by_pred[EX + "contains"]
    assert rel["predicateLabels"] == {"en": "contains substance"}


def test_neighbors_literal_has_no_labels(manager):
    manager._graph.add((URIRef(EX + "Root"), SKOS.definition, Literal("text")))
    items = manager.neighbors(EX + "Root")
    lit = next(i for i in items if i["predicate"] == str(SKOS.definition))
    assert lit["displayLabels"] == {}
