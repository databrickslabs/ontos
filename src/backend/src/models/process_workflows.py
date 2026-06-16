"""
Pydantic models for process workflows.

Defines the API request/response schemas for workflow definitions, steps, and executions.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator
import uuid

from src.common.logging import get_logger

logger = get_logger(__name__)


class TriggerType(str, Enum):
    """Types of workflow triggers."""
    ON_CREATE = "on_create"
    ON_UPDATE = "on_update"
    ON_DELETE = "on_delete"
    ON_STATUS_CHANGE = "on_status_change"
    SCHEDULED = "scheduled"
    MANUAL = "manual"
    BEFORE_CREATE = "before_create"  # Pre-creation validation (inline/blocking)
    BEFORE_UPDATE = "before_update"  # Pre-update validation (inline/blocking)
    BEFORE_STATUS_CHANGE = "before_status_change"  # Pre-status-change validation (inline/blocking)
    
    # Request triggers - fire when a request action is initiated
    ON_REQUEST_REVIEW = "on_request_review"  # When review is requested (datasets, contracts, products)
    ON_REQUEST_ACCESS = "on_request_access"  # When access is requested (access grants, projects)
    ON_REQUEST_PUBLISH = "on_request_publish"  # When publish/deployment is requested (contracts)
    ON_REQUEST_STATUS_CHANGE = "on_request_status_change"  # When status change is requested
    
    # Job lifecycle triggers
    ON_JOB_SUCCESS = "on_job_success"  # When a background job completes successfully
    ON_JOB_FAILURE = "on_job_failure"  # When a background job fails
    
    # Subscription triggers
    ON_SUBSCRIBE = "on_subscribe"  # When a user subscribes to an entity
    ON_UNSUBSCRIBE = "on_unsubscribe"  # When a user unsubscribes from an entity
    
    # Certification triggers
    ON_REQUEST_CERTIFY = "on_request_certify"  # When certification is requested
    ON_CERTIFY = "on_certify"  # When certification is granted
    ON_DECERTIFY = "on_decertify"  # When certification is removed

    # Publication triggers (separate from lifecycle status)
    ON_PUBLISH = "on_publish"  # When an entity is published to marketplace
    ON_UNPUBLISH = "on_unpublish"  # When an entity is unpublished from marketplace

    # Maturity triggers
    ON_MATURITY_CHANGE = "on_maturity_change"  # When maturity level changes (up or down)

    # Access lifecycle triggers
    ON_EXPIRING = "on_expiring"  # When access/entity is about to expire
    ON_REVOKE = "on_revoke"  # When access is revoked

    # App-known UI actions — approval workflows looked up by trigger type (not name).
    # All power the same ApprovalWizardDialog; 1:1 match with ON_* process triggers.
    FOR_APPROVAL_RESPONSE = "for_approval_response"  # Approver responds to a paused process-workflow approval step
    FOR_SUBSCRIBE = "for_subscribe"  # User subscribes to / signs a contract (matches ON_SUBSCRIBE)
    FOR_REQUEST_REVIEW = "for_request_review"  # Wizard before review request (matches ON_REQUEST_REVIEW)
    FOR_REQUEST_ACCESS = "for_request_access"  # Wizard before access request (matches ON_REQUEST_ACCESS)
    FOR_REQUEST_PUBLISH = "for_request_publish"  # Wizard before publish/deploy request (matches ON_REQUEST_PUBLISH)
    FOR_REQUEST_CERTIFY = "for_request_certify"  # Wizard before certification request (matches ON_REQUEST_CERTIFY)
    FOR_REQUEST_STATUS_CHANGE = "for_request_status_change"  # Wizard before status change request (matches ON_REQUEST_STATUS_CHANGE)

    # User session triggers — fired by the frontend on app mount, not by an
    # entity action. Used for terms-of-use / acceptable-use disclaimers that
    # must be acknowledged before the user proceeds.
    ON_FIRST_ACCESS = "on_first_access"  # User opens the app and hasn't yet accepted this workflow at its current version


class EntityType(str, Enum):
    """Entity types that can trigger workflows."""
    CATALOG = "catalog"
    SCHEMA = "schema"
    TABLE = "table"
    VIEW = "view"
    DATA_CONTRACT = "data_contract"
    DATA_PRODUCT = "data_product"
    DOMAIN = "domain"
    PROJECT = "project"
    ACCESS_GRANT = "access_grant"  # For access grant request workflows
    ROLE = "role"  # For role access request workflows
    DATA_ASSET_REVIEW = "data_asset_review"  # For data asset review request workflows
    JOB = "job"  # For background job lifecycle workflows
    SUBSCRIPTION = "subscription"  # For subscription events
    USER = "user"  # The user themselves — for on_first_access disclaimer/ToU workflows


class ScopeType(str, Enum):
    """Scope types for workflow applicability."""
    ALL = "all"
    PROJECT = "project"
    CATALOG = "catalog"
    DOMAIN = "domain"


class WorkflowType(str, Enum):
    """Type of workflow: process (event-driven) or approval (wizard-driven)."""
    PROCESS = "process"
    APPROVAL = "approval"


class StepType(str, Enum):
    """Types of workflow steps."""
    VALIDATION = "validation"
    APPROVAL = "approval"
    NOTIFICATION = "notification"
    ASSIGN_TAG = "assign_tag"
    REMOVE_TAG = "remove_tag"
    CONDITIONAL = "conditional"
    SCRIPT = "script"
    PASS = "pass"
    FAIL = "fail"
    POLICY_CHECK = "policy_check"  # Evaluates existing compliance policy by UUID
    DELIVERY = "delivery"  # Triggers DeliveryService to apply changes
    CREATE_ASSET_REVIEW = "create_asset_review"  # Creates a DataAssetReview for formal review tracking
    WEBHOOK = "webhook"  # Calls external HTTP endpoints via UC Connections or direct URL
    USER_ACTION = "user_action"  # Approval workflow: collect user input (reason, acceptances, fields)
    GENERATE_PDF = "generate_pdf"  # Approval workflow: build agreement PDF from step_results + pdf_contribution
    ENTITY_ACTION = "entity_action"  # Performs an action on the trigger entity (certify, publish, etc.)
    LEGAL_DOCUMENT = "legal_document"
    ACKNOWLEDGEMENT_CHECKLIST = "acknowledgement_checklist"
    CO_SIGNERS = "co_signers"
    PERSIST_AGREEMENT = "persist_agreement"
    DELIVER = "deliver"
    GRANT_PERMISSIONS = "grant_permissions"  # Process workflow: grant UC permissions via SP workspace client
    ON_BEHALF_OF = "on_behalf_of"  # Approval workflow: capture self/group/SP principal at wizard start ()


class ExecutionStatus(str, Enum):
    """Workflow execution status."""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"  # Awaiting approval
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepExecutionStatus(str, Enum):
    """Step execution status."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


