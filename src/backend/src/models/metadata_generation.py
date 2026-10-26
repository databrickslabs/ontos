"""API models for Metadata Generation (Generation Runs and Description Suggestions)."""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class GenerationRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    # Job finished; its results are being loaded into suggestions
    INGESTING = "ingesting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_RUN_STATUSES = {
    GenerationRunStatus.COMPLETED.value,
    GenerationRunStatus.FAILED.value,
    GenerationRunStatus.CANCELLED.value,
}


class SuggestionStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    APPLIED = "applied"
    CONFLICT = "conflict"
    NOT_APPLICABLE = "not_applicable"
    SUPERSEDED = "superseded"


class CommentStyle(str, Enum):
    CONCISE = "concise"
    STANDARD = "standard"
    DETAILED = "detailed"


class SelectionItem(BaseModel):
    """One picked UC object; a catalog or schema stands for all its tables."""
    type: Literal["catalog", "schema", "table"]
    fqn: str = Field(..., min_length=1)


class StartRunRequest(BaseModel):
    selection: List[SelectionItem] = Field(..., min_length=1)
    comment_style: CommentStyle = CommentStyle.STANDARD
    # Serving endpoint; defaults to the app's LLM_ENDPOINT
    model: Optional[str] = None
    regenerate_existing: bool = False
    auto_submit: bool = False
    # Reviewer of the auto-submitted review; defaults to a Data Steward
    reviewer_email: Optional[EmailStr] = None


class StartRunResponse(BaseModel):
    run_id: str
    status: GenerationRunStatus


class SuggestionCounts(BaseModel):
    pending: int = 0
    accepted: int = 0
    rejected: int = 0
    applied: int = 0
    conflict: int = 0
    not_applicable: int = 0
    superseded: int = 0


class GenerationRunSummary(BaseModel):
    run_id: str
    user_id: str
    status: GenerationRunStatus
    progress_message: Optional[str] = None
    error: Optional[str] = None
    selection: List[SelectionItem]
    options: Dict = Field(default_factory=dict)
    job_run_id: Optional[str] = None
    suggestion_count: int = 0
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class DescriptionSuggestion(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    kind: str
    object_type: str
    table_fqn: str
    column_name: Optional[str] = None
    base_text: Optional[str] = None
    proposed_text: str
    edited_text: Optional[str] = None
    status: SuggestionStatus
    review_request_id: Optional[str] = None
    reviewed_asset_id: Optional[str] = None
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    review_comment: Optional[str] = None
    applied_by: Optional[str] = None
    applied_at: Optional[datetime] = None
    error: Optional[str] = None


class GenerationRunDetail(GenerationRunSummary):
    counts: SuggestionCounts = Field(default_factory=SuggestionCounts)
    # Pending suggestions that can be submitted for review
    unsubmitted: int = 0
    # Asset Reviews holding the run's suggestions
    review_request_ids: List[str] = Field(default_factory=list)


class RunListResponse(BaseModel):
    runs: List[GenerationRunSummary]


class SuggestionListResponse(BaseModel):
    suggestions: List[DescriptionSuggestion]
    total: int


class SubmitReviewRequest(BaseModel):
    """POST /runs/{run_id}/review: put the run's pending suggestions up for review."""
    # Defaults to a Data Steward other than the requester
    reviewer_email: Optional[EmailStr] = None
    notes: Optional[str] = Field(None, max_length=2000)


class SubmitReviewResponse(BaseModel):
    run_id: str
    review_request_id: str
    reviewer_email: str
    suggestion_count: int


class SuggestionDecision(BaseModel):
    """A reviewer's decision on one Description Suggestion.

    ``accept`` approves it (with ``edited_text`` if the reviewer changed the
    description), ``reject`` closes it, ``clarify`` sends it back to pending
    so it can be regenerated or put up for review again.
    """
    id: str
    decision: Literal["accept", "reject", "clarify"]
    edited_text: Optional[str] = Field(None, max_length=10000)
    comment: Optional[str] = Field(None, max_length=2000)


class SuggestionDecisionBatch(BaseModel):
    decisions: List[SuggestionDecision] = Field(..., min_length=1, max_length=1000)


class SuggestionDecisionResult(BaseModel):
    accepted: int = 0
    rejected: int = 0
    clarify: int = 0
    skipped: int = 0
    errors: List[str] = Field(default_factory=list)
