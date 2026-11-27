"""API models of the delivery outbox (Settings > Delivery Modes, re-delivery)."""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.models.import_results import ImportDeliveryResult

DeliveryOutboxStatus = Literal["pending", "delivered", "failed"]


class DeliveryOutboxRow(BaseModel):
    """One change to deliver through one mode, and its last outcome."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    entity_type: str
    entity_id: str
    entity_name: Optional[str] = Field(None, description="Name of the entity, when it still exists")
    change_type: str
    mode: str
    status: DeliveryOutboxStatus
    code: Optional[str] = Field(
        None, description="Code of the last failure, or why nothing was done")
    params: Optional[Dict[str, Any]] = None
    attempts: int = 0
    max_attempts: int = Field(..., description="Attempts after which a row stays failed")
    next_attempt_at: Optional[datetime] = None
    last_attempt_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    queued_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class DeliveryOutboxList(BaseModel):
    rows: List[DeliveryOutboxRow] = Field(default_factory=list)
    counts: Dict[str, int] = Field(default_factory=dict, description="Rows per status listed")


class RedeliverResult(BaseModel):
    """The entity's rows after the attempt that followed ``redeliver``."""

    entity_type: str
    entity_id: str
    delivery: Optional[ImportDeliveryResult] = None
    rows: List[DeliveryOutboxRow] = Field(default_factory=list)
    in_progress_row_ids: List[str] = Field(
        default_factory=list,
        description="Open rows left alone: another delivery attempt holds them")