# --- Trigger Configuration ---

class WorkflowTrigger(BaseModel):
    """Trigger configuration for a workflow."""
    type: TriggerType = Field(..., description="Type of trigger")
    entity_types: List[EntityType] = Field(default_factory=list, description="Entity types that trigger this workflow")
    
    # For on_status_change
    from_status: Optional[str] = Field(None, description="Status to transition from (for status change triggers)")
    to_status: Optional[str] = Field(None, description="Status to transition to (for status change triggers)")
    
    # For scheduled
    schedule: Optional[str] = Field(None, description="Cron expression for scheduled triggers")
    
    class Config:
        json_schema_extra = {
            "example": {
                "type": "on_create",
                "entity_types": ["catalog", "schema", "table"]
            }
        }


# --- Scope Configuration ---

class WorkflowScope(BaseModel):
    """Scope configuration for workflow applicability."""
    type: ScopeType = Field(default=ScopeType.ALL, description="Scope type")
    ids: List[str] = Field(default_factory=list, description="IDs of scoped entities (project IDs, catalog names, domain IDs)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "type": "project",
                "ids": ["project-123", "project-456"]
            }
        }


# --- Step Configurations ---

class ValidationStepConfig(BaseModel):
    """Configuration for validation steps."""
    rule: str = Field(..., description="Compliance DSL rule to evaluate")
    
    class Config:
        json_schema_extra = {
            "example": {
                "rule": "MATCH (obj:Object)\nASSERT obj.name MATCHES '^[a-z][a-z0-9_]*$'\nON_FAIL FAIL 'Name must be lowercase with underscores only'"
            }
        }


