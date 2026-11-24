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
    # prefLabel and rdfs:label are kept in separate maps
    assert sub["displayLabels"] == {
        "prefLabel": {"pt": "Filho"},
        "rdfsLabel": {"pt": "Child rdfs", "en": "Child rdfs en"},
    }
    assert sub["predicateLabels"] == {"prefLabel": {}, "rdfsLabel": {}}
    rel = by_pred[EX + "contains"]
    assert rel["predicateLabels"] == {
        "prefLabel": {},
        "rdfsLabel": {"en": "contains substance"},
    }


def test_neighbors_literal_has_no_labels(manager):
    manager._graph.add((URIRef(EX + "Root"), SKOS.definition, Literal("text")))
    items = manager.neighbors(EX + "Root")
    lit = next(i for i in items if i["predicate"] == str(SKOS.definition))
    assert lit["displayLabels"] == {"prefLabel": {}, "rdfsLabel": {}}


def test_collect_label_maps_is_deterministic_per_language():
    from src.controller.semantic_models_manager import collect_label_maps

    node = URIRef(EX + "Thing")
    for order in (("b", "a", "c"), ("c", "b", "a")):
        g = Graph()
        for v in order:
            g.add((node, SKOS.prefLabel, Literal(v, lang="en")))
        assert collect_label_maps(g, node)["prefLabel"] == {"en": "a"}


def test_concept_details_keep_pref_and_rdfs_labels_apart(manager):
    from rdflib import ConjunctiveGraph

    cg = ConjunctiveGraph()
    ctx = cg.get_context(URIRef("urn:ctx:test"))
    c = URIRef(EX + "Thing")
    ctx.add((c, RDF.type, URIRef("http://www.w3.org/2002/07/owl#Class")))
    ctx.add((c, SKOS.prefLabel, Literal("PrefEN", lang="en")))
    ctx.add((c, RDFS.label, Literal("RdfsPT", lang="pt")))
    manager._graph = cg
    concept = manager.get_concept_details(EX + "Thing")
    assert concept.label_maps == {"prefLabel": {"en": "PrefEN"}, "rdfsLabel": {"pt": "RdfsPT"}}
    assert concept.labels == {"en": "PrefEN", "pt": "RdfsPT"}
