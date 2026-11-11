"""API models for metric view definition change requests (#1124 phase 3)."""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from src.common.metric_views import MAX_DEFINITION_LENGTH

ChangeRequestStatus = Literal[
    'draft', 'in_review', 'approved', 'rejected', 'delivered', 'failed', 'cancelled',
]
# Requests that can still change (a decision or a delivery is to come)
OPEN_STATUSES = ('draft', 'in_review', 'approved')


class MetricViewChangeRequestCreate(BaseModel):
    """A draft: the proposed YAML and why."""
    definition: str = Field(..., min_length=1, max_length=MAX_DEFINITION_LENGTH)
    justification: Optional[str] = Field(None, max_length=4000)


class CodedNote(BaseModel):
    """A pre-check warning or a delivery error: a code the UI translates, with its params."""
    code: str
    message: str
    params: Dict[str, Any] = Field(default_factory=dict)


class MetricViewChangeRequestRead(BaseModel):
    id: UUID
    asset_id: UUID
    metric_view_fqn: str
    status: ChangeRequestStatus
    justification: Optional[str] = None
    base_digest: str
    proposed_digest: str
    proposed_definition: str
    warnings: List[CodedNote] = Field(default_factory=list)
    # Why the delivery failed (status ``failed``)
    error: Optional[CodedNote] = None
    delivery_mode: Optional[str] = None
    delivery_reference: Optional[str] = None
    workflow_execution_id: Optional[str] = None
    requested_by: str
    decided_by: Optional[str] = None
    decision_message: Optional[str] = None
    created_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    decided_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    # When Unity Catalog was read back with this definition (it became the baseline)
    applied_at: Optional[datetime] = None
    # The DDL that delivers the request
    ddl: Optional[str] = None


class MetricViewChangeRequestDetail(MetricViewChangeRequestRead):
    """One request with its base definition and both parsed specs, for the review."""
    base_definition: str
    base_metric_view: Optional[Dict[str, Any]] = None
    proposed_metric_view: Optional[Dict[str, Any]] = None