class ApprovalStepConfig(BaseModel):
    """Configuration for approval steps."""
    approvers: str = Field(..., description="Approvers: 'domain_owners', 'project_owners', user email, or group name")
    timeout_days: int = Field(default=7, description="Days until approval times out")
    require_all: bool = Field(default=False, description="Require all approvers (vs any one)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "approvers": "domain_owners",
                "timeout_days": 7,
                "require_all": False
            }
        }


class UserActionStepConfig(BaseModel):
    """Configuration for approval workflow user_action steps (wizard: collect reason, acceptances, fields)."""
    title: Optional[str] = Field(None, description="Step title shown in wizard")
    description: Optional[str] = Field(None, description="Step description")
    document_url: Optional[str] = Field(None, description="URL of document to display (e.g. legal terms)")
    document_content: Optional[str] = Field(None, description="Inline document content")
    required_acceptances: Optional[List[Dict[str, Any]]] = Field(
        default_factory=list,
        description="List of { id, label, type: 'checkbox' } for required checkboxes",
    )
    required_fields: Optional[List[Dict[str, Any]]] = Field(
        default_factory=list,
        description="List of { id, label, type: 'text'|'text_list', required?: bool }",
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "title": "Enter a reason",
                "required_fields": [{"id": "reason", "label": "Reason for approval or rejection", "type": "text", "required": True}]
            }
        }


class LegalDocumentStepConfig(BaseModel):
    """Config for legal_document step: display legal text for review."""
    title: Optional[str] = Field(None, description="Step title shown in wizard")
    description: Optional[str] = Field(None, description="Step description (markdown)")
    body_markdown: Optional[str] = Field(None, description="Legal document body (markdown)")
    require_scroll_to_end: bool = Field(False, description="Require user to scroll to bottom")
    require_acknowledgement_checkbox: bool = Field(False, description="Require acknowledgement checkbox")
    acknowledgement_label: Optional[str] = Field("I have read and understood the above", description="Label for acknowledgement checkbox")


