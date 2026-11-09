"""Pydantic models for the data product types API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Lower-case words joined by hyphens, like the seeded keys (`source-aligned`).
KEY_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"


class DataProductTypeCreate(BaseModel):
    key: str = Field(..., min_length=1, max_length=100, pattern=KEY_PATTERN)
    label: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    icon: str | None = Field(None, max_length=100)
    color: str | None = Field(None, max_length=50)
    # Appended after the last type when omitted.
    sort_order: int | None = Field(None, ge=0)
    is_active: bool = True
    is_default: bool = False


class DataProductTypeUpdate(BaseModel):
    """Fields an admin can change. `key` is immutable, so it's rejected here."""

    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    icon: str | None = Field(None, max_length=100)
    color: str | None = Field(None, max_length=50)
    sort_order: int | None = Field(None, ge=0)
    is_active: bool | None = None
    is_default: bool | None = None


class DataProductTypeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key: str
    label: str
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    sort_order: int
    is_active: bool
    is_default: bool
    is_imported: bool
    # One of the five types every install starts with; these can't be deleted.
    is_seeded: bool = False
    # Number of data products using this type; a type in use can't be deleted.
    usage_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DataProductTypeOrder(BaseModel):
    id: UUID
    sort_order: int = Field(..., ge=0)


class DataProductTypeReorder(BaseModel):
    types: list[DataProductTypeOrder] = Field(..., min_length=1)
