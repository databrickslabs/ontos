"""Pydantic models for maturity levels API."""
from datetime import datetime
from typing import Optional, List, Any
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Maturity Level CRUD
# ---------------------------------------------------------------------------

class MaturityLevelBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    icon: Optional[str] = Field(None, max_length=100)
    color: Optional[str] = Field(None, max_length=50)
    entity_type: str = Field("all", description="DataProduct, DataContract, or all")


class MaturityLevelCreate(MaturityLevelBase):
    level_order: int = Field(..., ge=1)


class MaturityLevelUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    icon: Optional[str] = Field(None, max_length=100)
    color: Optional[str] = Field(None, max_length=50)
    entity_type: Optional[str] = None
    level_order: Optional[int] = Field(None, ge=1)


class MaturityGateRead(BaseModel):
    id: UUID
    maturity_level_id: UUID
    compliance_policy_id: str
    compliance_policy_name: Optional[str] = None
    compliance_policy_rule: Optional[str] = None
    required: bool = True
    display_order: int = 0
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class MaturityLevelRead(MaturityLevelBase):
    id: UUID
    level_order: int
    gates: List[MaturityGateRead] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class MaturityLevelReorder(BaseModel):
    """Bulk reorder: list of id -> new level_order mappings."""
    levels: list[dict] = Field(
        ...,
        description="List of {id, level_order} dicts",
        examples=[[{"id": "...", "level_order": 1}, {"id": "...", "level_order": 2}]],
    )


# ---------------------------------------------------------------------------
# Maturity Gate CRUD
# ---------------------------------------------------------------------------

class MaturityGateCreate(BaseModel):
    compliance_policy_id: str = Field(..., description="ID of the compliance policy to gate on")
    required: bool = Field(True, description="If False, treated as advisory (warn, not block)")
    display_order: int = Field(0, ge=0)


# ---------------------------------------------------------------------------
# Evaluation Results
# ---------------------------------------------------------------------------

class GateResult(BaseModel):
    """Result of evaluating a single gate."""
    gate_id: str
    policy_id: str
    policy_name: str
    required: bool
    passed: bool
    message: Optional[str] = None


class LevelResult(BaseModel):
    """Evaluation result for a single maturity level."""
    level_order: int
    level_name: str
    level_icon: Optional[str] = None
    level_color: Optional[str] = None
    achieved: bool
    gates: List[GateResult] = Field(default_factory=list)


class MaturityReport(BaseModel):
    """Full maturity evaluation report for an entity."""
    entity_type: str
    entity_id: str
    entity_name: Optional[str] = None
    achieved_level_order: Optional[int] = None
    achieved_level_name: Optional[str] = None
    total_levels: int = 0
    gates_passed: int = 0
    gates_total: int = 0
    levels: List[LevelResult] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=datetime.utcnow)
    evaluated_by: Optional[str] = None


class MaturitySnapshotRead(BaseModel):
    """Historical maturity snapshot."""
    id: UUID
    entity_type: str
    entity_id: str
    achieved_level_order: Optional[int] = None
    achieved_level_name: Optional[str] = None
    total_levels: int = 0
    gates_passed: int = 0
    gates_total: int = 0
    gate_results_json: Optional[str] = None
    evaluated_at: datetime
    evaluated_by: Optional[str] = None

    model_config = {"from_attributes": True}
