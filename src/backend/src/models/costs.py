from __future__ import annotations
from typing import Optional, Dict
from uuid import UUID
from datetime import date, datetime

from pydantic import BaseModel, Field


class CostCenter(str):
    INFRASTRUCTURE = "INFRASTRUCTURE"
    HR = "HR"
    STORAGE = "STORAGE"
    MAINTENANCE = "MAINTENANCE"
    OTHER = "OTHER"


class CostItemBase(BaseModel):
    entity_id: str
    entity_type: str = Field(..., pattern=r"^(data_domain|data_product|data_contract|asset)$")
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    cost_center: str = Field(..., pattern=r"^(INFRASTRUCTURE|HR|STORAGE|MAINTENANCE|OTHER)$")
    custom_center_name: Optional[str] = Field(None, max_length=255)
    amount_cents: int = Field(..., ge=0)
    currency: str = Field("USD", min_length=3, max_length=3)
    start_month: date
    end_month: Optional[date] = None


class CostItemCreate(CostItemBase):
    pass


class CostItemUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    cost_center: Optional[str] = Field(None, pattern=r"^(INFRASTRUCTURE|HR|STORAGE|MAINTENANCE|OTHER)$")
    custom_center_name: Optional[str] = Field(None, max_length=255)
    amount_cents: Optional[int] = Field(None, ge=0)
    currency: Optional[str] = Field(None, min_length=3, max_length=3)
    start_month: Optional[date] = None
    end_month: Optional[date] = None


class CostItem(CostItemBase):
    id: UUID
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {
        "from_attributes": True
    }


class CostSummary(BaseModel):
    month: str  # YYYY-MM
    currency: str
    total_cents: int
    items_count: int
    by_center: Dict[str, int]


