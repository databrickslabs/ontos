from enum import Enum
from typing import List, Optional
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, Field


class OwnerObjectType(str, Enum):
    """Types of objects that can have business owners."""
    DATA_PRODUCT = "data_product"
    DATA_CONTRACT = "data_contract"
    DATASET = "dataset"
    DATA_DOMAIN = "data_domain"
    BUSINESS_TERM = "business_term"
    ASSET = "asset"
    TAG = "tag"


# --- Business Owner Models ---
class BusinessOwnerBase(BaseModel):
    object_type: OwnerObjectType = Field(..., description="Type of the owned object")
    object_id: str = Field(..., description="ID of the owned object")
    user_email: str = Field(..., description="Owner's email / identifier")
    user_name: Optional[str] = Field(None, description="Cached display name")
    role_id: UUID = Field(..., description="Business role ID")


class BusinessOwnerCreate(BusinessOwnerBase):
    pass


class BusinessOwnerUpdate(BaseModel):
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    role_id: Optional[UUID] = None
    is_active: Optional[bool] = None
    removal_reason: Optional[str] = Field(None, description="Reason for removing the owner (sets is_active=False)")


class BusinessOwnerRemove(BaseModel):
    """Model for removing (deactivating) an owner with an optional reason."""
    removal_reason: Optional[str] = Field(None, description="Reason for the ownership change")


class BusinessOwnerRead(BusinessOwnerBase):
    id: UUID
    is_active: bool = True
    role_name: Optional[str] = Field(None, description="Resolved business role name")
    assigned_at: datetime
    removed_at: Optional[datetime] = None
    removal_reason: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BusinessOwnerHistory(BaseModel):
    """View of all owners (current and past) for an object."""
    object_type: OwnerObjectType
    object_id: str
    current_owners: List[BusinessOwnerRead] = Field(default_factory=list)
    previous_owners: List[BusinessOwnerRead] = Field(default_factory=list)


# --- Bulk Import Models ---

class ImportTeamMemberMapping(BaseModel):
    """Single team member to import as a business owner."""
    username: str = Field(..., description="Username/email from the ODCS/ODPS team or Ontos Team member")
    name: Optional[str] = Field(None, description="Display name (optional)")
    role_id: UUID = Field(..., description="Business role ID to assign")


class ImportFromTeamRequest(BaseModel):
    """Bulk import request: create Business Owner records from team members."""
    object_type: OwnerObjectType = Field(..., description="Type of the target object")
    object_id: str = Field(..., description="ID of the target object")
    members: List[ImportTeamMemberMapping] = Field(..., min_length=1, description="Team members to import as owners")


class ImportFromTeamResponse(BaseModel):
    """Result of bulk import."""
    created: int = Field(0, description="Number of new owner records created")
    skipped: int = Field(0, description="Number skipped (already assigned)")
    errors: List[str] = Field(default_factory=list, description="Any error messages")
