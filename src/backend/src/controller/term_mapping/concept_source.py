"""Concept lookup for the term-mapping suggester.

Concept candidates come ONLY from customer ontologies (rows in the
``semantic_models`` DB table, mirrored into the RDF graph under
``urn:semantic-model:*`` contexts) plus any shipped taxonomies the steward has
explicitly opted into per run.

The internal ``urn:taxonomy:ontos-ontology`` context defines Ontos's own Asset
typing schema (Table, Column, DataProduct…) and is **never** a valid
assignment target — this module rejects any caller that tries to include it.
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Set, TYPE_CHECKING

from rdflib import RDF, RDFS, OWL, Namespace, URIRef
from rdflib.namespace import SKOS

from src.common.logging import get_logger

from .types import ConceptCandidate

if TYPE_CHECKING:
    from src.controller.semantic_models_manager import SemanticModelsManager

logger = get_logger(__name__)


# Contexts that are NEVER selectable as a concept source for term-mapping.
# `ontos-ontology` defines internal Asset typing. The remaining `urn:meta:*` /
# `urn:semantic-links` etc. are internal app indices.
INTERNAL_BLOCKED_CONTEXTS: Set[str] = {
    "urn:taxonomy:ontos-ontology",
    "urn:semantic-links",
}

# Shipped customer-usable taxonomies. Excluded from defaults but selectable
# per-run via include_shipped. See PRD concept-source rules.
SHIPPED_OPT_IN_CONTEXTS: Set[str] = {
    "urn:taxonomy:databricks_ontology",
    "urn:taxonomy:odcs-ontology",
}

CUSTOMER_CONTEXT_PREFIX = "urn:semantic-model:"


class InvalidContextError(ValueError):
    """Raised when a caller tries to use an internal/blocked context."""


def is_customer_context(ctx: str) -> bool:
    return ctx.startswith(CUSTOMER_CONTEXT_PREFIX)


def is_shipped_context(ctx: str) -> bool:
    return ctx in SHIPPED_OPT_IN_CONTEXTS


def validate_contexts(
    ontology_contexts: Sequence[str],
    include_shipped: Sequence[str],
) -> List[str]:
    """Validate the run's selected contexts and return the full effective list.

    Rules:
      * INTERNAL_BLOCKED_CONTEXTS are rejected outright (HTTP 422 surface).
      * ontology_contexts items must be customer contexts.
      * include_shipped items must be in SHIPPED_OPT_IN_CONTEXTS.
    """
    seen: List[str] = []

    for ctx in ontology_contexts:
        if ctx in INTERNAL_BLOCKED_CONTEXTS:
            raise InvalidContextError(
                f"Context '{ctx}' is internal to Ontos and not assignable. "
                f"Use a customer ontology (urn:semantic-model:*) instead."
            )
        if ctx in SHIPPED_OPT_IN_CONTEXTS:
            raise InvalidContextError(
                f"Context '{ctx}' is a shipped taxonomy. Pass it via "
                f"include_shipped, not ontology_contexts."
            )
        if not is_customer_context(ctx):
            raise InvalidContextError(
                f"Context '{ctx}' is not recognised as a customer ontology "
                f"(must start with '{CUSTOMER_CONTEXT_PREFIX}')."
            )
        if ctx not in seen:
            seen.append(ctx)

    for ctx in include_shipped:
        if ctx in INTERNAL_BLOCKED_CONTEXTS:
            raise InvalidContextError(
                f"Context '{ctx}' is internal to Ontos and not assignable."
            )
        if ctx not in SHIPPED_OPT_IN_CONTEXTS:
            raise InvalidContextError(
                f"Context '{ctx}' is not on the shipped opt-in list. "
                f"Allowed shipped contexts: {sorted(SHIPPED_OPT_IN_CONTEXTS)}."
            )
        if ctx not in seen:
            seen.append(ctx)

    return seen


class ConceptSource:
    """Read-side wrapper around SemanticModelsManager that scopes lookups to
    a fixed set of RDF graph contexts.

    Holds the candidate list in memory (one list per run) — customer
    ontologies are small enough (hundreds, maybe low thousands of concepts)
    that pre-loading is faster than re-querying per target.
    """

    def __init__(
        self,
        semantic_models_manager: "SemanticModelsManager",
        contexts: Sequence[str],
    ):
        self._smm = semantic_models_manager
        self._contexts: List[str] = list(contexts)
        self._classes: List[ConceptCandidate] = []
        self._properties: List[ConceptCandidate] = []
        self._loaded = False

    @property
    def contexts(self) -> List[str]:
        return list(self._contexts)

    def load(self) -> None:
        """Pull all class + property concepts from the configured contexts.

        Iterates over the rdflib ConjunctiveGraph's named graphs directly
        rather than via SPARQL — gives us context-scoped traversal without
        depending on the FROM-clause behaviour of every rdflib version.
        """
        if self._loaded:
            return

        graph = self._smm._graph  # ConjunctiveGraph

        wanted: Set[str] = set(self._contexts)
        classes_seen: dict[str, ConceptCandidate] = {}
        props_seen: dict[str, ConceptCandidate] = {}

        for context in graph.contexts():
            ctx_name = str(context.identifier)
            if ctx_name not in wanted:
                continue

            for subject in _classes_in_context(context):
                iri = str(subject)
                if iri in classes_seen:
                    continue
                classes_seen[iri] = ConceptCandidate(
                    iri=iri,
                    label=_pick_label(context, subject),
                    comment=_pick_comment(context, subject),
                    source_context=ctx_name,
                    parent_iris=_parents(context, subject),
                    is_class=True,
                )

            for subject in _properties_in_context(context):
                iri = str(subject)
                if iri in props_seen:
                    continue
                props_seen[iri] = ConceptCandidate(
                    iri=iri,
                    label=_pick_label(context, subject),
                    comment=_pick_comment(context, subject),
                    source_context=ctx_name,
                    parent_iris=_parents(context, subject),
                    is_class=False,
                    range_type=_pick_range(context, subject),
                )

        self._classes = sorted(classes_seen.values(), key=lambda c: c.iri)
        self._properties = sorted(props_seen.values(), key=lambda c: c.iri)
        self._loaded = True
        logger.info(
            "ConceptSource loaded %d classes + %d properties from %d contexts: %s",
            len(self._classes),
            len(self._properties),
            len(wanted),
            sorted(wanted),
        )

    def classes(self) -> List[ConceptCandidate]:
        if not self._loaded:
            self.load()
        return self._classes

    def properties(self) -> List[ConceptCandidate]:
        if not self._loaded:
            self.load()
        return self._properties


def resolve_default_customer_contexts(
    semantic_models_manager: "SemanticModelsManager",
) -> List[str]:
    """Default = every enabled ``urn:semantic-model:*`` context present in
    the graph. Excludes disabled rows (already filtered by SemanticModelsManager)."""
    graph = semantic_models_manager._graph
    contexts: List[str] = []
    for ctx in graph.contexts():
        name = str(ctx.identifier)
        if is_customer_context(name) and name not in contexts:
            contexts.append(name)
    return sorted(contexts)


# ---------- Helpers (private) ----------

_CLASS_TYPES = (
    RDFS.Class,
    OWL.Class,
    SKOS.Concept,
)


def _classes_in_context(context) -> Iterable[URIRef]:
    seen: Set[URIRef] = set()
    for cls_type in _CLASS_TYPES:
        for s in context.subjects(RDF.type, cls_type):
            if isinstance(s, URIRef) and s not in seen:
                seen.add(s)
                yield s
    # Also: anything declared as a subClassOf is a class even if rdf:type is
    # implicit. Matches semantic_models_manager.search_concepts logic.
    for s in context.subjects(RDFS.subClassOf, None):
        if isinstance(s, URIRef) and s not in seen:
            seen.add(s)
            yield s


_PROPERTY_TYPES = (
    OWL.ObjectProperty,
    OWL.DatatypeProperty,
    RDF.Property,
)


def _properties_in_context(context) -> Iterable[URIRef]:
    seen: Set[URIRef] = set()
    for prop_type in _PROPERTY_TYPES:
        for s in context.subjects(RDF.type, prop_type):
            if isinstance(s, URIRef) and s not in seen:
                seen.add(s)
                yield s


def _pick_label(context, subject) -> str:
    for label in context.objects(subject, RDFS.label):
        return str(label)
    for label in context.objects(subject, SKOS.prefLabel):
        return str(label)
    iri = str(subject)
    return iri.split("#")[-1].split("/")[-1]


def _pick_comment(context, subject) -> str:
    for c in context.objects(subject, RDFS.comment):
        return str(c)
    for c in context.objects(subject, SKOS.definition):
        return str(c)
    return ""


def _pick_range(context, subject) -> str:
    for r in context.objects(subject, RDFS.range):
        return str(r)
    return ""


def _parents(context, subject) -> List[str]:
    parents: List[str] = []
    for parent in context.objects(subject, RDFS.subClassOf):
        if isinstance(parent, URIRef):
            parents.append(str(parent))
    for parent in context.objects(subject, RDFS.subPropertyOf):
        if isinstance(parent, URIRef):
            parents.append(str(parent))
    return parents
