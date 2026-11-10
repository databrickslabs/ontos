"""Pydantic models for maturity levels API."""
from datetime import datetime
from typing import Optional, List, Any, Dict
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
    entity_type: str = Field(
        "all",
        description=(
            "DataProduct, DataContract, Asset (table, view and metric view assets), or all "
            "(data products and data contracts; not assets)"
        ),
    )


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


class AssetDefaultsLoadResult(BaseModel):
    """Result of loading the default asset ladder: levels created, and the asset levels."""
    created: int = 0
    levels: List[MaturityLevelRead] = Field(default_factory=list)


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
    # Set when the gate failed for a known reason the UI translates
    # (e.g. the asset's Unity Catalog table couldn't be read)
    message_code: Optional[str] = None
    message_params: Optional[Dict[str, Any]] = None


class MaturityNotice(BaseModel):
    """Something that limited the evaluation, as a code the UI translates."""
    code: str
    message: str
    params: Dict[str, Any] = Field(default_factory=dict)


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
    notices: List[MaturityNotice] = Field(default_factory=list)


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


# ---------------------------------------------------------------------------
# Bulk evaluation of table and view assets
# ---------------------------------------------------------------------------

class MaturityBulkEvaluationRequest(BaseModel):
    """Scope and tuning of a bulk evaluation. Every field is optional."""
    catalog: Optional[str] = None
    schema_name: Optional[str] = None
    asset_types: Optional[List[str]] = None
    max_workers: Optional[int] = None
    batch_size: Optional[int] = None


class MaturityBulkEvaluationError(BaseModel):
    """An asset whose evaluation failed; the message is a code, never exception text."""
    asset_id: str
    code: str
    params: Dict[str, Any] = Field(default_factory=dict)


class MaturityBulkEvaluationRun(BaseModel):
    """Progress and summary of a bulk evaluation run."""
    id: str
    state: str  # running | completed | failed
    scope: Dict[str, Any]
    started_by: Optional[str] = None
    started_at: datetime
    finished_at: Optional[datetime] = None
    max_workers: int
    batch_size: int
    total: int = 0
    processed: int = 0
    evaluated: int = 0
    changed: int = 0
    skipped: Dict[str, int] = Field(default_factory=dict)
    error_count: int = 0
    errors: List[MaturityBulkEvaluationError] = Field(default_factory=list)
