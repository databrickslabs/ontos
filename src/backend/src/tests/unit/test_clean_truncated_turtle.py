"""Tests for the truncated-Turtle cleanup helper.

LLM-generated Turtle is frequently cut off mid-statement (token-limit
truncation). Feeding such content to rdflib's notation3 parser raises an
``IndexError: string index out of range`` deep in ``path()``. The helper
trims the trailing incomplete fragment so the remainder parses cleanly.
"""
import pytest
from rdflib import Graph

from src.owl.owl_parser import clean_truncated_turtle


WELL_FORMED_TURTLE = """@prefix : <http://test.org/ontology#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

:Customer a owl:Class ;
    rdfs:label "Customer" .

:Order a owl:Class ;
    rdfs:label "Order" .
"""


def test_well_formed_turtle_is_unchanged():
    assert clean_truncated_turtle(WELL_FORMED_TURTLE) == WELL_FORMED_TURTLE


def test_empty_string_is_unchanged():
    assert clean_truncated_turtle("") == ""
    assert clean_truncated_turtle("   \n\n  ") == "   \n\n  "


def test_content_ending_with_bracket_is_unchanged():
    """Blank-node-list and collection terminators are valid endings."""
    content = WELL_FORMED_TURTLE + ":Foo a owl:Class ;\n    rdfs:subClassOf [ a owl:Restriction ]"
    # Note: ends with "]" -> treated as complete statement (will fail parse but cleanup is no-op).
    assert clean_truncated_turtle(content) == content


def test_content_ending_with_angle_bracket_is_unchanged():
    """RDF/XML closing tags end in ``>``; cleanup must not touch them."""
    content = "<?xml version=\"1.0\"?><rdf:RDF></rdf:RDF>"
    assert clean_truncated_turtle(content) == content


def test_truncated_trailing_dangling_triple_is_trimmed():
    truncated = WELL_FORMED_TURTLE + ":Partial a owl:Class ;\n    rdfs:label \"Par"
    cleaned = clean_truncated_turtle(truncated)
    assert cleaned != truncated
    assert ":Order" in cleaned
    assert ":Partial" not in cleaned
    Graph().parse(data=cleaned, format="turtle")


def test_truncated_path_operator_is_trimmed():
    """Reproduces the exact crash mode that produced the ontology-generator bug.

    A trailing ``!`` or ``^`` Turtle path operator with no following token
    causes rdflib's ``path()`` to read past the end of the buffer.
    """
    truncated = WELL_FORMED_TURTLE + ":Foo a owl:Class ;\n    rdfs:subClassOf :Bar !"
    cleaned = clean_truncated_turtle(truncated)
    assert ":Foo" not in cleaned
    Graph().parse(data=cleaned, format="turtle")


def test_truncated_then_only_comments_keeps_complete_part():
    truncated = (
        WELL_FORMED_TURTLE
        + "# trailing comment\n"
        + ":Half a owl:Class ;\n    rdfs:label \"Hal"
    )
    cleaned = clean_truncated_turtle(truncated)
    assert ":Order" in cleaned
    assert ":Half" not in cleaned
    Graph().parse(data=cleaned, format="turtle")


def test_cleanup_logs_when_it_trims(caplog):
    truncated = WELL_FORMED_TURTLE + ":Partial a owl:Class ;\n    rdfs:label \"Par"
    with caplog.at_level("WARNING"):
        clean_truncated_turtle(truncated)
    assert any("truncated" in rec.message.lower() for rec in caplog.records)


def test_cleanup_does_not_log_when_input_complete(caplog):
    with caplog.at_level("WARNING"):
        clean_truncated_turtle(WELL_FORMED_TURTLE)
    assert not any("truncated" in rec.message.lower() for rec in caplog.records)


def test_truncated_real_world_llm_payload_parses_after_cleanup():
    """Mirrors the failing payload shape from the ontology generator route.

    The notation3 parser previously raised ``IndexError`` on a payload like
    this; cleanup must trim and the result must parse without exception.
    """
    payload = (
        "@prefix : <http://example.org/onto#> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "\n"
        ":Forecast a owl:Class ;\n"
        "    rdfs:label \"Forecast\" ;\n"
        "    rdfs:comment \"A weather forecast\" .\n"
        "\n"
        ":hasLocation a owl:ObjectProperty ;\n"
        "    rdfs:domain :Forecast ;\n"
        "    rdfs:range :Locat"
    )
    with pytest.raises(Exception):
        Graph().parse(data=payload, format="turtle")

    cleaned = clean_truncated_turtle(payload)
    g = Graph()
    g.parse(data=cleaned, format="turtle")
    labels = list(g.objects(predicate=None))
    assert any("Forecast" in str(o) for o in labels)
