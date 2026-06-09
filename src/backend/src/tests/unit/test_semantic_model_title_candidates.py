"""Unit tests for RDF source title candidate extraction and auto-pick."""

import pytest
from rdflib import Graph, Literal, RDF, RDFS, URIRef
from rdflib.namespace import OWL, SKOS

from src.utils.semantic_model_title_candidates import (
    best_display_title_from_graph,
    collect_title_candidates_from_graph,
    extract_title_candidates,
    humanize_rdf_filename,
    pick_auto_display_name,
)


TTL_ONTOLOGY = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.org/onto#> .

ex:MyOnto a owl:Ontology ;
    rdfs:label "My Ontology Title"@en .
"""


TTL_SCHEME = """
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.org/vocab#> .

ex:scheme a skos:ConceptScheme ;
    skos:prefLabel "Taxonomy One"@en .
"""


def test_extract_owl_ontology_label():
    cands = extract_title_candidates(TTL_ONTOLOGY, "skos")
    assert len(cands) >= 1
    assert any(c["text"] == "My Ontology Title" and c["kind"] == "owl:Ontology" for c in cands)


def test_extract_skos_concept_scheme():
    cands = extract_title_candidates(TTL_SCHEME, "skos")
    assert len(cands) >= 1
    assert any(c["text"] == "Taxonomy One" for c in cands)


def test_pick_auto_single_distinct_text():
    cands = [{"iri": "a", "kind": "owl:Ontology", "text": "Only One", "lang": "en"}]
    assert pick_auto_display_name(cands) == "Only One"


def test_pick_auto_prefers_owl_when_multiple_texts():
    cands = [
        {"iri": "x", "kind": "owl:Ontology", "text": "Onto Title"},
        {"iri": "y", "kind": "skos:ConceptScheme", "text": "Other"},
    ]
    assert pick_auto_display_name(cands) == "Onto Title"


@pytest.mark.parametrize("empty", ["", "   "])
def test_extract_empty_content(empty):
    assert extract_title_candidates(empty, "skos") == []


def test_extract_none_content():
    assert extract_title_candidates(None, "skos") == []


def test_collect_title_candidates_empty_graph():
    assert collect_title_candidates_from_graph(Graph()) == []


def test_best_display_title_from_graph_empty():
    assert best_display_title_from_graph(Graph()) is None


def test_collect_and_best_from_in_memory_owl_ontology():
    g = Graph()
    onto = URIRef("http://example.org/onto#root")
    g.add((onto, RDF.type, OWL.Ontology))
    g.add((onto, RDFS.label, Literal("Bundled Onto Title", lang="en")))
    cands = collect_title_candidates_from_graph(g)
    assert any(c["text"] == "Bundled Onto Title" and c["kind"] == "owl:Ontology" for c in cands)
    assert best_display_title_from_graph(g) == "Bundled Onto Title"


def test_collect_and_best_from_in_memory_skos_scheme():
    g = Graph()
    scheme = URIRef("http://example.org/vocab#scheme")
    g.add((scheme, RDF.type, SKOS.ConceptScheme))
    g.add((scheme, SKOS.prefLabel, Literal("Industry Codes", lang="en")))
    cands = collect_title_candidates_from_graph(g)
    assert any(c["text"] == "Industry Codes" for c in cands)
    assert best_display_title_from_graph(g) == "Industry Codes"


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("pizza.owl", "Pizza"),
        ("PIZZA.OWL", "Pizza"),
        ("my_ontology.ttl", "My Ontology"),
        ("my-ontology-v2.ttl", "My Ontology V2"),
        ("databricks_ontology.ttl", "Databricks Ontology"),
        ("fibo-quick-fix.rdf", "FIBO Quick Fix"),
        ("gs1_taxonomy.skos", "GS1 Taxonomy"),
        ("Schema.org.jsonld", "Schema Org"),
        ("foo.bar.baz.owl", "Foo Bar Baz"),
        ("/tmp/uploads/some_file.rdfs", "Some File"),
        ("nodot", "Nodot"),
        ("ALLCAPS.TTL", "Allcaps"),
        ("abc.TTL", "Abc"),
    ],
)
def test_humanize_rdf_filename(filename, expected):
    assert humanize_rdf_filename(filename) == expected


def test_humanize_rdf_filename_empty():
    assert humanize_rdf_filename("") == ""


def test_humanize_rdf_filename_only_extension():
    # Stripping everything would leave an empty name; helper should return
    # the original input unchanged so callers can fall back gracefully.
    assert humanize_rdf_filename(".ttl") == ".ttl"


def test_graph_title_matches_string_parse_path():
    g = Graph()
    g.parse(data=TTL_ONTOLOGY, format="turtle")
    assert collect_title_candidates_from_graph(g) == extract_title_candidates(TTL_ONTOLOGY, "skos")
    assert best_display_title_from_graph(g) == pick_auto_display_name(
        extract_title_candidates(TTL_ONTOLOGY, "skos")
    )
