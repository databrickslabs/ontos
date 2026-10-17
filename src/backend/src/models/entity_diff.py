"""API models for version diffs of versioned entities (PRD #1086)."""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

BumpLabel = Literal["major", "minor", "patch", "none"]


class EntityVersionRef(BaseModel):
    id: str
    name: Optional[str] = None
    version: Optional[str] = None
    status: Optional[str] = None


class EntityDiffChange(BaseModel):
    path: str = Field(..., description="Concrete path, e.g. schema[orders].properties[id].logicalType")
    op: Literal["added", "removed", "modified"]
    old: Any = None
    new: Any = None
    bump: BumpLabel
    rule_id: str = Field(..., description="Rule that classified the change ('default' if none matched)")
    message: str


class EntityDiffResponse(BaseModel):
    entity_type: Literal["data_contract", "data_product"]
    base: EntityVersionRef
    target: EntityVersionRef
    changes: List[EntityDiffChange]
    counts: Dict[BumpLabel, int]
    suggested_bump: BumpLabel = Field(..., description="Highest bump across all changes")
    suggested_version: str = Field(..., description="base.version bumped by suggested_bump")
    version_consistent: Optional[bool] = Field(
        None,
        description="Whether target.version bumps base.version by at least suggested_bump; "
                    "null when it can't be judged (unparseable, or target not newer than base)",
    )
    unified_diff: str = Field(..., description="Unified diff of the two normalized file-model documents (YAML)")
