"""Pydantic API models for the term-mapping feature.

Wire-format spec for routes/term_mapping_routes.py. Mirrors the DB shape in
db_models/term_mappings.py but uses str ids and ISO-format timestamps for the
HTTP boundary.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------- Enums (literals for the wire) ----------

RunStatus = Literal[
    "pending",
    "suggesting",
    "suggested",
    "applying",
    "applied",
    "undone",
    "failed",
]

SuggestionStatus = Literal[
    "pending",
    "accepted",
    "rejected",
    "applied",
    "superseded",
]

SuggestionKind = Literal["entity_assignment", "attribute_assignment"]

Engine = Literal["heuristic", "llm_judge"]

# Subset of entity_semantic_links EntityType valid as a term-mapping target.
TargetEntityType = Literal[
    "data_product",
    "data_contract",
    "data_contract_schema",
    "data_contract_property",
    "dataset",
    "asset",
]


# ---------- Run shapes ----------

class RunTargetFilter(BaseModel):
    """Filter that scopes a run's target selection.

    All fields are optional; omitted = no filter on that dimension. When
    multiple fields are set they AND-combine.
    """
    entity_types: Optional[List[TargetEntityType]] = None
    domain_ids: Optional[List[str]] = None
    contract_ids: Optional[List[str]] = None
    product_ids: Optional[List[str]] = None
    # For asset targets: filter to specific asset_type names (e.g. "Column",
    # "Table"). When omitted, defaults to ["Column"] in the adapter so we
    # don't suggest concepts for entire tables by default.
    asset_type_names: Optional[List[str]] = None
    # Hard cap on targets per run; defaults applied by manager.
    limit: Optional[int] = None


class RunCreate(BaseModel):
    """POST /api/term-mappings/runs body.

    ontology_contexts defaults (on the manager side) to every enabled
    customer ontology (urn:semantic-model:*). The internal
    urn:taxonomy:ontos-ontology context is rejected.
    """
    ontology_contexts: Optional[List[str]] = None
    include_shipped: List[str] = Field(default_factory=list)
    target_filter: RunTargetFilter = Field(default_factory=RunTargetFilter)
    engines: List[Engine] = Field(default_factory=lambda: ["heuristic"])
    comment: Optional[str] = None


class RunRead(BaseModel):
    # UUID fields below are typed as `UUID` so Pydantic accepts the SQLAlchemy
    # PG_UUID instances directly (model_validate from ORM rows). Pydantic v2
    # serializes UUID to a plain JSON string, so the wire format stays
    # `"abc-def-..."` and the TS client keeps treating these as strings.
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ontology_contexts: List[str]
    include_shipped: List[str]
    target_filter: Dict[str, Any]
    engines: List[str]
    status: RunStatus
    comment: Optional[str] = None
    stats: Dict[str, Any]
    error: Optional[str] = None
    applied_link_ids: List[UUID]
    created_by: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    applied_at: Optional[datetime] = None
    undone_at: Optional[datetime] = None


class RunSummary(BaseModel):
    """List-view projection of a run."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: RunStatus
    comment: Optional[str] = None
    stats: Dict[str, Any]
    created_by: Optional[str] = None
    created_at: datetime
    finished_at: Optional[datetime] = None
    applied_at: Optional[datetime] = None


# ---------- Suggestion shapes ----------

class SuggestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    source_entity_type: str
    source_entity_id: str
    source_label: Optional[str] = None
    suggestion_kind: SuggestionKind
    target_concept_iri: str
    target_concept_label: Optional[str] = None
    confidence: float
    reason: str
    auto_apply: bool
    engine: Engine
    engine_metadata: Optional[Dict[str, Any]] = None
    status: SuggestionStatus
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    custom_iri: Optional[str] = None
    applied_link_id: Optional[UUID] = None
    warnings: Optional[List[str]] = None
    created_at: datetime
    updated_at: datetime


class SuggestionDecision(BaseModel):
    """Single steward decision for bulk POST /suggestions/decisions."""
    id: str
    decision: Literal["accept", "reject"]
    custom_iri: Optional[str] = None  # only meaningful for decision=accept


class SuggestionDecisionBatch(BaseModel):
    decisions: List[SuggestionDecision]


class SuggestionDecisionResult(BaseModel):
    accepted: int
    rejected: int
    skipped: int  # suggestions whose id wasn't found or whose status was already terminal
    errors: List[str] = Field(default_factory=list)


# ---------- Apply / Undo result shapes ----------

class ApplyResult(BaseModel):
    run_id: UUID
    links_created: int
    links_skipped: int  # e.g. orphan attribute, NEW: prefix, duplicate
    errors: List[str] = Field(default_factory=list)


class UndoResult(BaseModel):
    run_id: UUID
    links_removed: int
    suggestions_reverted: int
    errors: List[str] = Field(default_factory=list)


class PendingSuggestionCount(BaseModel):
    """Drives the per-entity 'N pending suggestions' badge."""
    entity_type: str
    entity_id: str
    pending: int
    auto_apply: int
