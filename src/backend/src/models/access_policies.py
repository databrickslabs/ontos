"""API models for Access Policies (W3C ODRL 2.2): policies, audiences, asset collections, targets."""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.models.tags import AssignedTagCreate


class GovernedEntityInput(BaseModel):
    """Lifecycle + collaboration fields shared by every Access Policy entity on create."""
    name: str
    description: Optional[str] = None
    version: Optional[str] = Field(None, description="Semantic version; defaults to 1.0.0")
    owner_team_id: Optional[str] = None
    project_id: Optional[str] = None
    domain_ids: List[str] = Field(default_factory=list)
    primary_domain_id: Optional[str] = None
    tags: Optional[List[AssignedTagCreate]] = None
    # Create as a personal draft (visible to the author / project team only).
    personal_draft: bool = False


class GovernedEntityUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    owner_team_id: Optional[str] = None
    project_id: Optional[str] = None
    domain_ids: Optional[List[str]] = None
    primary_domain_id: Optional[str] = None
    tags: Optional[List[AssignedTagCreate]] = None
    change_summary: Optional[str] = None


SUBJECT_ENTITY_TYPES = ("data_product",)


class AccessPolicyCreate(GovernedEntityInput):
    policy_type: str = Field("Set", description="ODRL policy subclass: Set | Offer | Agreement")
    # The entity the policy is about, e.g. the Data Product an Offer states the terms for.
    subject_entity_type: Optional[str] = Field(None, description="data_product")
    subject_entity_id: Optional[str] = None
    conflict: str = Field("prohibit", description="ODRL conflict strategy: perm | prohibit | invalid")
    inherit_from: List[str] = Field(default_factory=list, description="Parent policy IRIs (inheritFrom)")
    # Rules in ODRL JSON (compact or atomic): {"permission": [...], "prohibition": [...], "obligation": [...]}
    rules: Dict[str, Any] = Field(default_factory=dict)


class AccessPolicyUpdate(GovernedEntityUpdate):
    policy_type: Optional[str] = None
    subject_entity_type: Optional[str] = None
    subject_entity_id: Optional[str] = None
    conflict: Optional[str] = None
    inherit_from: Optional[List[str]] = None
    rules: Optional[Dict[str, Any]] = None


class CollectionCreate(GovernedEntityInput):
    """Audience (PartyCollection) or Asset Collection."""
    members: List[str] = Field(default_factory=list)
    refinement: List[Dict[str, Any]] = Field(default_factory=list)


class CollectionUpdate(GovernedEntityUpdate):
    members: Optional[List[str]] = None
    refinement: Optional[List[Dict[str, Any]]] = None


class TargetCreate(GovernedEntityInput):
    """A compile + delivery target (Phase 4)."""
    key: str = Field(..., description="Stable key releases and the Grant Ledger reference (e.g. uc, uc-prod)")
    system: str = Field("uc", description="Adapter: uc (Unity Catalog)")
    # Non-secret connection settings only (credentials stay in secret scopes / app config).
    connection: Dict[str, Any] = Field(default_factory=dict)
    scope: List[str] = Field(default_factory=list, description="Securable prefixes managed; empty = all")
    delivery_modes: List[str] = Field(default_factory=list, description="Allowed Delivery Modes; empty = all enabled")
    reconcile_schedule: Optional[str] = Field(None, description="Drift reconciliation cron (report only)")
    drift_policy: str = "report"


class TargetUpdate(GovernedEntityUpdate):
    key: Optional[str] = None
    system: Optional[str] = None
    connection: Optional[Dict[str, Any]] = None
    scope: Optional[List[str]] = None
    delivery_modes: Optional[List[str]] = None
    reconcile_schedule: Optional[str] = None
    drift_policy: Optional[str] = None


class NewVersionRequest(BaseModel):
    new_version: str = Field(..., description="The new semantic version string (e.g. 1.1.0, 2.0.0)")
    change_summary: Optional[str] = None


class StatusChangeRequest(BaseModel):
    status: str
    comment: Optional[str] = None


class PolicyImportRequest(BaseModel):
    """An ODRL JSON-LD policy document to import as a new draft Access Policy."""
    document: Dict[str, Any]
    name: Optional[str] = None
    description: Optional[str] = None
    owner_team_id: Optional[str] = None
    project_id: Optional[str] = None
    domain_ids: List[str] = Field(default_factory=list)


class PolicyValidateRequest(BaseModel):
    policy_type: str = "Set"
    conflict: Optional[str] = "prohibit"
    inherit_from: List[str] = Field(default_factory=list)
    rules: Dict[str, Any] = Field(default_factory=dict)


class CheckAccessRequest(BaseModel):
    """Can ``principal`` perform ``action`` on ``asset``? Evaluated against active policies."""
    principal: str = Field(..., description="User email / SP id (typed refs like user:x also accepted)")
    action: str = Field(..., description="Profile action key, e.g. read, modify, ontos:manage")
    asset: str = Field(..., description="Asset ref, e.g. uc:main.sales.orders or an Ontos IRI")
    principal_groups: List[str] = Field(default_factory=list)
    principal_attributes: Dict[str, Any] = Field(default_factory=dict)
    asset_attributes: Dict[str, Any] = Field(default_factory=dict)
    context: Dict[str, Any] = Field(default_factory=dict)
    fulfilled_duties: List[str] = Field(default_factory=list)
    # Evaluate only these policies (any status) — "what-if" preview from the editor.
    policy_ids: Optional[List[str]] = None
    # Resolve Ontos Business Roles of the principal as ontos:businessRole (default on).
    resolve_business_roles: bool = True


# ------------------------------------------------------------- releases (Phase 2)

class ReleaseCreateRequest(BaseModel):
    target: str = Field("uc", description="Target platform (uc)")
    notes: Optional[str] = None


class ReleasePreviewRequest(BaseModel):
    target: str = "uc"


class ReleaseDeliverRequest(BaseModel):
    # Subset of the Delivery Modes enabled in Settings (direct | indirect | manual); default = all enabled.
    modes: Optional[List[str]] = None


class ReleaseConfirmRequest(BaseModel):
    comment: Optional[str] = None


class RevokeExpiredRequest(BaseModel):
    target: str = "uc"


class DutyFulfillRequest(BaseModel):
    action: str = Field(..., description="Duty action, e.g. ontos:acknowledgeTerms")
    note: Optional[str] = None
