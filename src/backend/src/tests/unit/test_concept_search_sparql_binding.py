"""Concept and property search treat the search text as a value, never as SPARQL.

``search_concepts`` and ``search_properties`` put the text inside the query's
string literal, so a quote, a backslash or a newline broke the query (no
results) and a crafted text could rewrite the FILTER (every class returned).
"""
from rdflib import ConjunctiveGraph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS

import pytest

from src.controller.semantic_models_manager import SemanticModelsManager

EX = 'http://example.org/onto#'
INJECTION = 'zzz")) || true || CONTAINS("", ("'


@pytest.fixture
def manager():
    graph = ConjunctiveGraph()
    classes = {
        'Customer': 'Customer "VIP"',
        'Brace': 'Set {a}',
        'Path': 'C:\\data\\raw',
        'Multi': 'line one\nline two',
        'Order': 'Order',
    }
    for name, label in classes.items():
        graph.add((URIRef(EX + name), RDF.type, OWL.Class))
        graph.add((URIRef(EX + name), RDFS.label, Literal(label)))
    graph.add((URIRef(EX + 'hasNote'), RDF.type, OWL.DatatypeProperty))
    graph.add((URIRef(EX + 'hasNote'), RDFS.label, Literal('note "quoted"')))
    instance = SemanticModelsManager.__new__(SemanticModelsManager)
    instance._graph = graph
    return instance


def _values(results):
    return sorted(result['value'] for result in results)


@pytest.mark.parametrize('text, expected', [
    ('"VIP"', 'Customer'),
    ('{a}', 'Brace'),
    ('a}', 'Brace'),
    ('\\data\\', 'Path'),
    ('one\nline', 'Multi'),
])
def test_special_characters_are_matched_literally(manager, text, expected):
    assert _values(manager.search_concepts(text)) == [EX + expected]


def test_an_injection_payload_does_not_rewrite_the_filter(manager):
    assert manager.search_concepts(INJECTION) == []
    assert manager.search_properties(INJECTION) == []


def test_plain_and_empty_searches_still_work(manager):
    assert _values(manager.search_concepts('order')) == [EX + 'Order']
    assert len(manager.search_concepts('')) == 5
    assert len(manager.search_concepts('', limit=2)) == 2


def test_property_search_matches_quotes_literally(manager):
    assert _values(manager.search_properties('"quoted"')) == [EX + 'hasNote']
