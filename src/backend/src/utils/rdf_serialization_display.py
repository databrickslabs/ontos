"""User-facing RDF *serialization* labels (syntax), not vocabulary (SKOS/OWL/RDFS)."""

from __future__ import annotations

from typing import Optional


def serialization_label_from_filename(filename: str) -> Optional[str]:
    """Map file extension to a serialization display name. Returns None if unknown."""
    if not filename:
        return None
    lower = filename.lower()
    if lower.endswith((".ttl", ".n3")):
        return "Turtle"
    if lower.endswith((".owl", ".rdf", ".xml")):
        return "RDF/XML"
    if lower.endswith((".jsonld", ".json-ld")) or lower.endswith(".json"):
        return "JSON-LD"
    if lower.endswith(".nt"):
        return "N-Triples"
    if lower.endswith(".trig"):
        return "TriG"
    if lower.endswith(".trix"):
        return "TriX"
    if lower.endswith(".skos") or lower.endswith(".rdfs"):
        return "Turtle"
    return None


def serialization_label_for_stored_model(
    *,
    original_filename: Optional[str],
    name: str,
    legacy_format: str,
) -> Optional[str]:
    """Label for a row from `semantic_models`: prefer filename extension, else upload parse-branch hints."""
    label = serialization_label_from_filename((original_filename or "").strip()) or serialization_label_from_filename(
        (name or "").strip()
    )
    if label:
        return label
    lf = (legacy_format or "").lower()
    if lf == "skos":
        return "Turtle"
    if lf == "rdfs":
        return "RDF/XML"
    return None


def serialization_label_for_graph_taxonomy(*, source_type: str, graph_format: Optional[str]) -> Optional[str]:
    """Serialization hint from graph taxonomy metadata (not vocabulary)."""
    if source_type == "file":
        return "Turtle"
    gf = (graph_format or "").lower()
    if gf == "ttl":
        return "Turtle"
    if gf == "rdfs":
        return "RDF/XML"
    return None