class AcknowledgementChecklistStepConfig(BaseModel):
    """Config for acknowledgement_checklist step: checkbox list for explicit consents."""
    title: Optional[str] = Field(None, description="Step title shown in wizard")
    description: Optional[str] = Field(None, description="Step description (markdown)")
    items: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of { id, label, required } checkbox items (max 10)",
    )

    @field_validator('items')
    @classmethod
    def cap_at_ten(cls, v: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if len(v) > 10:
            raise ValueError("acknowledgement_checklist.items has a hard cap of 10 entries; split into multiple steps")
        return v


class OnBehalfOfStepConfig(BaseModel):
    """Config for on_behalf_of step: captures whether the requester is acting
    for themselves, a group they belong to, or another principal (group / SP).

    Customer-controllable replacement for the pre-wizard ``SubscribeDialog``
    on-behalf-of picker — placing the choice inside the wizard means it lands
    in ``step_results`` (which the workflow snapshot + agreement PDF already
    immortalize) and the session columns ``on_behalf_of_type`` /
    ``on_behalf_of_value`` () get written exactly the same way
    a direct ``/subscribe`` call writes them.
    """
    title: Optional[str] = Field("Who are you requesting access for?", description="Step title shown in wizard")
    description: Optional[str] = Field(
        "Pick whether you're requesting for yourself or on behalf of a group/service principal.",
        description="Step description (markdown)",
    )
    allow_self: bool = Field(True, description="Show 'For myself' option")
    allow_user_groups: bool = Field(True, description="Show dropdown of user's own groups")
    allow_free_text: bool = Field(True, description="Show free-text input for any group/SP name")
    require_justification: bool = Field(False, description="Require a free-text justification field")


class CoSignersStepConfig(BaseModel):
    """Config for co_signers step: collect co-signer principals."""
    title: Optional[str] = Field(None, description="Step title shown in wizard")
    description: Optional[str] = Field(None, description="Step description (markdown)")
    min_count: int = Field(0, description="Minimum number of co-signers")
    max_count: int = Field(5, description="Maximum number of co-signers")
    principal_type: Optional[str] = Field("either", description="'user' | 'group' | 'either'")
    label: Optional[str] = Field("Add co-signer", description="Input label")


class PersistAgreementStepConfig(BaseModel):
    """Config for persist_agreement step: materialize the agreement record."""
    # No user-configurable fields — placement in workflow determines when agreement is persisted.
    pass


class GeneratePdfStepConfig(BaseModel):
    """Config for generate_pdf step: build agreement PDF and persist to storage."""
    storage: Optional[str] = Field(
        "volume",
        description="Storage backend: 'volume' (UC Volume via SDK Files API) or 'none' (regenerate on download).",
    )
    volume_path: Optional[str] = Field(
        None,
        description=(
            "Directory where PDFs are written. If the path doesn't already end in '/agreements', "
            "that segment is appended automatically. Final file: <resolved_dir>/<agreement_id>.pdf. "
            "Example: '/Volumes/cat/sch/vol' → files at '/Volumes/cat/sch/vol/agreements/<id>.pdf'."
        ),
    )
    include_step_results: Optional[bool] = Field(
        True,
        description="Include rendered step_results (acknowledgements, co-signers, etc.) in the PDF body.",
    )


class DeliverStepConfig(BaseModel):
    """Config for deliver step: send agreement via notification channels."""
    channels: List[str] = Field(
        default_factory=lambda: ["in_app"],
        description="Delivery channels: 'in_app' or 'webhook'. Use 'webhook' to integrate with your own email provider.",
    )
    recipients: List[str] = Field(
        default_factory=lambda: ["signer"],
        description="Recipients: 'signer', 'co_signers', 'entity_owner', or literal email/group",
    )
    subject_template: Optional[str] = Field(None, description="Subject line template with ${variable} substitution")
    body_template: Optional[str] = Field(None, description="Body template with ${variable} substitution")

    @field_validator('channels')
    @classmethod
    def _strip_unsupported_channels(cls, v: List[str]) -> List[str]:
        # Non-blocking: 'email' is out of scope in v1 (non-portable across customer
        # environments — no Databricks-managed SMTP). Strip it with a warning so
        # legacy workflow configs still load and execute.
        if v and 'email' in v:
            logger.warning(
                "'email' channel is not supported in v1 (non-portable across customer environments). "
                "Stripping from channels — use 'webhook' to your own email provider instead."
            )
            return [c for c in v if c != 'email']
        return v


class GrantPermissionsStepConfig(BaseModel):
    """Config for grant_permissions step: grant UC permissions via SP workspace client."""
    permission_type: str = Field("SELECT", description="Permission to grant: SELECT, USE_SCHEMA, USE_CATALOG, ALL_PRIVILEGES")
    target_source: str = Field("from_entity", description="'from_entity' (use trigger entity) or 'from_variable' (use step_results variable)")
    target_variable: Optional[str] = Field(None, description="step_results variable path for target (when target_source=from_variable)")
    principal_source: str = Field("requester", description="'requester', 'from_variable', or literal email/group")
    principal_variable: Optional[str] = Field(None, description="step_results variable path for principal (when principal_source=from_variable)")


class NotificationStepConfig(BaseModel):
    """Configuration for notification steps."""
    recipients: str = Field(..., description="Recipients: 'requester', 'owner', user email, or group name")
    template: str = Field(..., description="Notification template name")
    custom_message: Optional[str] = Field(None, description="Custom message override")
    
    class Config:
        json_schema_extra = {
            "example": {
                "recipients": "requester",
                "template": "validation_failed"
            }
        }


class AssignTagStepConfig(BaseModel):
    """Configuration for tag assignment steps."""
    key: str = Field(..., description="Tag key to assign")
    value: Optional[str] = Field(None, description="Static tag value")
    value_source: Optional[str] = Field(None, description="Dynamic value source: 'current_user', 'project_name', etc.")
    
    class Config:
        json_schema_extra = {
            "example": {
                "key": "owner",
                "value_source": "current_user"
            }
        }


class RemoveTagStepConfig(BaseModel):
    """Configuration for tag removal steps."""
    key: str = Field(..., description="Tag key to remove")


class ConditionalStepConfig(BaseModel):
    """Configuration for conditional branching steps."""
    condition: str = Field(..., description="Compliance DSL expression to evaluate")
    
    class Config:
        json_schema_extra = {
            "example": {
                "condition": "HAS_TAG('pii') AND obj.type = 'table'"
            }
        }


class ScriptStepConfig(BaseModel):
    """Configuration for script execution steps."""
    language: str = Field(default="python", description="Script language: 'python' or 'sql'")
    code: str = Field(..., description="Script code to execute")
    timeout_seconds: int = Field(default=60, description="Execution timeout")
    
    class Config:
        json_schema_extra = {
            "example": {
                "language": "python",
                "code": "return {'status': 'ok'}",
                "timeout_seconds": 30
            }
        }


class PolicyCheckStepConfig(BaseModel):
    """Configuration for policy check steps - references existing compliance policy by UUID."""
    policy_id: str = Field(..., description="UUID of the compliance policy to evaluate")
    policy_name: Optional[str] = Field(None, description="Cached policy name for display (set automatically)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "policy_id": "011abc123-def456",
                "policy_name": "Naming Conventions"
            }
        }


