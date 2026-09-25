"""Pydantic request/response models for the Authority Resolution API.

Response assembly is done in the manager (``to_read_dict``) so we don't depend on
ORM-mode across Pydantic versions; these models are primarily for request
validation and typed response shapes.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.models.tags import AssignedTagCreate


class EvidenceBinding(BaseModel):
    """Legacy single evidence binding: one UC Delta table + a column→AR-element map."""
    source_table_fqn: str
    column_map: Dict[str, str] = Field(default_factory=dict)
    row_filter: Optional[str] = None


class EvidenceSource(BaseModel):
    """One typed evidence source bound to an AR.

    ``type`` is ``delta_table`` (ref = table FQN), ``asset`` (ref = an asset that
    resolves to a table/view FQN), or ``data_product`` (ref = data product id;
    resolved to its output-port table — declared-only in v1). ``column_map`` maps
    canonical AR elements (actual_approver, documented_approver, value, escalated,
    cosign_present, action, object_id) to this source's raw column names.
    """
    type: str = "delta_table"
    ref: str
    label: Optional[str] = None
    column_map: Dict[str, str] = Field(default_factory=dict)
    row_filter: Optional[str] = None


class AffirmationInput(BaseModel):
    role: str                                   # Business Role name (cached label)
    business_role_id: Optional[str] = None      # Settings Business Role id (organizational role)
    role_category: Optional[str] = None         # governance|technical|business|operational
    principal: str                              # email or group id
    principal_type: str = "user"                # user|group
    required: bool = True
    sort_order: int = 0
    # A participant can be an approver (affirmation gate), a reviewer
    # (interviewee in the review process), or both.
    is_approver: bool = True
    is_reviewer: bool = False


class CriterionInput(BaseModel):
    """One author-configurable decision criterion attached to an AR.

    Either link an existing Compliance Check (``policy_id``) or author a new one
    inline (``name`` + ``rule``, an ``ASSERT`` DSL condition). ``direction`` and
    ``weight`` are the ARF divergence facets recorded on the link.
    """
    policy_id: Optional[str] = None             # link an existing compliance policy
    name: Optional[str] = None                  # inline-authored policy name
    rule: Optional[str] = None                  # inline-authored DSL rule (ASSERT obj.… )
    failure_message: Optional[str] = None
    direction: str = "neutral"                  # actual-exceeds-documented | documented-exceeds-actual | neutral
    weight: float = 1.0
    dimension: str = "people"                   # DNAco dimension this criterion scores
    order: int = 0
    enabled: bool = True


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
    evidence_sources: Optional[List[EvidenceSource]] = None
    dna_max_threshold: float = 0.3
    dna_scoring_config: Optional[Dict[str, Any]] = None
    schedule_cron: Optional[str] = None
    # Multi-domain assignment
    domain_ids: List[str] = Field(default_factory=list)
    primary_domain_id: Optional[str] = None
    # N-functional affirmation stakeholders
    affirmations: List[AffirmationInput] = Field(default_factory=list)
    # Author-configurable decision criteria (Compliance Checks)
    criteria: List[CriterionInput] = Field(default_factory=list)
    # Polymorphic tags
    tags: Optional[List[AssignedTagCreate]] = None


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
    evidence_sources: Optional[List[EvidenceSource]] = None
    dna_max_threshold: Optional[float] = None
    dna_scoring_config: Optional[Dict[str, Any]] = None
    schedule_cron: Optional[str] = None
    domain_ids: Optional[List[str]] = None
    primary_domain_id: Optional[str] = None
    affirmations: Optional[List[AffirmationInput]] = None
    criteria: Optional[List[CriterionInput]] = None
    tags: Optional[List[AssignedTagCreate]] = None


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
