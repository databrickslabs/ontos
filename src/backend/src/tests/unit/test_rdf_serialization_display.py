"""RDF serialization display helpers (syntax labels, not vocabulary)."""

from src.utils.rdf_serialization_display import (
    serialization_label_for_graph_taxonomy,
    serialization_label_for_stored_model,
    serialization_label_from_filename,
)


def test_serialization_from_filename_ttl():
    assert serialization_label_from_filename("foo.ttl") == "Turtle"
    assert serialization_label_from_filename("PATH/bar.n3") == "Turtle"


def test_serialization_from_filename_xml_family():
    assert serialization_label_from_filename("pizza.owl") == "RDF/XML"
    assert serialization_label_from_filename("x.rdf") == "RDF/XML"


def test_serialization_from_filename_unknown():
    assert serialization_label_from_filename("") is None
    assert serialization_label_from_filename("noext") is None


def test_stored_model_prefers_extension_over_legacy_flags():
    assert (
        serialization_label_for_stored_model(
            original_filename="mix.ttl", name="mix.ttl", legacy_format="rdfs"
        )
        == "Turtle"
    )


def test_stored_model_legacy_skos_means_turtle_parse_branch():
    assert (
        serialization_label_for_stored_model(original_filename=None, name="nope", legacy_format="skos")
        == "Turtle"
    )


def test_stored_model_legacy_rdfs_means_xml_parse_branch():
    assert (
        serialization_label_for_stored_model(original_filename=None, name="nope", legacy_format="rdfs")
        == "RDF/XML"
    )


def test_graph_taxonomy_bundled_file_is_turtle_not_skos():
    assert serialization_label_for_graph_taxonomy(source_type="file", graph_format="ttl") == "Turtle"


def test_graph_taxonomy_external_no_false_skos_default():
    assert serialization_label_for_graph_taxonomy(source_type="external", graph_format=None) is None


def test_graph_taxonomy_ttl_hint():
    assert serialization_label_for_graph_taxonomy(source_type="schema", graph_format="ttl") == "Turtle"
