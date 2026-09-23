"""Pydantic request/response models for the Authority Resolution API.

Response assembly is done in the manager (``to_read_dict``) so we don't depend on
ORM-mode across Pydantic versions; these models are primarily for request
validation and typed response shapes.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class EvidenceBinding(BaseModel):
    """v1 evidence binding: one UC Delta table + a column→AR-element map."""
    source_table_fqn: str
    column_map: Dict[str, str] = Field(default_factory=dict)
    row_filter: Optional[str] = None


class AffirmationInput(BaseModel):
    role: str                                   # business|technical|governance|<custom>
    principal: str                              # email or group id
    principal_type: str = "user"                # user|group
    required: bool = True
    sort_order: int = 0


class AuthorityRelationCreate(BaseModel):
    name: str
    description: Optional[str] = None
    slug: Optional[str] = None
    # ARF tuple
    actor_role: Optional[str] = None
    actor_identity: Optional[str] = None
    actor_since: Optional[datetime] = None
    action: Optional[str] = None
    object_type: Optional[str] = None
    object_id: Optional[str] = None
    object_resolves_to: Optional[List[str]] = None
    domain_context: Optional[Dict[str, Any]] = None
    justification_chain: Optional[Dict[str, Any]] = None
    decision_logic: Optional[Dict[str, Any]] = None
    evidence_binding: Optional[EvidenceBinding] = None
    dna_max_threshold: float = 0.3
    dna_scoring_config: Optional[Dict[str, Any]] = None
    schedule_cron: Optional[str] = None
    # Multi-domain assignment
    domain_ids: List[str] = Field(default_factory=list)
    primary_domain_id: Optional[str] = None
    # N-functional affirmation stakeholders
    affirmations: List[AffirmationInput] = Field(default_factory=list)


class AuthorityRelationUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    actor_role: Optional[str] = None
    actor_identity: Optional[str] = None
    actor_since: Optional[datetime] = None
    action: Optional[str] = None
    object_type: Optional[str] = None
    object_id: Optional[str] = None
    object_resolves_to: Optional[List[str]] = None
    domain_context: Optional[Dict[str, Any]] = None
    justification_chain: Optional[Dict[str, Any]] = None
    decision_logic: Optional[Dict[str, Any]] = None
    evidence_binding: Optional[EvidenceBinding] = None
    dna_max_threshold: Optional[float] = None
    dna_scoring_config: Optional[Dict[str, Any]] = None
    schedule_cron: Optional[str] = None
    domain_ids: Optional[List[str]] = None
    primary_domain_id: Optional[str] = None
    affirmations: Optional[List[AffirmationInput]] = None


class StatusChangeRequest(BaseModel):
    status: str                                 # active|draft|needs_review|retired


class AffirmRequest(BaseModel):
    notes: Optional[str] = None


class ResolveRequest(BaseModel):
    """Runtime decision parameters an agent supplies to the resolution gate."""
    actor_identity: Optional[str] = None
    action: Optional[str] = None
    object_id: Optional[str] = None
    value: Optional[float] = None
    cosign_present: Optional[bool] = None
    escalated: Optional[bool] = None
    params: Dict[str, Any] = Field(default_factory=dict)


class ResolveResponse(BaseModel):
    verdict: str                                # approved|denied|no_authority|conflict
    reason: str
    relation_id: Optional[str] = None
    relation_slug: Optional[str] = None
    relation_version: Optional[int] = None
    dna_magnitude: Optional[float] = None
    dna_direction: Optional[str] = None
