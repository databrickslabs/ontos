"""
API routes for process workflows.

Provides CRUD operations for workflow definitions and execution management.
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.orm import Session

from src.common.database import get_db
from src.common.dependencies import DBSessionDep, AuditManagerDep, AuditCurrentUserDep, get_notifications_manager, SettingsManagerDep
from src.common.authorization import (
    PermissionChecker,
    enforce_feature_permission,
    get_user_details_from_sdk,
)
from src.common.features import FeatureAccessLevel
from src.models.users import UserInfo
from src.models.notifications import Notification
from src.common.logging import get_logger
from src.controller.workflows_manager import WorkflowsManager
from src.controller.notifications_manager import NotificationsManager
from src.common.workflow_executor import WorkflowExecutor
from src.repositories.process_workflows_repository import process_workflow_repo, workflow_execution_repo
from src.db_models.compliance import CompliancePolicyDb
from src.db_models.notifications import NotificationDb
from src.db_models.process_workflows import WorkflowStepDb
from src.models.process_workflows import (
    ProcessWorkflow,
    ProcessWorkflowCreate,
    ProcessWorkflowUpdate,
    WorkflowExecution,
    WorkflowListResponse,
    WorkflowExecutionListResponse,
    WorkflowValidationResult,
    StepTypeSchema,
    TriggerContext,
    TriggerType,
    EntityType,
    WorkflowType,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/workflows", tags=["Process Workflows"])


def get_workflows_manager(db: Session = Depends(get_db)) -> WorkflowsManager:
    """Get WorkflowsManager instance."""
    return WorkflowsManager(db)


def get_workflow_executor(db: Session = Depends(get_db)) -> WorkflowExecutor:
    """Get WorkflowExecutor instance."""
    return WorkflowExecutor(db)


@router.get("", response_model=WorkflowListResponse)
async def list_workflows(
    request: Request,
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    workflow_type: Optional[str] = Query(None, description="Filter by workflow_type: process | approval"),
    manager: WorkflowsManager = Depends(get_workflows_manager),
    _: bool = Depends(PermissionChecker('settings-workflows', FeatureAccessLevel.READ_ONLY)),
) -> WorkflowListResponse:
    """List all process workflows (or approval workflows when workflow_type=approval).

    Admin-only enumeration (``settings:READ_ONLY``). End users MUST NOT
    use this endpoint — the full payload includes every step's ``config``
    which can carry webhook URLs, script content, internal recipient
    lists, and other implementation detail that shouldn't leak.

    For end-user wizard flows use:
      - ``GET /api/workflows/for-trigger/{trigger_type}`` — per-trigger
        dispatch via ``WIZARD_PERMISSION_DISPATCH`` (PR A).
      - ``GET /api/workflows/{workflow_id}`` — when the workflow is an
        approval workflow, dispatched on its trigger; otherwise still
        ``settings:READ_ONLY``.
    """
    wf_type = WorkflowType(workflow_type) if workflow_type in ('process', 'approval') else None
    workflows = manager.list_workflows(is_active=is_active, workflow_type=wf_type)
    return WorkflowListResponse(workflows=workflows, total=len(workflows))


@router.get("/step-types", response_model=List[StepTypeSchema])
async def get_step_types(
    request: Request,
    manager: WorkflowsManager = Depends(get_workflows_manager),
    _: bool = Depends(PermissionChecker('settings-workflows', FeatureAccessLevel.READ_ONLY)),
) -> List[StepTypeSchema]:
    """Get schemas for all available step types."""
    return manager.get_step_type_schemas()


# ---------------------------------------------------------------------------
# Trigger-type catalog
# ---------------------------------------------------------------------------
#
# Returns a UI-friendly catalog of every TriggerType enum member so the
# workflow-authoring form can:
#   1. Render human-readable labels (no more raw enum values in the picker).
#   2. Group triggers (lifecycle / request_flow / validation_gates /
#      system_scheduled).
#   3. Show approval (for_*) vs process (on_* / before_* / scheduled / manual)
#      based on the workflow being authored.
#   4. Pre-populate the entity_types multiselect with the entity types each
#      trigger is wired for in the backend.
#
# Wire-format contract: every TriggerType member appears exactly once.
# `value` is the raw enum string (used as the FK in stored trigger configs).
# Labels here are the canonical source of truth; the FE getTriggerLabel()
# helper mirrors them so existing labels keep working if the endpoint is
# unavailable.
#
# entity_types mapping mirrors SUPPORTED_TRIGGER_ENTITY_MAP in the FE
# (src/frontend/src/lib/workflow-labels.ts) — keep them in sync. An empty
# list means "any entity type" (manual, scheduled, on_first_access).

_TRIGGER_LABELS: Dict[str, str] = {
    "for_subscribe": "When a user subscribes",
    "on_subscribe": "After a subscription is created",
    "for_request_access": "When a user requests access",
    "on_request_access": "After an access request is submitted",
    "for_request_review": "When a user requests review",
    "on_request_review": "After a review request is submitted",
    "for_request_publish": "When a user requests publish",
    "on_request_publish": "After a publish request is submitted",
    "for_request_certify": "When a user requests certification",
    "on_request_certify": "After a certification request is submitted",
    "for_request_status_change": "When a user requests status change",
    "on_request_status_change": "After a status change request is submitted",
    "for_approval_response": "Approval response dialog",
    "before_create": "Before entity is created (validation)",
    "before_update": "Before entity is updated (validation)",
    "before_status_change": "Before status changes (validation)",
    "on_create": "After entity is created",
    "on_update": "After entity is updated",
    "on_delete": "After entity is deleted",
    "on_status_change": "After status changes",
    "on_publish": "After entity is published",
    "on_unpublish": "After entity is unpublished",
    "on_revoke": "After access is revoked",
    "on_expiring": "When access is about to expire",
    "on_first_access": "First time a user accesses (consent)",
    "on_unsubscribe": "After a user unsubscribes",
    "on_job_success": "After a background job succeeds",
    "on_job_failure": "After a background job fails",
    "scheduled": "On a schedule (cron)",
    # Fallbacks for enum members that are not part of the user-approved table.
    # These keep the catalog 1:1 with the enum without expanding the table.
    "manual": "Manually triggered",
    "on_certify": "After entity is certified",
    "on_decertify": "After entity is decertified",
}

# Group assignment per the design brief. Anything not listed falls back to
# "lifecycle" for process workflows.
_TRIGGER_GROUPS_REQUEST_FLOW = {
    "for_subscribe", "for_request_access", "for_request_review",
    "for_request_publish", "for_request_certify",
    "for_request_status_change", "for_approval_response",
    "on_subscribe", "on_unsubscribe",
    "on_request_access", "on_request_review", "on_request_publish",
    "on_request_certify", "on_request_status_change",
    "on_revoke", "on_expiring", "on_first_access",
}
_TRIGGER_GROUPS_LIFECYCLE = {
    "on_create", "on_update", "on_delete", "on_status_change",
    "on_publish", "on_unpublish",
    # on_certify / on_decertify are lifecycle in spirit — they describe an
    # entity transitioning state, not a request flow.
    "on_certify", "on_decertify",
}
_TRIGGER_GROUPS_VALIDATION = {
    "before_create", "before_update", "before_status_change",
}
_TRIGGER_GROUPS_SYSTEM_SCHEDULED = {
    "on_job_success", "on_job_failure", "scheduled", "manual",
}

# Entity types each trigger CAN fire for, derived from the dispatch sites in
# src/backend/src/common/workflow_triggers.py and the existing FE map
# (SUPPORTED_TRIGGER_ENTITY_MAP). Empty list = "any entity" (no constraint).
_TRIGGER_ENTITY_TYPES: Dict[str, List[str]] = {
    # CRUD / lifecycle
    "on_create": ["catalog", "schema", "table", "data_contract", "data_product", "domain"],
    "on_update": ["data_contract", "data_product", "domain"],
    "on_delete": ["data_contract", "data_product", "domain"],
    "on_status_change": ["data_contract", "data_product", "data_asset_review"],
    "on_publish": ["data_contract", "data_product"],
    "on_unpublish": ["data_contract", "data_product"],
    "on_certify": ["data_contract", "data_product"],
    "on_decertify": ["data_contract", "data_product"],
    # Validation gates
    "before_create": ["catalog", "schema", "table"],
    "before_update": ["data_contract"],
    "before_status_change": ["data_contract", "data_product"],
    # Request flow — process side
    "on_request_review": ["data_contract", "data_product", "data_asset_review"],
    "on_request_access": ["access_grant", "project", "role"],
    "on_request_publish": ["data_contract", "data_product"],
    "on_request_certify": ["data_contract", "data_product"],
    "on_request_status_change": ["data_product"],
    "on_subscribe": ["subscription", "data_product", "data_contract"],
    "on_unsubscribe": ["subscription", "data_product", "data_contract"],
    "on_revoke": ["access_grant"],
    "on_expiring": ["access_grant"],
    "on_first_access": ["user"],
    # Request flow — approval (for_*) side. These mirror the matching on_*
    # trigger's entity scope so the wizard targets the same kinds of objects.
    "for_subscribe": ["data_product", "data_contract"],
    "for_request_access": ["access_grant", "project", "role"],
    "for_request_review": ["data_contract", "data_product", "data_asset_review"],
    "for_request_publish": ["data_contract", "data_product"],
    "for_request_certify": ["data_contract", "data_product"],
    "for_request_status_change": ["data_product"],
    "for_approval_response": [],  # system trigger — any entity
    # Background jobs
    "on_job_success": ["job"],
    "on_job_failure": ["job"],
    # Scheduled / manual — no entity binding
    "scheduled": [],
    "manual": [],
}


def _trigger_group(value: str) -> str:
    if value in _TRIGGER_GROUPS_REQUEST_FLOW:
        return "request_flow"
    if value in _TRIGGER_GROUPS_VALIDATION:
        return "validation_gates"
    if value in _TRIGGER_GROUPS_SYSTEM_SCHEDULED:
        return "system_scheduled"
    if value in _TRIGGER_GROUPS_LIFECYCLE:
        return "lifecycle"
    # Safe fallback — should never hit if mappings stay in sync with the enum.
    return "lifecycle"


@router.get("/trigger-types", response_model=List[Dict[str, Any]])
async def get_trigger_types(
    request: Request,
    _: bool = Depends(PermissionChecker('settings-workflows', FeatureAccessLevel.READ_ONLY)),
) -> List[Dict[str, Any]]:
    """Get the UI catalog of all trigger types.

    Returns one entry per TriggerType enum member with the metadata the
    workflow-authoring picker needs (label, group, workflow_type,
    entity_types). See module-level comments for the contract.
    """
    out: List[Dict[str, Any]] = []
    for tt in TriggerType:
        value = tt.value
        workflow_type = "approval" if value.startswith("for_") else "process"
        out.append({
            "value": value,
            "label": _TRIGGER_LABELS.get(value, value.replace("_", " ").title()),
            "workflow_type": workflow_type,
            "entity_types": list(_TRIGGER_ENTITY_TYPES.get(value, [])),
            "group": _trigger_group(value),
        })
    return out


@router.get("/executions", response_model=WorkflowExecutionListResponse)
async def list_executions(
    request: Request,
    db: DBSessionDep,
    workflow_id: Optional[str] = Query(None, description="Filter by workflow ID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _: bool = Depends(PermissionChecker('settings-workflows', FeatureAccessLevel.READ_ONLY)),
) -> WorkflowExecutionListResponse:
    """List workflow executions."""
    if workflow_id:
        executions = workflow_execution_repo.list_for_workflow(
            db, workflow_id, limit=limit, offset=offset
        )
    else:
        executions = workflow_execution_repo.list_all(
            db, status=status, limit=limit, offset=offset
        )
    
    # Convert to response models
    result = []
    for exe in executions:
        workflow = exe.workflow
        workflow_name = workflow.name if workflow else None
        
        # Extract entity info from trigger_context
        entity_type = None
        entity_id = None
        entity_name = None
        if exe.trigger_context:
            try:
                tc = json.loads(exe.trigger_context) if isinstance(exe.trigger_context, str) else exe.trigger_context
                entity_type = tc.get('entity_type')
                entity_id = tc.get('entity_id')
                entity_name = tc.get('entity_name')
            except (json.JSONDecodeError, TypeError):
                pass
        
        # Resolve current step name from workflow definition
        current_step_name = None
        if exe.current_step_id and workflow and workflow.steps:
            try:
                # workflow.steps is a relationship to WorkflowStepDb objects
                # current_step_id stores the step_id (slug), not the UUID id
                for step in workflow.steps:
                    if step.step_id == exe.current_step_id:
                        current_step_name = step.name or exe.current_step_id
                        break
            except Exception:
                pass
        
        result.append(WorkflowExecution(
            id=exe.id,
            workflow_id=exe.workflow_id,
            status=exe.status,
            current_step_id=exe.current_step_id,
            current_step_name=current_step_name,
            success_count=exe.success_count,
            failure_count=exe.failure_count,
            error_message=exe.error_message,
            started_at=exe.started_at,
            finished_at=exe.finished_at,
            triggered_by=exe.triggered_by,
            workflow_name=workflow_name,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
        ))
    
    return WorkflowExecutionListResponse(executions=result, total=len(result))


@router.get("/compliance-policies")
async def list_compliance_policies_for_workflows(
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker('compliance', FeatureAccessLevel.READ_ONLY)),
) -> List[Dict[str, Any]]:
    """List active compliance policies for workflow designer selection.
    
    Returns simplified policy objects for use in the policy_check step type selector.
    """
    policies = db.query(CompliancePolicyDb).filter(
        CompliancePolicyDb.is_active == True
    ).order_by(CompliancePolicyDb.name).all()
    
    return [
        {
            "id": p.id,
            "name": p.name,
            "slug": p.slug,
            "description": p.description,
            "category": p.category,
            "severity": p.severity,
        }
        for p in policies
    ]


@router.get("/roles")
async def list_roles_for_workflows(
    db: DBSessionDep,
    settings_manager: SettingsManagerDep,
    _: bool = Depends(PermissionChecker('settings-workflows', FeatureAccessLevel.READ_ONLY)),
    approval_entity: Optional[str] = Query(
        default=None,
        description=(
            "Filter to roles whose approval_privileges flag is True for this entity type. "
            "Valid values: CONTRACTS, PRODUCTS, DOMAINS, ASSET_REVIEWS. "
            "Omit to return all roles (backward-compatible)."
        ),
    ),
) -> List[Dict[str, Any]]:
    """List roles available for workflow approver/recipient selection.

    Returns both app roles (RBAC) and business roles (governance) that are
    marked as approvers. Each role includes a 'source' field to distinguish
    between app and business roles.

    When *approval_entity* is provided the app-role list is narrowed to only
    roles where ``approval_privileges[approval_entity]`` is ``True``. Business
    roles (is_approver=True) are always included regardless of the filter
    because they carry entity-level approval semantics through their own flag.
    """
    from src.db_models.business_roles import BusinessRoleDb

    # App roles — optionally filtered by approval_entity
    filtered_app_roles = settings_manager.list_app_roles_for_approval(
        approval_entity=approval_entity
    )

    # Business roles marked as approvers (always returned for backward compat)
    business_roles = (
        db.query(BusinessRoleDb)
        .filter(BusinessRoleDb.is_approver.is_(True), BusinessRoleDb.status == "active")
        .order_by(BusinessRoleDb.name)
        .all()
    )

    result = []

    for r in filtered_app_roles:
        result.append({
            "id": str(r.id),
            "name": r.name,
            "description": r.description,
            "source": "app",
            "has_groups": bool(r.assigned_groups),
        })

    for r in business_roles:
        result.append({
            "id": f"business:{r.id}",
            "name": r.name,
            "description": r.description,
            "source": "business",
            "category": r.category,
        })

    return result


@router.get("/roles/{role_id}")
async def get_role_by_id(
    role_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker('settings-workflows', FeatureAccessLevel.READ_ONLY)),
) -> Dict[str, Any]:
    """Get a single role by UUID for display purposes."""
    from src.db_models.settings import AppRoleDb
    from src.db_models.business_roles import BusinessRoleDb

    # Check if it's a business role (prefixed with "business:")
    if role_id.startswith("business:"):
        br_id = role_id[len("business:"):]
        role = db.query(BusinessRoleDb).filter(BusinessRoleDb.id == br_id).first()
        if not role:
            raise HTTPException(status_code=404, detail="Business role not found")
        return {
            "id": f"business:{role.id}",
            "name": role.name,
            "description": role.description,
            "source": "business",
        }

    role = db.query(AppRoleDb).filter(AppRoleDb.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    return {
        "id": str(role.id),
        "name": role.name,
        "description": role.description,
        "source": "app",
    }


@router.get("/http-connections")
async def list_http_connections_for_workflows(
    request: Request,
    _: bool = Depends(PermissionChecker('settings-workflows', FeatureAccessLevel.READ_ONLY)),
) -> List[Dict[str, Any]]:
    """List Unity Catalog HTTP connections for webhook step configuration.

    Returns HTTP-type connections that can be used with the webhook step type.
    These connections are pre-configured in Unity Catalog with credentials.
    """
    from src.common.workspace_client import get_obo_workspace_client
    from src.common.uc_connections import list_http_connections

    ws = get_obo_workspace_client(request)
    return list_http_connections(ws)


@router.get("/policy-usage/{policy_id}")
async def get_policy_workflow_usage(
    policy_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker('compliance', FeatureAccessLevel.READ_ONLY)),
) -> Dict[str, Any]:
    """Get list of workflows that reference a specific compliance policy.
    
    Scans all workflow steps of type 'policy_check' that have this policy_id configured.
    """
    # Query workflow steps where step_type is 'policy_check' and config contains policy_id
    steps = db.query(WorkflowStepDb).filter(
        WorkflowStepDb.step_type == 'policy_check'
    ).all()
    
    # Filter steps that reference this policy
    workflow_ids = set()
    for step in steps:
        if step.config:
            try:
                config = json.loads(step.config) if isinstance(step.config, str) else step.config
                if config.get('policy_id') == policy_id:
                    workflow_ids.add(step.workflow_id)
            except (json.JSONDecodeError, TypeError):
                continue
    
    # Get workflow details
    workflows = []
    for wf_id in workflow_ids:
        wf = process_workflow_repo.get(db, wf_id)
        if wf:
            workflows.append({
                'id': wf.id,
                'name': wf.name,
                'is_active': wf.is_active,
            })
    
    return {
        'policy_id': policy_id,
        'workflow_count': len(workflows),
        'workflows': workflows,
    }


# App-known trigger types for GET /for-trigger/{trigger_type} (workflow looked up by trigger type, not name).
# All power the same ApprovalWizardDialog. 1:1 match with ON_* process triggers.
APP_ACTION_TRIGGER_TYPES = frozenset({
    TriggerType.FOR_APPROVAL_RESPONSE.value,
    TriggerType.FOR_SUBSCRIBE.value,
    TriggerType.FOR_REQUEST_REVIEW.value,
    TriggerType.FOR_REQUEST_ACCESS.value,
    TriggerType.FOR_REQUEST_PUBLISH.value,
    TriggerType.FOR_REQUEST_CERTIFY.value,
    TriggerType.FOR_REQUEST_STATUS_CHANGE.value,
})


# Per-trigger permission gate for wizard endpoints. Maps each app-action
# trigger to the FEATURE permission a user needs to interact with that
# wizard (look it up, start a session, advance steps).
#
# None = authenticated only (no feature permission required). Used for
# first-login onboarding screens that must work for users with zero
# feature permissions.
#
# Customers control who can run each wizard by adjusting role-feature
# permissions in the Settings UI — the same lever they already use for
# every other feature in Ontos. The mapping below describes the SEMANTIC
# IDENTITY of each wizard (which feature it belongs to), not customer
# policy.
#
# Background: previously every wizard endpoint required
# `settings:READ_ONLY` (or `data-contracts:READ_WRITE` on session POSTs),
# which gated wizards behind admin-style permissions even when the
# wizard's actual feature was something a Data Consumer could already
# touch (e.g. requesting access to a data product). Two customer incidents
# in May 2026 hit this: Data Consumers couldn't open the access-request
# wizard because they didn't have `settings` read.
WIZARD_PERMISSION_DISPATCH: Dict[str, Optional[tuple]] = {
    TriggerType.FOR_REQUEST_ACCESS.value:        ("access-grants",  FeatureAccessLevel.READ_ONLY),
    TriggerType.FOR_SUBSCRIBE.value:             ("data-products",  FeatureAccessLevel.READ_ONLY),
    TriggerType.FOR_REQUEST_REVIEW.value:        ("data-contracts", FeatureAccessLevel.READ_ONLY),
    TriggerType.FOR_REQUEST_PUBLISH.value:       ("data-products",  FeatureAccessLevel.READ_WRITE),
    TriggerType.FOR_REQUEST_CERTIFY.value:       ("data-contracts", FeatureAccessLevel.READ_WRITE),
    TriggerType.FOR_REQUEST_STATUS_CHANGE.value: ("data-products",  FeatureAccessLevel.READ_WRITE),
    TriggerType.ON_FIRST_ACCESS.value:           None,  # authenticated only — first-login welcome screen
    # `for_approval_response` — relaxed from `notifications:READ_WRITE`
    # (PR K) down to `notifications:READ_ONLY` (PR L). The outer gate
    # only needs to confirm the user is part of the notification system
    # at all; the real authorization is the per-execution check inside
    # `POST /api/workflows/handle-approval`
    # (`_assert_caller_authorized_for_execution`), which verifies the
    # caller is the recipient (or role-member) of the actual approval
    # notification — preventing horizontal privilege escalation.
    # READ_WRITE is too tight: typical Business Owners hold a business
    # role on the entity but only have notifications:Read-only at the
    # app-role level (they read + respond to notifications routed to
    # them; they don't author or modify notifications).
    TriggerType.FOR_APPROVAL_RESPONSE.value:     ("notifications",  FeatureAccessLevel.READ_ONLY),
}


async def enforce_wizard_permission(
    trigger_type: str,
    user_details: UserInfo,
    request: Request,
    *,
    raise_on_unknown: bool = True,
) -> None:
    """Enforce the per-trigger permission gate from ``WIZARD_PERMISSION_DISPATCH``.

    Raises ``HTTPException(403)`` if the user lacks the required feature
    permission. No-op when the dispatch entry is ``None`` (authenticated-only
    triggers like ``on_first_access``).

    If ``trigger_type`` isn't in the dispatch and ``raise_on_unknown`` is True
    (default), raises 400. Set to False for callers that have already
    validated the trigger (e.g. session handlers reading a stored workflow).
    """
    if trigger_type not in WIZARD_PERMISSION_DISPATCH:
        if raise_on_unknown:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown wizard trigger type: {trigger_type}",
            )
        return
    gate = WIZARD_PERMISSION_DISPATCH[trigger_type]
    if gate is None:
        # Authenticated-only trigger; no feature permission required.
        return
    feature_id, required_level = gate
    await enforce_feature_permission(feature_id, required_level, user_details, request)


@router.get("/for-trigger/{trigger_type}", response_model=ProcessWorkflow)
async def get_workflow_for_trigger(
    request: Request,
    trigger_type: str,
    entity_type: Optional[str] = Query(None, description="Optional entity type to match against workflow trigger entity_types"),
    manager: WorkflowsManager = Depends(get_workflows_manager),
    user_details: UserInfo = Depends(get_user_details_from_sdk),
) -> ProcessWorkflow:
    """Get the first active workflow that declares this trigger type.

    Trigger type is the stable contract; workflow names are for display only.
    Optionally pass ?entity_type= to narrow the match to workflows whose
    trigger.entity_types includes the value (or is empty, meaning "all").

    Permission gate is dispatched per trigger type via
    ``WIZARD_PERMISSION_DISPATCH`` — see the comment on that table for the
    rationale. Previously hard-coded to ``settings:READ_ONLY`` which gated
    e.g. the access-request wizard behind admin-style permissions.
    """
    if trigger_type not in APP_ACTION_TRIGGER_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid trigger_type. Allowed: {sorted(APP_ACTION_TRIGGER_TYPES)}",
        )
    # Per-trigger permission check — replaces the blanket settings:READ_ONLY gate.
    await enforce_wizard_permission(trigger_type, user_details, request)
    workflow = manager.get_workflow_by_trigger_type(trigger_type, entity_type=entity_type)
    if not workflow:
        raise HTTPException(
            status_code=404,
            detail=f"No active workflow found for trigger type '{trigger_type}'. Load default workflows from Settings.",
        )
    return workflow


@router.get("/{workflow_id}", response_model=ProcessWorkflow)
async def get_workflow(
    request: Request,
    workflow_id: str,
    manager: WorkflowsManager = Depends(get_workflows_manager),
    user_details: UserInfo = Depends(get_user_details_from_sdk),
) -> ProcessWorkflow:
    """Get a specific workflow by ID.

    Permission model is dispatched on the workflow's shape:

      * **Approval workflows** (``workflow_type == 'approval'``) — gated
        via ``WIZARD_PERMISSION_DISPATCH[trigger.type]``. Mirrors
        ``/for-trigger/{type}`` so the approval-wizard-dialog can fetch
        a single workflow by id without the caller needing
        ``settings:READ_ONLY``. The wizard already obtained the id from
        ``/for-trigger/{type}`` (same dispatch), so this is symmetric.
      * **Process workflows** — gated by ``settings:READ_ONLY`` (admin
        configuration), unchanged.

    A workflow whose trigger isn't in the dispatch table falls back to
    ``settings:READ_ONLY`` (fail-closed).
    """
    workflow = manager.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Dispatch the permission check on the workflow's actual trigger.
    trigger_type = workflow.trigger.type.value if workflow.trigger and workflow.trigger.type else None
    is_approval = getattr(workflow, "workflow_type", None) == WorkflowType.APPROVAL
    if is_approval and trigger_type and trigger_type in WIZARD_PERMISSION_DISPATCH:
        # Reuse PR A's dispatch — None entries (e.g. on_first_access)
        # short-circuit to authenticated-only.
        await enforce_wizard_permission(trigger_type, user_details, request, raise_on_unknown=False)
    else:
        # Process workflows, or approval workflows whose trigger isn't in
        # the dispatch table — keep the original admin-config gate.
        await enforce_feature_permission(
            'settings', FeatureAccessLevel.READ_ONLY, user_details, request,
        )
    return workflow


@router.post("", response_model=ProcessWorkflow)
async def create_workflow(
    request: Request,
    workflow: ProcessWorkflowCreate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: WorkflowsManager = Depends(get_workflows_manager),
    _: bool = Depends(PermissionChecker('settings-workflows', FeatureAccessLevel.READ_WRITE)),
) -> ProcessWorkflow:
    """Create a new workflow."""
    user_email = current_user.email if current_user else None
    
    # Validate workflow
    validation = manager.validate_workflow(workflow)
    if not validation.valid:
        raise HTTPException(status_code=400, detail={"errors": validation.errors})
    
    result = manager.create_workflow(workflow, created_by=user_email)
    
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else 'unknown',
        ip_address=request.client.host if request.client else None,
        feature='process-workflows',
        action='CREATE',
        success=True,
        details={'workflow_id': result.id, 'workflow_name': result.name}
    )
    
    return result


@router.put("/{workflow_id}", response_model=ProcessWorkflow)
async def update_workflow(
    request: Request,
    workflow_id: str,
    workflow: ProcessWorkflowUpdate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: WorkflowsManager = Depends(get_workflows_manager),
    _: bool = Depends(PermissionChecker('settings-workflows', FeatureAccessLevel.READ_WRITE)),
) -> ProcessWorkflow:
    """Update an existing workflow."""
    user_email = current_user.email if current_user else None
    
    # Validate if steps are being updated
    if workflow.steps is not None:
        # Create a full workflow for validation
        existing = manager.get_workflow(workflow_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Workflow not found")
        
        full_workflow = ProcessWorkflowCreate(
            name=workflow.name or existing.name,
            description=workflow.description or existing.description,
            trigger=workflow.trigger or existing.trigger,
            scope=workflow.scope or existing.scope,
            is_active=workflow.is_active if workflow.is_active is not None else existing.is_active,
            steps=workflow.steps,
        )
        validation = manager.validate_workflow(full_workflow)
        if not validation.valid:
            raise HTTPException(status_code=400, detail={"errors": validation.errors})
    
    result = manager.update_workflow(workflow_id, workflow, updated_by=user_email)
    if not result:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else 'unknown',
        ip_address=request.client.host if request.client else None,
        feature='process-workflows',
        action='UPDATE',
        success=True,
        details={'workflow_id': workflow_id, 'workflow_name': result.name}
    )
    
    return result


@router.delete("/{workflow_id}")
async def delete_workflow(
    request: Request,
    workflow_id: str,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: WorkflowsManager = Depends(get_workflows_manager),
    _: bool = Depends(PermissionChecker('settings-workflows', FeatureAccessLevel.ADMIN)),
) -> dict:
    """Delete a workflow (non-default only)."""
    # Check if it's a default workflow
    workflow = manager.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    workflow_name = workflow.name
    
    if workflow.is_default:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete default workflows. Disable it instead."
        )
    
    if not manager.delete_workflow(workflow_id):
        raise HTTPException(status_code=500, detail="Failed to delete workflow")
    
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else 'unknown',
        ip_address=request.client.host if request.client else None,
        feature='process-workflows',
        action='DELETE',
        success=True,
        details={'workflow_id': workflow_id, 'workflow_name': workflow_name}
    )
    
    return {"message": "Workflow deleted"}


@router.post("/{workflow_id}/toggle-active", response_model=ProcessWorkflow)
async def toggle_workflow_active(
    request: Request,
    workflow_id: str,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    is_active: bool = Query(..., description="New active status"),
    manager: WorkflowsManager = Depends(get_workflows_manager),
    _: bool = Depends(PermissionChecker('settings-workflows', FeatureAccessLevel.READ_WRITE)),
) -> ProcessWorkflow:
    """Toggle workflow active status."""
    user_email = current_user.email if current_user else None
    
    result = manager.toggle_active(workflow_id, is_active, updated_by=user_email)
    if not result:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else 'unknown',
        ip_address=request.client.host if request.client else None,
        feature='process-workflows',
        action='TOGGLE_ACTIVE',
        success=True,
        details={'workflow_id': workflow_id, 'is_active': is_active}
    )
    
    return result


@router.post("/{workflow_id}/duplicate", response_model=ProcessWorkflow)
async def duplicate_workflow(
    request: Request,
    workflow_id: str,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    new_name: str = Query(..., description="Name for the duplicated workflow"),
    manager: WorkflowsManager = Depends(get_workflows_manager),
    _: bool = Depends(PermissionChecker('settings-workflows', FeatureAccessLevel.READ_WRITE)),
) -> ProcessWorkflow:
    """Duplicate an existing workflow."""
    user_email = current_user.email if current_user else None
    
    result = manager.duplicate_workflow(workflow_id, new_name, created_by=user_email)
    if not result:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else 'unknown',
        ip_address=request.client.host if request.client else None,
        feature='process-workflows',
        action='DUPLICATE',
        success=True,
        details={'source_workflow_id': workflow_id, 'new_workflow_id': result.id, 'new_name': new_name}
    )
    
    return result


@router.post("/{workflow_id}/execute", response_model=WorkflowExecution)
async def execute_workflow(
    request: Request,
    workflow_id: str,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    entity_type: EntityType = Query(..., description="Entity type"),
    entity_id: str = Query(..., description="Entity ID"),
    entity_name: Optional[str] = Query(None, description="Entity name"),
    manager: WorkflowsManager = Depends(get_workflows_manager),
    executor: WorkflowExecutor = Depends(get_workflow_executor),
    _: bool = Depends(PermissionChecker('settings-workflows', FeatureAccessLevel.READ_WRITE)),
) -> WorkflowExecution:
    """Manually execute a workflow."""
    workflow = manager.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    user_email = current_user.email if current_user else None
    
    # Build trigger context
    trigger_context = TriggerContext(
        entity_type=entity_type.value,
        entity_id=entity_id,
        entity_name=entity_name,
        trigger_type=TriggerType.MANUAL,
        user_email=user_email,
    )
    
    execution = executor.execute_workflow(
        workflow=workflow,
        entity={'id': entity_id, 'name': entity_name, 'type': entity_type.value},
        entity_type=entity_type.value,
        entity_id=entity_id,
        entity_name=entity_name,
        user_email=user_email,
        trigger_context=trigger_context,
    )
    
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else 'unknown',
        ip_address=request.client.host if request.client else None,
        feature='process-workflows',
        action='EXECUTE',
        success=True,
        details={'workflow_id': workflow_id, 'execution_id': execution.id, 'entity_type': entity_type.value, 'entity_id': entity_id}
    )
    
    return execution


@router.post("/validate", response_model=WorkflowValidationResult)
async def validate_workflow(
    request: Request,
    workflow: ProcessWorkflowCreate,
    manager: WorkflowsManager = Depends(get_workflows_manager),
    _: bool = Depends(PermissionChecker('settings-workflows', FeatureAccessLevel.READ_ONLY)),
) -> WorkflowValidationResult:
    """Validate a workflow definition."""
    return manager.validate_workflow(workflow)


@router.post("/load-defaults")
async def load_default_workflows(
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    update_existing: bool = False,
    manager: WorkflowsManager = Depends(get_workflows_manager),
    _: bool = Depends(PermissionChecker('settings-workflows', FeatureAccessLevel.ADMIN)),
) -> dict:
    """Load default workflows from YAML (admin only).
    
    Query params:
        update_existing: If true, updates existing default workflows to match YAML definitions.
    """
    result = manager.load_from_yaml(update_existing=update_existing)
    
    parts = []
    if result['created'] > 0:
        parts.append(f"created {result['created']}")
    if result['updated'] > 0:
        parts.append(f"updated {result['updated']}")
    if result['skipped'] > 0:
        parts.append(f"skipped {result['skipped']} (already exist)")
    
    message = "Workflows: " + ", ".join(parts) if parts else "No workflows to load"
    
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else 'unknown',
        ip_address=request.client.host if request.client else None,
        feature='process-workflows',
        action='LOAD_DEFAULTS',
        success=True,
        details={'created': result['created'], 'updated': result['updated'], 'skipped': result['skipped']}
    )
    
    return {"message": message, **result}


@router.get("/{workflow_id}/referenced-policies")
async def get_workflow_referenced_policies(
    workflow_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker('compliance', FeatureAccessLevel.READ_ONLY)),
) -> Dict[str, Any]:
    """Get list of compliance policies referenced by a workflow.
    
    Scans the workflow's steps for policy_check types and returns the referenced policies.
    """
    workflow = process_workflow_repo.get(db, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    # Get all policy_check steps
    policy_ids = set()
    for step in workflow.steps:
        if step.step_type == 'policy_check' and step.config:
            try:
                config = json.loads(step.config) if isinstance(step.config, str) else step.config
                policy_id = config.get('policy_id')
                if policy_id:
                    policy_ids.add(policy_id)
            except (json.JSONDecodeError, TypeError):
                continue
    
    # Get policy details
    policies = []
    for pid in policy_ids:
        policy = db.get(CompliancePolicyDb, pid)
        if policy:
            policies.append({
                'id': policy.id,
                'name': policy.name,
                'slug': policy.slug,
                'category': policy.category,
                'severity': policy.severity,
                'is_active': policy.is_active,
            })
    
    return {
        'workflow_id': workflow_id,
        'workflow_name': workflow.name,
        'policy_count': len(policies),
        'policies': policies,
    }


# =========================================================================
# Workflow Approval/Resume Endpoints
# =========================================================================

@router.post("/executions/{execution_id}/resume")
async def resume_workflow_execution(
    execution_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    executor: WorkflowExecutor = Depends(get_workflow_executor),
    _: bool = Depends(PermissionChecker('settings-workflows', FeatureAccessLevel.READ_WRITE)),
) -> Dict[str, Any]:
    """Resume a paused workflow execution after approval decision.
    
    This endpoint is called when an approver responds to an approval request.
    The workflow will continue from where it left off, following the on_pass
    or on_fail branch based on the decision.
    
    Request body:
        - approved: bool - Whether the request was approved
        - message: Optional[str] - Message from the approver
        - reason: Optional[str] - Reason for the decision (especially for rejections)
    """
    try:
        body = await request.json()
        approved = body.get('approved', False)
        message = body.get('message')
        reason = body.get('reason')
        
        user_email = current_user.email if current_user else None
        
        # Resume the workflow
        result = executor.resume_workflow(
            execution_id=execution_id,
            step_result=approved,
            result_data={
                'message': message,
                'reason': reason,
                'decision': 'approved' if approved else 'rejected',
            },
            user_email=user_email,
        )
        
        if not result:
            raise HTTPException(
                status_code=404, 
                detail="Execution not found or not in paused state"
            )
        
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'unknown',
            ip_address=request.client.host if request.client else None,
            feature='process-workflows',
            action='RESUME_EXECUTION',
            success=True,
            details={'execution_id': execution_id, 'approved': approved}
        )
        
        logger.info(
            f"Workflow execution {execution_id} resumed with decision: "
            f"{'approved' if approved else 'rejected'}"
        )
        
        return {
            'execution_id': result.id,
            'status': result.status.value,
            'success_count': result.success_count,
            'failure_count': result.failure_count,
            'message': f"Workflow {'approved and continued' if approved else 'rejected'}",
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error resuming workflow {execution_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to resume workflow")


@router.get("/executions/paused/by-entity")
async def get_paused_executions_for_entity(
    db: DBSessionDep,
    entity_type: str = Query(..., description="Entity type (e.g., 'data_contract', 'dataset')"),
    entity_id: str = Query(..., description="Entity ID"),
    _: bool = Depends(PermissionChecker('settings-workflows', FeatureAccessLevel.READ_ONLY)),
) -> Dict[str, Any]:
    """Find paused workflow executions for a specific entity.
    
    This is useful for finding which workflow(s) need to be resumed when
    handling an approval response for an entity.
    """
    # Query paused executions
    paused = workflow_execution_repo.list_all(db, status='paused', limit=100)
    
    # Filter by entity in trigger context
    matching = []
    for exe in paused:
        if exe.trigger_context:
            try:
                tc = json.loads(exe.trigger_context) if isinstance(exe.trigger_context, str) else exe.trigger_context
                if tc.get('entity_type') == entity_type and tc.get('entity_id') == entity_id:
                    matching.append({
                        'id': exe.id,
                        'workflow_id': exe.workflow_id,
                        'workflow_name': exe.workflow.name if exe.workflow else None,
                        'current_step_id': exe.current_step_id,
                        'triggered_by': exe.triggered_by,
                        'started_at': exe.started_at.isoformat() if exe.started_at else None,
                    })
            except (json.JSONDecodeError, TypeError):
                continue
    
    return {
        'entity_type': entity_type,
        'entity_id': entity_id,
        'paused_count': len(matching),
        'executions': matching,
    }


def _find_approval_notifications_for_execution(
    db: Session, execution_id: str
) -> List[Notification]:
    """Return all `workflow_approval` notifications whose payload targets
    ``execution_id``.

    Returned objects are pydantic ``Notification`` models (validated from
    the DB rows) so they can be fed directly to
    ``NotificationsManager.can_user_access_notification``.

    We intentionally do NOT filter on ``read == False`` here — a previously
    auto-marked-read notification still encodes "this user/role was an
    authorized approver for this execution", which is exactly what we
    want when authorizing a fresh approval POST.
    """
    rows = db.query(NotificationDb).filter(
        NotificationDb.action_type == 'workflow_approval'
    ).all()
    matches: List[Notification] = []
    for row in rows:
        try:
            payload = row.action_payload
            if isinstance(payload, str):
                payload = json.loads(payload)
            if payload and payload.get('execution_id') == execution_id:
                matches.append(Notification.model_validate(row))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    return matches


def _assert_caller_authorized_for_execution(
    db: Session,
    notifications_manager: NotificationsManager,
    execution_id: str,
    user_info: UserInfo,
) -> List[Notification]:
    """Authorize ``user_info`` to act on the paused workflow execution.

    A caller is authorized iff there exists at least one
    ``workflow_approval`` notification for ``execution_id`` that the caller
    can access under
    ``NotificationsManager.can_user_access_notification`` (direct
    recipient, role membership via ``recipient_role_id``, or admin
    fallback for role-with-no-groups).

    This is the per-execution check that backs the relaxed outer gate on
    ``POST /handle-approval`` (notifications:READ_WRITE instead of
    settings:READ_WRITE). It prevents horizontal privilege escalation —
    a Business Owner with notifications RW cannot approve an execution
    they were never notified about.

    Raises 403 with a descriptive detail on failure. Returns the matching
    notifications on success so callers can avoid re-fetching them.

    NOTE: name kept generic (``_assert_caller_authorized_for_execution``)
    so PR L can lift this for ``resume_workflow`` / similar.
    """
    candidates = _find_approval_notifications_for_execution(db, execution_id)
    if not candidates:
        raise HTTPException(
            status_code=403,
            detail="You are not an authorized approver for this execution",
        )
    for notification in candidates:
        if notifications_manager.can_user_access_notification(
            db=db, notification=notification, user_info=user_info
        ):
            return candidates
    raise HTTPException(
        status_code=403,
        detail="You are not an authorized approver for this execution",
    )


@router.post("/handle-approval")
async def handle_workflow_approval(
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    executor: WorkflowExecutor = Depends(get_workflow_executor),
    notifications_manager: NotificationsManager = Depends(get_notifications_manager),
    # Outer gate is `notifications:READ_ONLY` (PR L). The real
    # authorization is the per-execution check below
    # (`_assert_caller_authorized_for_execution`), which confirms the
    # caller was an actual recipient/role-member of the approval
    # notification. The outer gate exists for defense-in-depth — it
    # ensures the caller is part of the notification system at all
    # (rejects users with `notifications:None`), but doesn't require
    # write-level notification permissions which most non-admin
    # Business Owners legitimately don't have. Approving a notification
    # routed to you is *reading* + responding; not a separate "write"
    # action on the notification feature itself.
    #
    # Two-layer defense satisfied (per OWASP API1+API5):
    #   * Function-level (outer): you can see notifications → can be a
    #     workflow recipient. Excludes users with no notification access.
    #   * Object-level (inner): you must be the specific recipient of
    #     this execution's approval notification (or have admin bypass).
    #
    # History: was `settings:READ_WRITE` (pre-PR-K, semantically wrong),
    # then `notifications:READ_WRITE` (PR K, too tight for non-admin
    # BOs), now `notifications:READ_ONLY` (PR L, the minimum that
    # preserves defense-in-depth without blocking legitimate approvers).
    _: bool = Depends(PermissionChecker('notifications', FeatureAccessLevel.READ_ONLY)),
) -> Dict[str, Any]:
    """Handle a workflow approval from a notification action.

    This is the endpoint called when a user responds to an approval notification
    with action_type='workflow_approval'. It finds the execution from the
    action_payload and resumes it.

    Request body:
        - execution_id: str - ID of the paused execution
        - approved: bool - Whether the request was approved
        - message: Optional[str] - Message/reason from the approver (e.g. from default approval response workflow)
        - reason: Optional[str] - Reason for the decision (alias for message)
    """
    try:
        body = await request.json()
        execution_id = body.get('execution_id')
        approved = body.get('approved', False)
        message = body.get('message') or body.get('reason')

        if not execution_id:
            raise HTTPException(status_code=400, detail="execution_id is required")

        # Per-execution authorization (PR K). Raises 403 if the caller
        # isn't a recipient/role-member of any approval notification for
        # this execution. Must run BEFORE resume_workflow side effects.
        _assert_caller_authorized_for_execution(
            db=db,
            notifications_manager=notifications_manager,
            execution_id=execution_id,
            user_info=current_user,
        )

        user_email = current_user.email if current_user else None

        # Resume the workflow
        result = executor.resume_workflow(
            execution_id=execution_id,
            step_result=approved,
            result_data={
                'message': message,
                'reason': message,
                'decision': 'approved' if approved else 'rejected',
            },
            user_email=user_email,
        )
        
        if not result:
            raise HTTPException(
                status_code=404,
                detail="Execution not found or not in paused state"
            )
        
        # Mark the notification as handled
        from src.repositories.notification_repository import notification_repo
        from src.db_models.notifications import NotificationDb
        
        # Find and mark notifications for this execution as read
        notifications = db.query(NotificationDb).filter(
            NotificationDb.action_type == 'workflow_approval',
            NotificationDb.read == False
        ).all()
        
        for notif in notifications:
            try:
                payload = json.loads(notif.action_payload) if isinstance(notif.action_payload, str) else notif.action_payload
                if payload and payload.get('execution_id') == execution_id:
                    notif.read = True
                    # Mark the action as handled with decision info
                    payload['handled'] = True
                    payload['decision'] = 'approved' if approved else 'rejected'
                    payload['handled_by'] = user_email
                    payload['handled_at'] = datetime.utcnow().isoformat()
                    notif.action_payload = json.dumps(payload)
                    db.add(notif)
            except (json.JSONDecodeError, TypeError):
                continue
        
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'unknown',
            ip_address=request.client.host if request.client else None,
            feature='process-workflows',
            action='HANDLE_APPROVAL',
            success=True,
            details={'execution_id': execution_id, 'approved': approved}
        )
        
        db.commit()
        
        logger.info(f"Workflow approval handled for execution {execution_id}: {'approved' if approved else 'rejected'}")
        
        return {
            'execution_id': result.id,
            'status': result.status.value,
            'message': f"Request {'approved' if approved else 'rejected'} successfully",
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error handling workflow approval: {e}")
        raise HTTPException(status_code=500, detail="Failed to handle approval")


# ============================================================================
# Execution Administration Endpoints
# ============================================================================

@router.post("/executions/{execution_id}/cancel")
async def cancel_execution(
    execution_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    _: bool = Depends(PermissionChecker('process-workflows', FeatureAccessLevel.ADMIN)),
) -> Dict[str, Any]:
    """Cancel a running or paused workflow execution.
    
    Requires ADMIN permission. Running and paused executions can be cancelled.
    """
    user_email = current_user.email if current_user else None
    
    result = workflow_execution_repo.cancel(db, execution_id, cancelled_by=user_email)
    
    if not result:
        raise HTTPException(
            status_code=404,
            detail="Execution not found or cannot be cancelled (must be running or paused)"
        )
    
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else 'unknown',
        ip_address=request.client.host if request.client else None,
        feature='process-workflows',
        action='CANCEL_EXECUTION',
        success=True,
        details={'execution_id': execution_id}
    )
    
    logger.info(f"Execution {execution_id} cancelled by {user_email}")
    
    return {
        'execution_id': result.id,
        'status': result.status,
        'message': 'Execution cancelled successfully',
    }


@router.post("/executions/{execution_id}/retry")
async def retry_execution(
    execution_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    executor: WorkflowExecutor = Depends(get_workflow_executor),
    _: bool = Depends(PermissionChecker('process-workflows', FeatureAccessLevel.ADMIN)),
) -> Dict[str, Any]:
    """Retry a failed workflow execution from the beginning.
    
    Requires ADMIN permission. Only failed executions can be retried.
    Resets the execution state and re-runs all steps.
    """
    # Reset the execution
    reset_result = workflow_execution_repo.reset_for_retry(db, execution_id)
    
    if not reset_result:
        raise HTTPException(
            status_code=404,
            detail="Execution not found or cannot be retried (must be failed)"
        )
    
    # Re-execute the workflow
    try:
        workflow = process_workflow_repo.get(db, reset_result.workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="Associated workflow not found")
        
        # Get trigger context to re-execute
        trigger_context = json.loads(reset_result.trigger_context) if reset_result.trigger_context else {}
        
        # Get entity data from trigger context
        entity_data = trigger_context.get('entity_data', {}) or {}
        
        result = executor.execute_workflow(
            workflow,
            entity_data,  # positional argument
            entity_type=trigger_context.get('entity_type', 'unknown'),
            entity_id=trigger_context.get('entity_id', ''),
            entity_name=trigger_context.get('entity_name'),
            user_email=trigger_context.get('user_email'),
            execution_id=execution_id,  # Reuse the same execution record
        )
        
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'unknown',
            ip_address=request.client.host if request.client else None,
            feature='process-workflows',
            action='RETRY_EXECUTION',
            success=True,
            details={'execution_id': execution_id}
        )
        
        logger.info(f"Execution {execution_id} retried, new status: {result.status}")
        
        return {
            'execution_id': result.id,
            'status': result.status.value,
            'message': 'Execution retry initiated',
        }
    except Exception as e:
        logger.exception(f"Error retrying execution {execution_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retry execution: {str(e)}")


@router.delete("/executions/{execution_id}")
async def delete_execution(
    execution_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    _: bool = Depends(PermissionChecker('process-workflows', FeatureAccessLevel.ADMIN)),
) -> Dict[str, Any]:
    """Delete a workflow execution.
    
    Requires ADMIN permission. Running and paused executions should be
    cancelled before deletion.
    """
    # Check if execution exists and its status
    execution = workflow_execution_repo.get(db, execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    
    if execution.status in ('running', 'paused'):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete {execution.status} execution. Cancel it first."
        )
    
    success = workflow_execution_repo.delete(db, execution_id)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete execution")
    
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else 'unknown',
        ip_address=request.client.host if request.client else None,
        feature='process-workflows',
        action='DELETE_EXECUTION',
        success=True,
        details={'execution_id': execution_id}
    )
    
    logger.info(f"Execution {execution_id} deleted")
    
    return {
        'message': 'Execution deleted successfully',
        'execution_id': execution_id,
    }


@router.delete("/executions")
async def delete_executions_bulk(
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    older_than_days: Optional[int] = Query(None, description="Delete executions older than X days"),
    status: Optional[str] = Query(None, description="Filter by status (failed, succeeded, cancelled)"),
    workflow_id: Optional[str] = Query(None, description="Filter by workflow ID"),
    _: bool = Depends(PermissionChecker('process-workflows', FeatureAccessLevel.ADMIN)),
) -> Dict[str, Any]:
    """Bulk delete workflow executions matching criteria.
    
    Requires ADMIN permission. Running and paused executions are never deleted.
    At least one filter parameter is required.
    """
    if older_than_days is None and status is None and workflow_id is None:
        raise HTTPException(
            status_code=400,
            detail="At least one filter parameter is required (older_than_days, status, or workflow_id)"
        )
    
    # Validate status if provided
    valid_statuses = ['failed', 'succeeded', 'cancelled']
    if status and status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
        )
    
    count = workflow_execution_repo.delete_bulk(
        db,
        older_than_days=older_than_days,
        status=status,
        workflow_id=workflow_id,
    )
    
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else 'unknown',
        ip_address=request.client.host if request.client else None,
        feature='process-workflows',
        action='DELETE_EXECUTIONS_BULK',
        success=True,
        details={'count': count, 'older_than_days': older_than_days, 'status': status, 'workflow_id': workflow_id}
    )
    
    logger.info(f"Bulk delete: {count} executions deleted (older_than_days={older_than_days}, status={status}, workflow_id={workflow_id})")
    
    return {
        'message': f'{count} executions deleted',
        'count': count,
    }


@router.get("/executions/{execution_id}")
async def get_execution(
    execution_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker('process-workflows', FeatureAccessLevel.READ_ONLY)),
) -> Dict[str, Any]:
    """Get detailed information about a workflow execution.
    
    Returns the execution with all step execution details.
    """
    execution = workflow_execution_repo.get(db, execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    
    # Get workflow for additional context
    workflow = process_workflow_repo.get(db, execution.workflow_id) if execution.workflow_id else None
    
    # Parse trigger context
    trigger_context = {}
    if execution.trigger_context:
        try:
            trigger_context = json.loads(execution.trigger_context)
        except json.JSONDecodeError:
            pass
    
    # Get current step name
    current_step_name = None
    if execution.current_step_id and workflow and workflow.steps:
        for step in workflow.steps:
            if step.step_id == execution.current_step_id:
                current_step_name = step.name or execution.current_step_id
                break
    
    # Build step executions list
    step_executions = []
    for se in (execution.step_executions or []):
        step_executions.append({
            'id': se.id,
            'step_id': se.step_id,
            'status': se.status,
            'passed': se.passed,
            'result_data': json.loads(se.result_data) if se.result_data else None,
            'error_message': se.error_message,
            'duration_ms': se.duration_ms,
            'started_at': se.started_at.isoformat() if se.started_at else None,
            'finished_at': se.finished_at.isoformat() if se.finished_at else None,
        })
    
    return {
        'id': execution.id,
        'workflow_id': execution.workflow_id,
        'workflow_name': workflow.name if workflow else None,
        'status': execution.status,
        'current_step_id': execution.current_step_id,
        'current_step_name': current_step_name,
        'success_count': execution.success_count,
        'failure_count': execution.failure_count,
        'error_message': execution.error_message,
        'triggered_by': execution.triggered_by,
        'started_at': execution.started_at.isoformat() if execution.started_at else None,
        'finished_at': execution.finished_at.isoformat() if execution.finished_at else None,
        'entity_type': trigger_context.get('entity_type'),
        'entity_id': trigger_context.get('entity_id'),
        'entity_name': trigger_context.get('entity_name'),
        'step_executions': step_executions,
        'workflow_steps': [
            {
                'step_id': s.step_id,
                'name': s.name,
                'step_type': s.step_type,
                'order': s.order,
            }
            for s in (workflow.steps if workflow else [])
        ],
    }


def register_routes(app):
    """Register workflow routes with the FastAPI app."""
    app.include_router(router)
    logger.info("Workflow routes registered with prefix /api/workflows")

