"""Concept-level diff engine for file re-upload as a bulk versioning event (P0-4).

A re-upload of a semantic-model file is NOT a blind delete-replace. It is a
bulk versioning event: we diff the incoming triples against what is currently
stored for that file's context, group by concept subject IRI, and bucket each
concept into {unchanged, modified, new, removed}. The orchestrator on the
manager then maps each bucket to the EXISTING versioning primitives
(publish_concept_version / create_concept / deprecate_concept).

THE all-or-nothing correctness prerequisite — blank-node canonicalization
(URDNA2015):
    Protege / OWL exports are full of blank nodes (owl:Restriction,
    owl:unionOf lists, owl:onProperty). Blank nodes have NO stable identity
    across serializations, so a naive triple set-diff reports a byte-identical
    re-upload as "everything changed" and mints spurious versions + false
    UC-remap alarms. We therefore canonicalize BOTH graphs with rdflib's
    ``to_canonical_graph`` (URDNA2015) BEFORE grouping/comparing. A concept
    whose canonical triple set is identical across the two uploads lands in the
    ``unchanged`` bucket and mints ZERO new versions.

Triple ownership (P0-1 rule): a triple's owning concept = its subject IRI.
Blank-node closures follow the IRI subject they hang off. We only bucket named
(URIRef) subjects as concepts; blank-node subjects are pulled into the canonical
comparison via the triples that reference them but are never themselves treated
as concepts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from rdflib import Graph, URIRef, Literal, BNode
from rdflib.compare import to_canonical_graph
from rdflib.namespace import RDF, RDFS, SKOS, OWL

from src.common.logging import get_logger

logger = get_logger(__name__)

# rdf:type values that mark a subject as a CONCEPT we version. A ConceptScheme
# / owl:Ontology header is deliberately NOT here — scheme/metadata subjects are
# not versioned units and must not be pushed through the concept primitives.
_CONCEPT_TYPES = frozenset(
    str(t)
    for t in (
        SKOS.Concept,
        RDFS.Class,
        OWL.Class,
        OWL.ObjectProperty,
        OWL.DatatypeProperty,
        OWL.AnnotationProperty,
        RDF.Property,
    )
)


# Human/SKOS fields we surface as ``changes`` for a MODIFIED concept so the
# orchestrator can feed them straight into ``publish_concept_version``. Mirrors
# the manager's _PUBLISH_* field maps so the two stay in lockstep.
_LITERAL_FIELDS: Dict[str, URIRef] = {
    "label": SKOS.prefLabel,
    "definition": SKOS.definition,
}
_LIST_LITERAL_FIELDS: Dict[str, URIRef] = {
    "synonyms": SKOS.altLabel,
    "examples": SKOS.example,
}
_LIST_URI_FIELDS: Dict[str, URIRef] = {
    "broader_iris": SKOS.broader,
    "narrower_iris": SKOS.narrower,
    "related_iris": SKOS.related,
}


@dataclass
class ConceptDiff:
    """The result of diffing an incoming upload against the current store.

    Each bucket is a list of concept IRIs (strings). ``modified`` additionally
    carries the incoming human-field values keyed by IRI in ``changes`` so the
    orchestrator can pass them to ``publish_concept_version(changes=...)``.
    """

    unchanged: List[str] = field(default_factory=list)
    modified: List[str] = field(default_factory=list)
    new: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    # iri -> {field: value} extracted from the incoming graph for MODIFIED and
    # NEW concepts (new concepts also need field values to be created).
    changes: Dict[str, Dict[str, object]] = field(default_factory=dict)

    def summary(self) -> Dict[str, int]:
        return {
            "unchanged": len(self.unchanged),
            "modified": len(self.modified),
            "new": len(self.new),
            "removed": len(self.removed),
        }


def _canonical_triples_by_subject(graph: Graph) -> Dict[str, frozenset]:
    """Canonicalize a graph (URDNA2015) and group triples by named subject IRI.

    Returns ``{subject_iri: frozenset(canonical (pred, obj_key) tuples)}`` for
    every URIRef subject. Blank-node subjects are skipped as concept keys (they
    have no stable identity), but the canonicalization step has already given
    every blank node a deterministic label, so triples pointing AT a bnode
    object compare stably across uploads.

    The per-subject value is a frozenset of ``(predicate, object-fingerprint)``
    so two subjects with the same set of outgoing edges compare equal
    regardless of triple ordering.
    """
    canonical = to_canonical_graph(graph)
    by_subject: Dict[str, set] = {}
    for subj, pred, obj in canonical:
        if not isinstance(subj, URIRef):
            # Blank-node subject: part of some concept's closure, not a concept
            # itself. Its canonical label is deterministic post-URDNA2015, so it
            # already contributes a stable object-fingerprint wherever a named
            # subject points at it.
            continue
        by_subject.setdefault(str(subj), set()).add(
            (str(pred), _object_fingerprint(obj))
        )
    return {k: frozenset(v) for k, v in by_subject.items()}


def _object_fingerprint(obj) -> str:
    """A stable string fingerprint for a triple object.

    URIRef -> its IRI; Literal -> value + lang + datatype; BNode -> its
    canonical label (deterministic after ``to_canonical_graph``). This makes
    two literals equal only when value AND lang AND datatype match.
    """
    if isinstance(obj, Literal):
        return f"L:{str(obj)}\x1f{obj.language or ''}\x1f{obj.datatype or ''}"
    if isinstance(obj, BNode):
        return f"B:{str(obj)}"
    return f"U:{str(obj)}"


def compute_concept_diff(incoming_graph: Graph, current_triples) -> ConceptDiff:
    """Diff an incoming parsed graph against the current stored triples.

    Both sides are canonicalized (URDNA2015) BEFORE comparison so blank nodes
    do not produce spurious diffs. Grouping is by named concept subject IRI.

    Buckets:
      - unchanged: subject in both, canonical triple sets identical
                   -> NO new version (byte-identical re-upload = no-op).
      - modified:  subject in both, triple sets differ -> mint new version.
      - new:       subject only in incoming -> create (v1).
      - removed:   subject only in current -> deprecate/tombstone.
    """
    incoming_by_subj = _canonical_triples_by_subject(incoming_graph)

    # Reconstruct the current side as one graph, canonicalize it whole, then
    # group by subject. Canonicalizing the whole graph (not per-subject) is
    # required so bnode labels are globally consistent with the incoming graph.
    current_graph = _rebuild_current_graph(current_triples)
    current_by_subj = _canonical_triples_by_subject(current_graph)

    # Only bucket CONCEPT subjects. Scheme / ontology-header / bnode subjects
    # are not versioned units and must not be pushed through the concept
    # primitives (publish/deprecate call get_concept and would fail on them).
    incoming_concepts = _concept_subjects(incoming_graph)
    current_concepts = _concept_subjects(current_graph)

    incoming_subjects = incoming_concepts & set(incoming_by_subj.keys())
    current_subjects = current_concepts & set(current_by_subj.keys())

    diff = ConceptDiff()

    for iri in sorted(incoming_subjects & current_subjects):
        if incoming_by_subj[iri] == current_by_subj[iri]:
            diff.unchanged.append(iri)
        else:
            diff.modified.append(iri)
            diff.changes[iri] = _extract_changes(incoming_graph, iri)

    for iri in sorted(incoming_subjects - current_subjects):
        diff.new.append(iri)
        diff.changes[iri] = _extract_changes(incoming_graph, iri)

    for iri in sorted(current_subjects - incoming_subjects):
        diff.removed.append(iri)

    logger.info("Concept diff: %s", diff.summary())
    return diff


def _concept_subjects(graph: Graph) -> set:
    """Named subject IRIs that are CONCEPTS (have a versionable rdf:type).

    A subject counts as a concept if it carries at least one rdf:type in
    ``_CONCEPT_TYPES``. This deliberately excludes skos:ConceptScheme and
    owl:Ontology header subjects so they are never routed through the concept
    versioning primitives.
    """
    concepts: set = set()
    for subj in graph.subjects(RDF.type, None):
        if not isinstance(subj, URIRef):
            continue
        for t in graph.objects(subj, RDF.type):
            if str(t) in _CONCEPT_TYPES:
                concepts.add(str(subj))
                break
    return concepts


def _rebuild_current_graph(current_triples) -> Graph:
    """Rebuild ONE rdflib Graph from stored rows, de-skolemizing blank nodes."""
    g = Graph()
    bnode_map: Dict[str, BNode] = {}

    def _term(value: str, is_uri: bool, lang: str, dtype: str):
        if is_uri:
            if value.startswith("urn:ontos:bnode:"):
                if value not in bnode_map:
                    bnode_map[value] = BNode()
                return bnode_map[value]
            return URIRef(value)
        if dtype:
            return Literal(value, datatype=URIRef(dtype))
        if lang:
            return Literal(value, lang=lang)
        return Literal(value)

    for t in current_triples:
        subj = _term(t.subject_uri, True, "", "")
        pred = URIRef(t.predicate_uri)
        obj = _term(
            t.object_value,
            bool(t.object_is_uri),
            t.object_language or "",
            t.object_datatype or "",
        )
        g.add((subj, pred, obj))
    return g


def _extract_changes(graph: Graph, iri: str) -> Dict[str, object]:
    """Pull the human/SKOS field values for a concept out of the incoming graph.

    Shaped to match ``publish_concept_version(changes=...)`` and
    ``create_concept(...)`` kwargs. Literal fields take the first value; list
    fields collect all. Missing fields are omitted so a publish only overwrites
    what the file actually carries.
    """
    subj = URIRef(iri)
    changes: Dict[str, object] = {}

    for field_name, pred in _LITERAL_FIELDS.items():
        val = graph.value(subj, pred)
        # RDFS fallbacks so RDFS/OWL exports (rdfs:label / rdfs:comment) map too.
        if val is None and field_name == "label":
            val = graph.value(subj, RDFS.label)
        if val is None and field_name == "definition":
            val = graph.value(subj, RDFS.comment)
        if val is not None:
            changes[field_name] = str(val)

    for field_name, pred in _LIST_LITERAL_FIELDS.items():
        vals = [str(o) for o in graph.objects(subj, pred)]
        if vals:
            changes[field_name] = vals

    for field_name, pred in _LIST_URI_FIELDS.items():
        vals = [str(o) for o in graph.objects(subj, pred) if isinstance(o, URIRef)]
        if vals:
            changes[field_name] = vals

    return changes
