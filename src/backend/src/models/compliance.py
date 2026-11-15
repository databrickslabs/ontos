from datetime import datetime
from typing import List, Optional, Any
from uuid import UUID

from pydantic import BaseModel, Field


class CompliancePolicyCreate(BaseModel):
    """Payload accepted by POST /api/compliance/policies. id, compliance score, and timestamps are server-generated."""
    name: str = Field(..., description="Name of the compliance policy")
    description: str = Field(..., description="Description of what the policy checks")
    failure_message: Optional[str] = Field(default=None, description="Human-readable message shown when policy fails")
    rule: str = Field(..., description="Policy rule using the compliance DSL")
    is_active: bool = Field(default=True, description="Whether the policy is active")
    severity: str = Field(default="medium", description="Severity level: low, medium, high")
    category: str = Field(default="general", description="Category of the policy")


class CompliancePolicy(BaseModel):
    id: UUID = Field(..., description="Unique identifier for the policy (UUID)")
    name: str = Field(..., description="Name of the compliance policy")
    description: str = Field(..., description="Description of what the policy checks")
    failure_message: Optional[str] = Field(default=None, description="Human-readable message shown when policy fails")
    rule: str = Field(..., description="Policy rule using the compliance DSL")
    compliance: float = Field(default=0.0, description="Current compliance score (0-100)")
    history: List[float] = Field(default_factory=list, description="Historical compliance scores")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    is_active: bool = Field(default=True, description="Whether the policy is active")
    severity: str = Field(default="medium", description="Severity level: low, medium, high")
    category: str = Field(default="general", description="Category of the policy")


class ComplianceRun(BaseModel):
    id: str
    policy_id: str
    status: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    success_count: int
    failure_count: int
    score: float
    error_message: Optional[str] = None
    error_code: Optional[str] = None  # translated by the UI; error_message is the fallback
    error_params: Optional[dict] = None
    warning_code: Optional[str] = None  # what a finished run reports; translated by the UI
    warning_params: Optional[dict] = None
    # LLM_CHECK model calls of the run, and verdicts read from the cache (None: not counted)
    llm_calls: Optional[int] = None
    llm_cache_hits: Optional[int] = None
    # Entities an LLM_CHECK couldn't judge: in neither count nor the score
    not_evaluated_count: Optional[int] = None


class ComplianceResult(BaseModel):
    id: str
    run_id: str
    object_type: str
    object_id: str
    object_name: Optional[str] = None
    passed: bool
    not_evaluated: bool = False  # no verdict (LLM_CHECK couldn't run); passed is False
    message: Optional[str] = None
    details_json: Optional[str] = None
    created_at: datetime


class ComplianceRunRequest(BaseModel):
    mode: str = Field(default="async", description="inline or async")
    limit: Optional[int] = Field(default=None, description="Optional limit of objects to check")
    dry_run: bool = Field(default=False)


class ComplianceResultsResponse(BaseModel):
    run: ComplianceRun
    results: List[ComplianceResult]
    only_failed: bool = False
    total: int


class LlmCheckOutcome(BaseModel):
    """One LLM_CHECK: the model's verdict and reason, or the code of why there is none."""
    criterion: str
    passed: bool
    reason: str = ''
    code: Optional[str] = Field(default=None, description="Error code; None for a model verdict")
    cached: bool = False


class LlmCheckTestRequest(BaseModel):
    """POST /api/compliance/llm-check/test: try a rule on one entity before saving it."""
    rule: str = Field(..., min_length=1, description="Rule in the compliance DSL")
    entity: Optional[str] = Field(
        default=None,
        description="Name or id of the entity to try it on; default: the first match",
    )


class LlmCheckTestResponse(BaseModel):
    entity_type: str
    entity_id: Optional[str] = None
    entity_name: Optional[str] = None
    passed: bool
    error_code: Optional[str] = Field(
        default=None, description="Why the rule failed without a verdict",
    )
    llm_checks: List[LlmCheckOutcome] = Field(default_factory=list)