class WebhookStepConfig(BaseModel):
    """Configuration for webhook steps - calls external HTTP endpoints.
    
    Supports two modes:
    1. UC Connection mode: Use a pre-configured Unity Catalog HTTP Connection (secure, production)
    2. Inline mode: Provide URL and credentials directly (testing/simple cases)
    """
    # UC Connection mode - reference by name
    connection_name: Optional[str] = Field(None, description="UC HTTP Connection name (if using UC mode)")
    
    # Inline mode - direct URL
    url: Optional[str] = Field(None, description="Target URL (required if not using connection)")
    
    # Common settings
    method: str = Field(default="POST", description="HTTP method: GET, POST, PUT, PATCH, DELETE")
    path: Optional[str] = Field(None, description="Path appended to connection base URL (for UC mode)")
    headers: Optional[Dict[str, str]] = Field(default_factory=dict, description="Custom headers (merged with connection headers)")
    body_template: Optional[str] = Field(None, description="JSON body with ${variable} substitution")
    timeout_seconds: int = Field(default=30, description="Request timeout in seconds")
    success_codes: Optional[List[int]] = Field(default=None, description="HTTP codes considered success (default: 200-299)")
    retry_count: int = Field(default=0, description="Number of retries on failure")

    # Caller-supplied extra parameters forwarded into the UC HTTPConnection call.
    # All three support ${entity.*} / ${trigger.*} / ${context.*} substitution,
    # the same syntax as `body_template`. Absent/empty fields are no-ops, so
    # existing webhook configs continue to work unchanged.
    additional_headers: Optional[Dict[str, str]] = Field(
        default_factory=dict,
        description=(
            "Additional headers merged into the request (template substitution supported). "
            "Take precedence over `headers` if a key collides."
        ),
    )
    additional_query_params: Optional[Dict[str, str]] = Field(
        default_factory=dict,
        description=(
            "Additional query string parameters appended to the request "
            "(template substitution supported). Values are URL-encoded."
        ),
    )
    path_suffix: Optional[str] = Field(
        None,
        description=(
            "Optional suffix appended to `path` before the query string "
            "(template substitution supported). Useful for context-derived path segments."
        ),
    )

    class Config:
        json_schema_extra = {
            "example": {
                "connection_name": "servicenow-prod",
                "method": "POST",
                "path": "/api/now/table/incident",
                "body_template": '{"short_description": "Alert: ${entity_name}"}',
                "additional_headers": {"X-Trace-Id": "${execution_id}"},
                "additional_query_params": {"caller": "ontos"},
                "path_suffix": "/${entity_id}",
                "timeout_seconds": 30,
            }
        }


# Union type for step configs
StepConfig = Union[
    ValidationStepConfig,
    ApprovalStepConfig,
    NotificationStepConfig,
    AssignTagStepConfig,
    RemoveTagStepConfig,
    ConditionalStepConfig,
    ScriptStepConfig,
    PolicyCheckStepConfig,
    WebhookStepConfig,
    Dict[str, Any],  # For pass/fail steps with no config
]


# --- Step Position ---

class StepPosition(BaseModel):
    """Visual position of a step in the workflow designer."""
    x: float = Field(default=0, description="X coordinate")
    y: float = Field(default=0, description="Y coordinate")


