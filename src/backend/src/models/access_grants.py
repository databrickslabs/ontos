"""
Pydantic models for Access Grants API.

Models for creating, reading, and managing time-limited access grants.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AccessGrantRequestStatus(str, Enum):
    """Status of an access grant request."""
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class AccessGrantStatus(str, Enum):
    """Status of an access grant."""
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class PermissionLevel(str, Enum):
    """Permission level for access grants."""
    READ = "READ"
    WRITE = "WRITE"
    MANAGE = "MANAGE"


# ============================================================================
# Access Grant Request Models
# ============================================================================

class AccessGrantRequestCreate(BaseModel):
    """Request payload for creating a new access grant request.

    Path-B portable wizard launch: when a ``for_request_access`` approval
    workflow is configured, the FE captures the wizard's ``user_action`` fields
    and posts them in ``wizard_data``. ``model_config = extra='allow'`` keeps
    the surface flexible for any other deployment-specific fields the workflow
    author defines without requiring per-customer model edits. The
    ``AccessGrantsManager`` then forwards ``wizard_data`` into the
    ``on_request_access`` trigger's ``entity_data`` so Process workflow steps
    can reference values via ``${entity.<field_id>}``.
    """
    model_config = ConfigDict(extra="allow")

    entity_type: str = Field(..., description="Type of asset (data_product, dataset, table, etc.)")
    entity_id: str = Field(..., description="ID of the asset")
    entity_name: Optional[str] = Field(None, description="Display name of the asset")
    requested_duration_days: int = Field(..., ge=1, le=365, description="Requested access duration in days")
    permission_level: PermissionLevel = Field(default=PermissionLevel.READ, description="Level of access requested")
    reason: Optional[str] = Field(None, min_length=10, description="Justification for the request")
    wizard_data: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Custom fields collected from the configured for_request_access "
            "approval wizard's user_action steps. Forwarded into the "
            "on_request_access trigger's entity_data so Process workflows can "
            "reference values via ${entity.<field_id>}."
        ),
    )

    @field_validator('entity_type')
    @classmethod
    def validate_entity_type(cls, v: str) -> str:
        allowed_types = ['data_product', 'dataset', 'data_contract', 'table', 'schema', 'catalog']
        if v.lower() not in allowed_types:
            # Allow custom types but normalize
            pass
        return v.lower()


class AccessGrantRequestResponse(BaseModel):
    """Response model for an access grant request."""
    id: UUID
    requester_email: str
    entity_type: str
    entity_id: str
    entity_name: Optional[str] = None
    requested_duration_days: int
    permission_level: str
    reason: Optional[str] = None
    status: AccessGrantRequestStatus
    created_at: datetime
    handled_at: Optional[datetime] = None
    handled_by: Optional[str] = None
    admin_message: Optional[str] = None

    class Config:
        from_attributes = True


class AccessGrantRequestList(BaseModel):
    """Response model for listing access grant requests."""
    requests: List[AccessGrantRequestResponse]
    total: int


# ============================================================================
# Access Grant Handle Models
# ============================================================================

class AccessGrantHandlePayload(BaseModel):
    """Payload for handling (approve/deny) an access grant request."""
    request_id: UUID = Field(..., description="ID of the request to handle")
    approved: bool = Field(..., description="Whether to approve the request")
    granted_duration_days: Optional[int] = Field(
        None, 
        ge=1, 
        le=365, 
        description="Actual duration to grant (may differ from requested)"
    )
    permission_level: Optional[PermissionLevel] = Field(
        None, 
        description="Permission level to grant (may differ from requested)"
    )
    message: Optional[str] = Field(None, description="Message to the requester")

    @field_validator('granted_duration_days')
    @classmethod
    def validate_duration_on_approve(cls, v: Optional[int], info) -> Optional[int]:
        # If approving, duration is required
        if info.data.get('approved') and v is None:
            raise ValueError("granted_duration_days is required when approving a request")
        return v


# ============================================================================
# Access Grant Models
# ============================================================================

class AccessGrantResponse(BaseModel):
    """Response model for an access grant."""
    id: UUID
    request_id: Optional[UUID] = None
    grantee_email: str
    entity_type: str
    entity_id: str
    entity_name: Optional[str] = None
    permission_level: str
    granted_at: datetime
    expires_at: datetime
    granted_by: Optional[str] = None
    status: AccessGrantStatus
    revoked_at: Optional[datetime] = None
    revoked_by: Optional[str] = None
    revocation_reason: Optional[str] = None
    days_until_expiry: Optional[int] = None
    is_active: bool = True

    class Config:
        from_attributes = True


class AccessGrantList(BaseModel):
    """Response model for listing access grants."""
    grants: List[AccessGrantResponse]
    total: int


class AccessGrantRevokePayload(BaseModel):
    """Payload for revoking an access grant."""
    reason: Optional[str] = Field(None, description="Reason for revocation")


class AccessGrantCreateDirect(BaseModel):
    """Payload for creating an access grant directly (admin use)."""
    grantee_email: str = Field(..., description="Email of the user to grant access")
    entity_type: str = Field(..., description="Type of asset")
    entity_id: str = Field(..., description="ID of the asset")
    entity_name: Optional[str] = Field(None, description="Display name of the asset")
    permission_level: PermissionLevel = Field(default=PermissionLevel.READ, description="Level of access")
    duration_days: int = Field(..., ge=1, le=365, description="Duration of access in days")


# ============================================================================
# Duration Configuration Models
# ============================================================================

class DurationRangeConfig(BaseModel):
    """Range-based duration configuration."""
    min: int = Field(1, ge=0, description="Minimum allowed duration in days")
    max: int = Field(90, ge=1, le=365, description="Maximum allowed duration in days")


class AccessGrantDurationConfigCreate(BaseModel):
    """Payload for creating/updating duration configuration."""
    entity_type: str = Field(..., description="Entity type this config applies to")
    allowed_durations: Union[List[int], DurationRangeConfig] = Field(
        ..., 
        description="Allowed durations: list of days [30, 60, 90] or range {min: 1, max: 90}"
    )
    default_duration: int = Field(30, ge=1, le=365, description="Default duration in days")
    expiry_workflow_id: Optional[str] = Field(None, description="Process workflow to trigger on expiry")
    expiry_warning_days: int = Field(7, ge=1, le=30, description="Days before expiry to send warning")
    allow_renewal: bool = Field(True, description="Whether to allow renewal requests")
    max_renewals: Optional[int] = Field(3, ge=0, description="Maximum number of renewals allowed")

    @field_validator('allowed_durations')
    @classmethod
    def validate_allowed_durations(cls, v):
        if isinstance(v, list):
            if not v:
                raise ValueError("allowed_durations list cannot be empty")
            for d in v:
                if not isinstance(d, int) or d < 1 or d > 365:
                    raise ValueError("Each duration must be an integer between 1 and 365")
        return v


class AccessGrantDurationConfigResponse(BaseModel):
    """Response model for duration configuration."""
    id: UUID
    entity_type: str
    allowed_durations: Union[List[int], Dict[str, int]]
    default_duration: int
    expiry_workflow_id: Optional[str] = None
    expiry_warning_days: int
    allow_renewal: bool
    max_renewals: Optional[int] = None
    created_at: Optional[datetime] = None  # Optional for default/unpersisted configs
    updated_at: Optional[datetime] = None  # Optional for default/unpersisted configs
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    duration_options: List[int] = Field(default_factory=list, description="Computed list of available options")

    class Config:
        from_attributes = True


class AccessGrantDurationConfigList(BaseModel):
    """Response model for listing duration configurations."""
    configs: List[AccessGrantDurationConfigResponse]
    total: int


# ============================================================================
# Summary and Statistics Models
# ============================================================================

class AccessGrantSummary(BaseModel):
    """Summary of access grants for an entity."""
    entity_type: str
    entity_id: str
    active_grants_count: int
    pending_requests_count: int
    expiring_soon_count: int  # Grants expiring within warning period
    total_grants_count: int


class UserAccessGrantsSummary(BaseModel):
    """Summary of a user's access grants."""
    email: str
    active_grants: List[AccessGrantResponse]
    pending_requests: List[AccessGrantRequestResponse]
    expiring_soon: List[AccessGrantResponse]

