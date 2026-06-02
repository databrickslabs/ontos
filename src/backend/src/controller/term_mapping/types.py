"""Internal dataclasses shared by adapters and engines.

These shapes are the contract between the entity-specific adapters and the
generic suggester engines. The engine never sees Ontos types directly — the
adapters translate at the boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TargetEntity:
    """One thing the suggester can attach concept links to.

    A TargetEntity can be:
      * a top-level "container" (a Data Product, a Data Contract, an Asset of
        type Table/Dataset). The engine treats this as an entity_assignment
        candidate.
      * a "sub-entity" (a Data Contract property, an Asset of type Column).
        The engine treats this as an attribute_assignment candidate.

    ``entity_id`` follows the existing semantic-link convention:
      - data_product / data_contract / asset:  UUID string
      - data_contract_schema: ``{contract_id}#{schema_name}``
      - data_contract_property: ``{contract_id}#{schema_name}#{property_name}``
    """
    entity_type: str   # one of TargetEntityType from models/term_mappings.py
    entity_id: str
    name: str          # short identifier, e.g. column name "cust_email"
    label: str         # display name, often == name
    type_label: str = ""   # primitive type for sub-entities (STRING, INT, …)
    # For sub-entities: pointer to the parent's container target so the engine
    # can reason about entity-vs-attribute assignment coherently.
    parent_entity_type: Optional[str] = None
    parent_entity_id: Optional[str] = None
    parent_name: Optional[str] = None
    # Optional pk/fk flags from the source schema.
    is_pk: bool = False
    is_fk: bool = False
    # Free-form extras the adapter can stash (e.g. property classification).
    extras: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConceptCandidate:
    """One concept from a customer ontology, pulled by ConceptSource."""
    iri: str
    label: str
    comment: str = ""
    # Which ontology this came from. Carries through into suggestion `reason`
    # strings so stewards can prefer concepts from the vocabulary they trust.
    source_context: str = ""
    # rdfs:subClassOf parents, if known. Used by future semantic engines.
    parent_iris: List[str] = field(default_factory=list)
    # True if SKOS concept or rdfs:Class. False for owl:DatatypeProperty /
    # ObjectProperty (we treat those as attribute candidates).
    is_class: bool = True
    # For property concepts, the rdfs:range value (xsd type or class IRI).
    range_type: str = ""


@dataclass
class SuggestionDraft:
    """Engine output. The manager turns each draft into a MappingSuggestionDb row.

    Intentionally separate from the DB model so engines stay easily testable.
    """
    source_entity_type: str
    source_entity_id: str
    source_label: str
    suggestion_kind: str  # entity_assignment | attribute_assignment
    target_concept_iri: str
    target_concept_label: str
    confidence: float
    reason: str
    auto_apply: bool = False
    engine: str = "heuristic"
    engine_metadata: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
