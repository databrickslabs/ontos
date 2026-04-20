from enum import Enum
from typing import Optional
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, Field


class BusinessRoleStatus(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class BusinessRoleCategory(str, Enum):
    GOVERNANCE = "governance"
    TECHNICAL = "technical"
    BUSINESS = "business"
    OPERATIONAL = "operational"


# --- Business Role Models ---
class BusinessRoleBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Unique role name (e.g., Data Owner, Domain Owner)")
    description: Optional[str] = Field(None, description="Human-readable description")
    category: Optional[BusinessRoleCategory] = Field(None, description="Role category")
    is_system: bool = Field(False, description="Whether this is a built-in role")
    status: BusinessRoleStatus = Field(BusinessRoleStatus.ACTIVE, description="Lifecycle status")
    is_approver: bool = Field(False, description="Whether this role appears in workflow approver/recipient dropdowns")


class BusinessRoleCreate(BusinessRoleBase):
    pass


class BusinessRoleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    category: Optional[BusinessRoleCategory] = None
    is_system: Optional[bool] = None
    status: Optional[BusinessRoleStatus] = None
    is_approver: Optional[bool] = None


class BusinessRoleRead(BusinessRoleBase):
    id: UUID
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
