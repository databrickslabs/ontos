"""Pydantic models for the Compliance Templates API.

Slice 1 (#706) stands up the full read/write shape with a single value type
(String). The ``ComplianceValueType`` enum already enumerates every planned
type so later slices add typed handling without reshaping the API.
"""
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ComplianceValueType(str, Enum):
    """Supported field value types. Only STRING is handled in slice 1."""
    STRING = "string"
    NUMERIC = "numeric"
    ENUM = "enum"
    MULTI_ENUM = "multi_enum"
    DATE = "date"
    RANGE = "range"
    BOOLEAN = "boolean"


# ----- Fields -------------------------------------------------------------

class ComplianceFieldBase(BaseModel):
    group_title: str = Field("", max_length=255)
    group_order: int = Field(0, ge=0)
    key: str = Field(..., min_length=1, max_length=255)
    label: str = Field(..., min_length=1, max_length=255)
    reference_id: str = Field(..., min_length=1, max_length=255)
    value_type: ComplianceValueType = ComplianceValueType.STRING
    possible_values: list[str] | None = None
    default_value: Any | None = None
    hint_text: str | None = None
    is_mandatory: bool = False
    field_order: int = Field(0, ge=0)


class ComplianceFieldCreate(ComplianceFieldBase):
    pass


class ComplianceFieldUpdate(BaseModel):
    group_title: str | None = Field(None, max_length=255)
    group_order: int | None = Field(None, ge=0)
    key: str | None = Field(None, min_length=1, max_length=255)
    label: str | None = Field(None, min_length=1, max_length=255)
    reference_id: str | None = Field(None, min_length=1, max_length=255)
    value_type: ComplianceValueType | None = None
    possible_values: list[str] | None = None
    default_value: Any | None = None
    hint_text: str | None = None
    is_mandatory: bool | None = None
    field_order: int | None = Field(None, ge=0)


class ComplianceFieldRead(ComplianceFieldBase):
    id: UUID
    template_id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


# ----- Templates ----------------------------------------------------------

class ComplianceTemplateBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    entity_type: str = Field(..., min_length=1, max_length=100)


class ComplianceTemplateCreate(ComplianceTemplateBase):
    # Fields may be supplied inline on create, or added later via the field API.
    fields: list[ComplianceFieldCreate] = Field(default_factory=list)


class ComplianceTemplateUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None


class ComplianceTemplateRead(ComplianceTemplateBase):
    id: UUID
    scope_type: str
    scope_id: str
    is_active: bool
    version: int
    created_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    fields: list[ComplianceFieldRead] = Field(default_factory=list)

    model_config = {"from_attributes": True}


# ----- Per-entity values --------------------------------------------------

class ComplianceValueRead(BaseModel):
    field_id: UUID
    reference_id: str
    entity_type: str
    entity_id: str
    value: Any | None = None
    filled_by: str | None = None
    filled_at: datetime | None = None

    model_config = {"from_attributes": True}


class ComplianceValueWrite(BaseModel):
    """A single field's value in a replace-all write."""
    field_id: UUID
    value: Any | None = None


class ComplianceValuesReplace(BaseModel):
    """Replace-all write payload: the materialization event for an entity."""
    values: list[ComplianceValueWrite] = Field(default_factory=list)


class EntityComplianceRead(BaseModel):
    """Composed read: the active template, its fields, and this entity's values.

    ``template`` is null when no template is active for the entity type — the
    frontend hides the fill button in that case.
    """
    template: ComplianceTemplateRead | None = None
    fields: list[ComplianceFieldRead] = Field(default_factory=list)
    values: list[ComplianceValueRead] = Field(default_factory=list)


class ComplianceCompletenessRead(BaseModel):
    """Result of the completeness check for an entity.

    ``applicable`` is False when no template is active (nothing to complete).
    ``passed`` is True when all mandatory fields are satisfied; ``missing`` and
    ``messages`` describe unsatisfied mandatory fields.
    """
    applicable: bool
    passed: bool
    missing: list[str] = Field(default_factory=list)
    messages: list[str] = Field(default_factory=list)
