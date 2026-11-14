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


class PrerequisiteInput(BaseModel):
    """One ``requires_prior_authority`` edge keyed by the upstream AR's family slug.

    Edges are per-family slug (never version UUIDs) so a published AR survives
    version bumps of its prerequisites; the resolver walks each slug to the
    family's active version at eval time. ``required=False`` edges are advisory
    — they appear in the response chain but do not block.
    """
    prerequisite_family_slug: str
    required: bool = True
    display_order: int = 0
    notes: Optional[str] = None


class ResourceRefInput(BaseModel):
    """A typed pointer that backs one of an AR's canonical fields.

    ``field_path`` is a JSON-pointer-ish path on the AR row (``actor_identity``,
    ``object_id``, ``domain_context.brand``). The AR's own scalar column is
    the cached literal; this row records where that value came from and lets
    the resolver re-materialise it on demand.
    """
    field_path: str
    ref_type: str                              # literal | ontos_entity | mcp_tool
    literal_value: Optional[str] = None
    entity_type: Optional[str] = None          # business_concept | data_product | data_domain | …
    entity_id: Optional[str] = None            # IRI (for concepts) or entity UUID
    mcp_service_name: Optional[str] = None
    mcp_tool_name: Optional[str] = None
    mcp_params: Optional[Dict[str, Any]] = None
    mcp_result_pointer: Optional[str] = None


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
    # Credentials for this AR's mcp_tool refs: ``obo`` (caller's token) or ``app_sp``.
    resolver_auth: Optional[str] = None
    # Multi-domain assignment
    domain_ids: List[str] = Field(default_factory=list)
    primary_domain_id: Optional[str] = None
    # Ownership & scoping (parity with Data Products / Contracts)
    owner_team_id: Optional[str] = None
    project_id: Optional[str] = None
    # N-functional affirmation stakeholders
    affirmations: List[AffirmationInput] = Field(default_factory=list)
    # Author-configurable decision criteria (Compliance Checks)
    criteria: List[CriterionInput] = Field(default_factory=list)
    # Declarative prerequisite chain — this AR requires each listed slug's
    # family active version to resolve ``approved`` before deciding.
    prerequisites: Optional[List[PrerequisiteInput]] = None
    # Typed pointers backing the canonical fields (``actor_identity``,
    # ``object_id``, ``domain_context.*``). Omit the field to leave the
    # authored scalar as a plain literal.
    resource_refs: Optional[List[ResourceRefInput]] = None
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
    resolver_auth: Optional[str] = None
    domain_ids: Optional[List[str]] = None
    primary_domain_id: Optional[str] = None
    owner_team_id: Optional[str] = None
    project_id: Optional[str] = None
    affirmations: Optional[List[AffirmationInput]] = None
    criteria: Optional[List[CriterionInput]] = None
    prerequisites: Optional[List[PrerequisiteInput]] = None
    resource_refs: Optional[List[ResourceRefInput]] = None
    tags: Optional[List[AssignedTagCreate]] = None


class NewVersionRequest(BaseModel):
    """Request to snapshot an AR into a new version (mirrors Data Products)."""
    new_version: str = Field(..., description="The new semantic version string (e.g. 1.1.0, 2.0.0)")
    change_summary: Optional[str] = None


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


class FindAuthorityForConceptRequest(BaseModel):
    """Concept-based AR lookup: which active AR governs this concept here?"""
    concept_iri: str
    # Caller's domain context, compared against each AR's domain_context
    # (literal values and domain_context.* resource refs), e.g. {"market": "DE"}.
    context: Dict[str, Any] = Field(default_factory=dict)
    # Data-domain ids or names the decision belongs to.
    domains: List[str] = Field(default_factory=list)
    # Decision params used to dry-run each candidate's prerequisite chain.
    request: Dict[str, Any] = Field(default_factory=dict)


class ResolveResponse(BaseModel):
    verdict: str                                # approved|denied|no_authority|conflict
    reason: str
    relation_id: Optional[str] = None
    relation_slug: Optional[str] = None
    relation_version: Optional[str] = None
    dna_magnitude: Optional[float] = None
    dna_direction: Optional[str] = None
    # The prerequisite chain walked for this decision. Each entry is
    # ``{slug, version, verdict, reason, required}`` — present even when the
    # outer verdict is approved so agents can see which gates were cleared.
    prerequisite_chain: List[Dict[str, Any]] = Field(default_factory=list)
    # Typed pointers that were materialised during this resolve, one entry per
    # ``authority_resource_refs`` row the AR declared. Each entry carries
    # ``{field_path, ref_type, value, iri?, source}`` so agents (and the
    # provenance audit trail) know whether a scalar came from a literal, an
    # Ontos entity lookup, or an MCP tool call.
    resolved_refs: List[Dict[str, Any]] = Field(default_factory=list)