# --- Workflow Step ---

class WorkflowStepBase(BaseModel):
    """Base model for workflow step."""
    step_id: str = Field(..., description="Unique identifier for the step within the workflow")
    name: Optional[str] = Field(None, description="Human-readable step name")
    step_type: StepType = Field(..., description="Type of step")
    config: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Step configuration")
    on_pass: Optional[str] = Field(None, description="Step ID to go to on pass (null for terminal)")
    on_fail: Optional[str] = Field(None, description="Step ID to go to on fail (null for terminal)")
    order: int = Field(default=0, description="Order in the workflow")
    position: Optional[StepPosition] = Field(None, description="Visual position")


class WorkflowStepCreate(WorkflowStepBase):
    """Model for creating a workflow step."""
    pass


class WorkflowStep(WorkflowStepBase):
    """Full workflow step model with database ID."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Database ID")
    workflow_id: str = Field(..., description="Parent workflow ID")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# --- Workflow ---

class ProcessWorkflowBase(BaseModel):
    """Base model for process workflow."""
    name: str = Field(..., description="Workflow name")
    description: Optional[str] = Field(None, description="Workflow description")
    trigger: WorkflowTrigger = Field(..., description="Trigger configuration")
    scope: Optional[WorkflowScope] = Field(default_factory=lambda: WorkflowScope(type=ScopeType.ALL), description="Scope configuration")
    workflow_type: WorkflowType = Field(default=WorkflowType.PROCESS, description="process (event-driven) or approval (wizard-driven)")
    is_active: bool = Field(default=True, description="Whether workflow is active")


class ProcessWorkflowCreate(ProcessWorkflowBase):
    """Model for creating a workflow."""
    steps: List[WorkflowStepCreate] = Field(default_factory=list, description="Workflow steps")


class ProcessWorkflowUpdate(BaseModel):
    """Model for updating a workflow."""
    name: Optional[str] = None
    description: Optional[str] = None
    trigger: Optional[WorkflowTrigger] = None
    scope: Optional[WorkflowScope] = None
    workflow_type: Optional[WorkflowType] = None
    is_active: Optional[bool] = None
    steps: Optional[List[WorkflowStepCreate]] = None


class ProcessWorkflow(ProcessWorkflowBase):
    """Full workflow model with database ID and metadata."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Database ID")
    is_default: bool = Field(default=False, description="Whether this is a system default workflow")
    version: int = Field(default=1, description="Version for optimistic locking")
    steps: List[WorkflowStep] = Field(default_factory=list, description="Workflow steps")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None

    class Config:
        from_attributes = True


# --- Workflow Execution ---

class TriggerContext(BaseModel):
    """Context for workflow trigger."""
    entity_type: str = Field(..., description="Type of entity that triggered the workflow")
    entity_id: str = Field(..., description="ID of the entity")
    entity_name: Optional[str] = Field(None, description="Name of the entity")
    trigger_type: TriggerType = Field(..., description="Type of trigger")
    user_email: Optional[str] = Field(None, description="User who triggered the workflow")
    entity_data: Optional[Dict[str, Any]] = Field(None, description="Entity data at trigger time")
    
    # For status change triggers
    from_status: Optional[str] = None
    to_status: Optional[str] = None


class WorkflowStepExecutionResult(BaseModel):
    """Result of a step execution."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    step_id: str
    status: StepExecutionStatus
    passed: Optional[bool] = None
    result_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    duration_ms: Optional[float] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WorkflowExecutionBase(BaseModel):
    """Base model for workflow execution."""
    workflow_id: str = Field(..., description="ID of the workflow being executed")
    trigger_context: Optional[TriggerContext] = Field(None, description="Trigger context")


class WorkflowExecutionCreate(WorkflowExecutionBase):
    """Model for creating a workflow execution."""
    triggered_by: Optional[str] = Field(None, description="User who triggered the execution")


class WorkflowExecution(WorkflowExecutionBase):
    """Full workflow execution model."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: ExecutionStatus = Field(default=ExecutionStatus.PENDING)
    current_step_id: Optional[str] = None
    current_step_name: Optional[str] = Field(None, description="Name of the current step (for display)")
    success_count: int = Field(default=0)
    failure_count: int = Field(default=0)
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    triggered_by: Optional[str] = None
    step_executions: List[WorkflowStepExecutionResult] = Field(default_factory=list)
    
    # Include workflow details for display
    workflow_name: Optional[str] = None
    entity_type: Optional[str] = Field(None, description="Type of entity this workflow is for")
    entity_id: Optional[str] = Field(None, description="ID of the entity")
    entity_name: Optional[str] = Field(None, description="Name of the entity")

    class Config:
        from_attributes = True


