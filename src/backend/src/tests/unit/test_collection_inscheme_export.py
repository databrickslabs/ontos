"""ONT-ONTO-005: concept scheme membership in the collection export.

A concept added to a collection must be linked to a skos:ConceptScheme via
skos:inScheme, and the collection's Turtle/RDF-XML export must declare that
ConceptScheme. PR #526 only enabled the collection picker in the Create dialog;
it did not emit the membership semantics, so the export still produced bare
skos:Concept resources with no scheme. These tests pin the fixed behavior.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from rdflib import Graph, URIRef
from rdflib.namespace import RDF, SKOS

from src.controller.semantic_models_manager import SemanticModelsManager


@pytest.fixture
def manager(db_session):
    with patch.object(SemanticModelsManager, "rebuild_graph_from_enabled", lambda self: None):
        yield SemanticModelsManager(db_session, data_dir=Path("/tmp/ontos-test-inscheme"))


def _make_collection_with_concept(manager):
    collection = manager.create_collection(
        label="Risk Glossary",
        collection_type="glossary",
        created_by="tester@example.com",
    )
    coll_iri = collection["iri"]
    concept = manager.create_concept(
        collection_iri=coll_iri,
        label="Counterparty Risk",
        definition="Risk that a counterparty defaults.",
        created_by="tester@example.com",
    )
    return coll_iri, concept


def test_create_concept_persists_inscheme(manager):
    coll_iri, concept = _make_collection_with_concept(manager)
    concept_iri = concept["iri"]

    # The in-memory collection context carries the skos:inScheme triple.
    ctx = manager._graph.get_context(URIRef(coll_iri))
    assert (URIRef(concept_iri), SKOS.inScheme, URIRef(coll_iri)) in ctx


def test_turtle_export_declares_scheme_and_membership(manager):
    coll_iri, concept = _make_collection_with_concept(manager)
    concept_iri = concept["iri"]

    ttl = manager.export_collection_as_turtle(coll_iri)
    g = Graph()
    g.parse(data=ttl, format="turtle")

    # The collection IRI is declared as a ConceptScheme.
    assert (URIRef(coll_iri), RDF.type, SKOS.ConceptScheme) in g
    # The concept is linked to the scheme.
    assert (URIRef(concept_iri), SKOS.inScheme, URIRef(coll_iri)) in g
    # Sanity: there is at least one inScheme triple (regression guard).
    assert len(list(g.triples((None, SKOS.inScheme, None)))) >= 1


def test_rdfxml_export_declares_scheme_and_membership(manager):
    coll_iri, concept = _make_collection_with_concept(manager)
    concept_iri = concept["iri"]

    xml = manager.export_collection_as_rdfxml(coll_iri)
    g = Graph()
    g.parse(data=xml, format="xml")

    assert (URIRef(coll_iri), RDF.type, SKOS.ConceptScheme) in g
    assert (URIRef(concept_iri), SKOS.inScheme, URIRef(coll_iri)) in g
