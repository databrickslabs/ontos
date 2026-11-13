"""API models of Lifecycle Stage Groups (PRD #1208, slice #1213)."""
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

StageCategory = Literal['draft', 'review', 'active', 'deprecated', 'retired']
LifecycleEntityType = Literal['data_product', 'data_contract', 'asset']


class LifecycleStage(BaseModel):
    """A stage of a group. ``key`` is what entities store in ``status``."""
    key: str = Field(..., min_length=1, max_length=64, description="Immutable stage key")
    label: str = Field(..., min_length=1, max_length=255)
    category: StageCategory
    color: Optional[str] = Field(None, max_length=32)
    order: int = Field(0, description="Position in the stage table")
    is_initial: bool = Field(
        False, description="The stage a new entity, or an entity changing group, starts in",
    )

    model_config = {"from_attributes": True}


class LifecycleStageTransition(BaseModel):
    """An allowed move between two stages of a group, by stage key."""
    from_key: str
    to_key: str


class LifecycleStageGroupWrite(BaseModel):
    """A whole group: saving it replaces its stages and transitions."""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    entity_type: LifecycleEntityType
    is_default_for_type: bool = False
    stages: List[LifecycleStage] = Field(default_factory=list)
    transitions: List[LifecycleStageTransition] = Field(default_factory=list)


class LifecycleStageGroupRead(LifecycleStageGroupWrite):
    id: Optional[str] = Field(
        None, description="None only for a built-in default that isn't stored yet",
    )
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class LifecycleStageGroupSummary(BaseModel):
    id: Optional[str] = None
    name: str
    entity_type: LifecycleEntityType
    is_default_for_type: bool = False


class EntityLifecycleRead(BaseModel):
    """An entity's group, its current stage and the stages it may move to."""
    entity_type: LifecycleEntityType
    entity_id: str
    group: LifecycleStageGroupSummary
    status: str = Field(..., description="The stored stage key")
    stage: Optional[LifecycleStage] = Field(
        None, description="The current stage; None when the status is not a stage of the group",
    )
    allowed_transitions: List[LifecycleStage] = Field(default_factory=list)
    can_change_group: bool = Field(
        False, description="Whether the caller may change the entity's group (admin or owner)",
    )


class ChangeLifecycleGroupPayload(BaseModel):
    group_id: str = Field(..., description="The new Lifecycle Stage Group of the entity")