# --- Step Type Schema ---

class StepTypeSchema(BaseModel):
    """Schema for a step type, used by frontend to render forms."""
    type: StepType
    name: str
    description: str
    icon: str
    config_schema: Dict[str, Any]  # JSON Schema for the config
    has_pass_branch: bool = True
    has_fail_branch: bool = True


# --- Template Variable Inspector ---
#
# Workflow designers (the React side) need a way to surface every
# ``${...}`` variable a workflow author can reference in a webhook
# ``body_template`` for a given (trigger, entity_type) pair. The set is
# derived from the manager-side enrichment that prepares ``entity_data``
# right before a trigger fires; the backend exposes it as a static
# registry so the UI doesn't have to introspect manager code.
#
# Drift between the registry and the actual enrichment is caught by a
# unit test in ``tests/unit/test_template_vars_registry.py`` which walks
# every descriptor path through ``substitute_template`` against a
# realistic ``StepContext`` fixture.


class TemplateVarDescriptor(BaseModel):
    """One ``${...}`` variable surfaced in the workflow designer."""

    path: str = Field(
        ...,
        description=(
            "The placeholder body (without the ``${}`` wrapper) that a "
            "workflow author types into a webhook body_template — e.g. "
            "``entity.catalogs`` or ``user_email``."
        ),
    )
    type: str = Field(
        ...,
        description=(
            "Coarse runtime type of the resolved value. One of "
            "``string``, ``number``, ``boolean``, ``array``, ``object``, "
            "``enum``. Drives the badge styling in the UI."
        ),
    )
    description: str = Field(
        ...,
        description=(
            "One-sentence prose explaining the variable. Shown muted "
            "next to the path."
        ),
    )
    sample: Optional[Any] = Field(
        None,
        description=(
            "Realistic example value for the variable. Rendered as a "
            "preview chip so authors know what shape to expect — e.g. "
            "lists show ``[\"main\", \"prod\"]``."
        ),
    )
    enum_values: Optional[List[str]] = Field(
        None,
        description=(
            "Set of allowed values when ``type == 'enum'``. Otherwise "
            "``None``."
        ),
    )


class TemplateVarGroup(BaseModel):
    """A namespace of related descriptors (``entity``, ``context``, …)."""

    namespace: str = Field(
        ...,
        description=(
            "Short slug for the group. Used as the section header in "
            "the inspector — e.g. ``entity``, ``context``, ``flat``."
        ),
    )
    description: str = Field(
        ...,
        description="One-sentence prose summarizing what this namespace covers.",
    )
    variables: List[TemplateVarDescriptor] = Field(
        default_factory=list,
        description="Descriptors that live under this namespace.",
    )


class TemplateVarsResponse(BaseModel):
    """Response payload for ``GET /api/workflows/template-vars``."""

    trigger: TriggerType = Field(
        ...,
        description="The trigger this descriptor set applies to.",
    )
    entity_type: EntityType = Field(
        ...,
        description="The entity type this descriptor set applies to.",
    )
    groups: List[TemplateVarGroup] = Field(
        default_factory=list,
        description=(
            "Descriptor groups for this (trigger, entity_type) pair. "
            "Empty when the combination has no curated registry entry "
            "— the UI should render a friendly 'no descriptors yet' "
            "state rather than treat that as an error."
        ),
    )


# --- API Response Models ---

class WorkflowListResponse(BaseModel):
    """Response for listing workflows."""
    workflows: List[ProcessWorkflow]
    total: int


class WorkflowExecutionListResponse(BaseModel):
    """Response for listing executions."""
    executions: List[WorkflowExecution]
    total: int


class WorkflowValidationResult(BaseModel):
    """Result of workflow validation."""
    valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

