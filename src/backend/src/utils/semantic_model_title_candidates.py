"""Extract human-readable title candidates from RDF ontology / taxonomy content."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from rdflib import Graph, RDF, RDFS, URIRef
from rdflib.namespace import DC, DCTERMS, OWL, SKOS
from rdflib.term import Literal, Node


_TITLE_PREDICATES: Tuple[URIRef, ...] = (
    RDFS.label,
    SKOS.prefLabel,
    DCTERMS.title,
    DC.title,
)

_RDF_FILE_EXTENSIONS: Tuple[str, ...] = (
    ".ttl",
    ".owl",
    ".rdf",
    ".xml",
    ".skos",
    ".rdfs",
    ".nt",
    ".n3",
    ".trig",
    ".trix",
    ".jsonld",
    ".json-ld",
    ".json",
)

# Tokens that should keep their original casing instead of being title-cased
# (acronyms / brand names common in RDF source filenames).
_PRESERVED_CASE_TOKENS: frozenset[str] = frozenset(
    {
        "FIBO", "GS1", "OWL", "RDF", "RDFS", "SKOS", "ODCS", "ODPS",
        "W3C", "OBO", "GO", "DCAT", "PROV", "SHACL", "QUDT", "FOAF",
        "DBpedia", "DC", "VOID", "SIOC", "OAI", "ISO",
    }
)


@dataclass(frozen=True)
class TitleCandidate:
    iri: str
    kind: str
    text: str
    lang: Optional[str]

    def as_dict(self) -> dict:
        d: dict = {"iri": self.iri, "kind": self.kind, "text": self.text}
        if self.lang:
            d["lang"] = self.lang
        return d


def detect_rdf_parse_format(content_text: str, format_field: str) -> str:
    """Match format detection used when loading semantic model content."""
    content_stripped = content_text.strip()
    if content_stripped.startswith("@prefix") or content_stripped.startswith("@base"):
        return "turtle"
    if content_stripped.startswith("{") or content_stripped.startswith("["):
        return "json-ld"
    if content_stripped.startswith("<?xml") or content_stripped.startswith("<rdf:RDF"):
        return "xml"
    return "turtle" if format_field in ("skos", "rdfs") else "xml"


def _literal_lang(lit: Literal) -> Optional[str]:
    return lit.language if getattr(lit, "language", None) else None


def _lang_sort_key(lang: Optional[str]) -> int:
    if lang is None or lang == "":
        return 1
    if lang.lower().startswith("en"):
        return 0
    return 2


def _collect_labels_for_subject(
    graph: Graph,
    subject: Node,
    kind: str,
    title_preds: Tuple[URIRef, ...],
) -> List[TitleCandidate]:
    out: List[TitleCandidate] = []
    if not isinstance(subject, URIRef):
        return out
    iri = str(subject)
    for pred in title_preds:
        for obj in graph.objects(subject, pred):
            if isinstance(obj, Literal):
                text = str(obj).strip()
                if text:
                    out.append(
                        TitleCandidate(
                            iri=iri,
                            kind=kind,
                            text=text,
                            lang=_literal_lang(obj),
                        )
                    )
    return out


def collect_title_candidates_from_graph(graph: Graph) -> List[dict]:
    """
    Collect title/label literals from ontology header resources in an rdflib Graph
    (named graph context or standalone parse result):
    owl:Ontology, skos:ConceptScheme (rdfs:label, skos:prefLabel, dcterms:title, dc:title).
    """
    seen: set[tuple[str, str, Optional[str]]] = set()
    candidates: List[TitleCandidate] = []

    for subj in graph.subjects(RDF.type, OWL.Ontology):
        for c in _collect_labels_for_subject(graph, subj, "owl:Ontology", _TITLE_PREDICATES):
            key = (c.iri, c.text, c.lang)
            if key not in seen:
                seen.add(key)
                candidates.append(c)

    for subj in graph.subjects(RDF.type, SKOS.ConceptScheme):
        for c in _collect_labels_for_subject(graph, subj, "skos:ConceptScheme", _TITLE_PREDICATES):
            key = (c.iri, c.text, c.lang)
            if key not in seen:
                seen.add(key)
                candidates.append(c)

    candidates.sort(key=lambda c: (_lang_sort_key(c.lang), c.kind, c.text.lower()))
    return [c.as_dict() for c in candidates]


def best_display_title_from_graph(graph: Graph) -> Optional[str]:
    """Pick a single display title from graph ontology headers (same policy as upload auto-title)."""
    return pick_auto_display_name(collect_title_candidates_from_graph(graph))


def extract_title_candidates(content_text: str, format_field: str) -> List[dict]:
    """
    Collect title/label literals from ontology header resources:
    owl:Ontology, skos:ConceptScheme (rdfs:label, skos:prefLabel, dcterms:title, dc:title).
    """
    if content_text is None or not str(content_text).strip():
        return []

    fmt = detect_rdf_parse_format(content_text, format_field)
    graph = Graph()
    graph.parse(data=content_text, format=fmt)
    return collect_title_candidates_from_graph(graph)


def humanize_rdf_filename(filename: str) -> str:
    """Turn an RDF source filename into a human-readable title.

    Steps:
      1. Take the basename (drop any directory parts).
      2. Strip a single known RDF extension if present (case-insensitive).
      3. Replace ``_``, ``-`` and ``.`` with spaces.
      4. Collapse whitespace.
      5. Title-case word-by-word, preserving common acronyms (FIBO, GS1, ...).

    Returns the original filename unchanged if it ends up empty after cleaning.
    """
    if not filename:
        return ""

    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    lower = name.lower()
    for ext in _RDF_FILE_EXTENSIONS:
        if lower.endswith(ext):
            name = name[: -len(ext)]
            break

    cleaned = re.sub(r"[._\-]+", " ", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return filename

    parts: List[str] = []
    for word in cleaned.split(" "):
        upper = word.upper()
        if upper in _PRESERVED_CASE_TOKENS:
            parts.append(upper)
        elif word.isupper() and len(word) <= 4 and word.isalpha():
            parts.append(word)
        else:
            parts.append(word[:1].upper() + word[1:].lower() if word else word)
    return " ".join(parts)


def pick_auto_display_name(candidates: List[dict]) -> Optional[str]:
    """
    If there is a single distinct title text across all candidates, use it.
    Otherwise, if any owl:Ontology candidate exists, use the first one's text after sorting.
    """
    if not candidates:
        return None
    texts = {c["text"].strip() for c in candidates if c.get("text")}
    if len(texts) == 1:
        return next(iter(texts))
    owl_first = next((c for c in candidates if c.get("kind") == "owl:Ontology"), None)
    if owl_first and owl_first.get("text"):
        return owl_first["text"].strip()
    return None
