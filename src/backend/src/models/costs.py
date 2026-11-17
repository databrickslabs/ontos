from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class CostCenter(str):
    INFRASTRUCTURE = "INFRASTRUCTURE"
    HR = "HR"
    STORAGE = "STORAGE"
    MAINTENANCE = "MAINTENANCE"
    OTHER = "OTHER"


class CostItemBase(BaseModel):
    entity_id: str
    entity_type: str = Field(..., pattern=r"^(data_domain|data_product|data_contract|asset)$")
    title: str | None = Field(None, max_length=255)
    description: str | None = Field(None, max_length=2000)
    cost_center: str = Field(..., pattern=r"^(INFRASTRUCTURE|HR|STORAGE|MAINTENANCE|OTHER)$")
    custom_center_name: str | None = Field(None, max_length=255)
    amount_cents: int = Field(..., ge=0)
    currency: str = Field("USD", min_length=3, max_length=3)
    start_month: date
    end_month: date | None = None

    @field_validator("cost_center", mode="before")
    @classmethod
    def normalize_cost_center(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class CostItemCreate(CostItemBase):
    pass


class CostItemUpdate(BaseModel):
    title: str | None = Field(None, max_length=255)
    description: str | None = Field(None, max_length=2000)
    cost_center: str | None = Field(
        None, pattern=r"^(INFRASTRUCTURE|HR|STORAGE|MAINTENANCE|OTHER)$"
    )
    custom_center_name: str | None = Field(None, max_length=255)
    amount_cents: int | None = Field(None, ge=0)
    currency: str | None = Field(None, min_length=3, max_length=3)
    start_month: date | None = None
    end_month: date | None = None

    @field_validator("cost_center", mode="before")
    @classmethod
    def normalize_cost_center(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class CostItem(CostItemBase):
    id: UUID
    created_by: str | None = None
    updated_by: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CostSummary(BaseModel):
    month: str  # YYYY-MM
    currency: str
    total_cents: int
    items_count: int
    by_center: dict[str, int]
