import uuid # Import uuid
from datetime import datetime # Import datetime
from typing import Dict, Optional, List

from fastapi import APIRouter, Request, Depends, HTTPException
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound

from src.models.users import UserInfo
from src.models.users import UserPermissions
from src.models.notifications import Notification, NotificationType
from src.models.settings import RoleAccessRequest, AppRole
from src.common.config import get_settings, Settings
from src.controller.authorization_manager import AuthorizationManager
from src.common.dependencies import get_auth_manager, get_db, AuditManagerDep, AuditCurrentUserDep, DBSessionDep # Import get_db
from src.common.dependencies import get_settings_manager, get_notifications_manager
from src.controller.settings_manager import SettingsManager
from pydantic import BaseModel
from src.controller.notifications_manager import NotificationsManager
from src.common.features import FeatureAccessLevel
from src.common.authorization import get_user_details_from_sdk, _try_resolve_test_override
from sqlalchemy.orm import Session # Import Session

from src.common.logging import get_logger
from src.common.deployment_dependencies import get_deployment_policy_manager
from src.controller.deployment_policy_manager import DeploymentPolicyManager

logger = get_logger(__name__)

# Define router at the module level with /api prefix
router = APIRouter(prefix="/api", tags=["User"])

# Original endpoint: Get user info directly from headers (with local dev check)
@router.get("/user/info", response_model=UserInfo)
async def get_user_info_from_headers(request: Request, settings: Settings = Depends(get_settings)):
    """Get basic user information directly from request headers, or mock data if local dev."""
    logger.info("Request received for /api/user/info")

    # Per-request test-user override takes precedence over both mock-mode and headers.
    override = _try_resolve_test_override(
        request, settings, manager=None, real_ip=request.headers.get("X-Real-Ip")
    )
    if override is not None:
        logger.info(f"/user/info: returning test override identity for {override.email}")
        return override

    # Check for local development environment
    if settings.ENV.upper().startswith("LOCAL") or getattr(settings, "MOCK_USER_DETAILS", False):
        # Build from overrides consistent with get_user_details_from_sdk
        email = settings.MOCK_USER_EMAIL or "unknown@dev.local"
        username = settings.MOCK_USER_USERNAME or "localdev"
        name = settings.MOCK_USER_NAME or "Local Developer"
        ip = settings.MOCK_USER_IP or "127.0.0.1"
        logger.info(
            f"Local/mock /user/info: using overrides(email={email}, username={username}, user={name}, ip={ip})"
        )
        simple_mock_user = UserInfo(
            email=email,
            username=username,
            user=name,
            ip=ip,
            groups=None # This endpoint doesn't include groups
        )
        return simple_mock_user

    # Original logic for non-local environments
    headers = request.headers
    logger.info("Non-local environment, reading headers for /user/info.")
    user_info = UserInfo(
        email=headers.get("X-Forwarded-Email"),
        username=headers.get("X-Forwarded-User"),
        user=headers.get("X-Forwarded-User"),
        ip=headers.get("X-Real-Ip"),
        groups=None # Headers don't contain groups
    )
    logger.info(f"User information from headers: email={user_info.email}, username={user_info.username}, user={user_info.user}, ip={user_info.ip}")
    return user_info

# --- User Details Endpoint (using the dependency) --- 
@router.get("/user/details", response_model=UserInfo)
async def get_user_details(
    user_info: UserInfo = Depends(get_user_details_from_sdk)
) -> UserInfo:
    """Returns detailed user information obtained via the SDK (or mock data)."""
    # The dependency get_user_details_from_sdk handles fetching or mocking.
    # We just return the result provided by the dependency.
    # The dependency also handles raising HTTPException on errors.
    logger.info(f"Returning user details for '{user_info.user or user_info.email}' from dependency.")
    return user_info

# --- User Permissions Endpoint --- 

@router.get("/user/pending-approvals")
async def get_pending_approvals(
    request: Request,
    db: DBSessionDep,
    user_details: UserInfo = Depends(get_user_details_from_sdk),
):
    """Active ``on_first_access`` workflows the current user has not yet
    accepted at the workflow's current version.

    Used by the frontend on app mount: the welcome / ToU dialog is rendered
    as a real Approval Workflow wizard rather than a hardcoded settings
    dialog. Each entry triggers an ApprovalWizardDialog flow against
    ``entity_type='user'`` and ``entity_id=<user_email>``. When the user
    completes the wizard, an ``agreements`` row is persisted and the
    endpoint returns one fewer item on the next reload. If an admin edits
    the workflow text, ``workflow.version`` increments and every user is
    re-prompted on next mount.

    Returns ``{"workflows": [{workflow_id, workflow_name, workflow_version}, ...]}``.
    """
    from src.controller.agreement_wizard_manager import AgreementWizardManager
    user_email = user_details.email or user_details.user
    if not user_email:
        return {"workflows": []}
    manager = AgreementWizardManager(db)
    return {"workflows": manager.get_pending_first_access_workflows(user_email)}


@router.get("/user/permissions", response_model=UserPermissions)
async def get_current_user_permissions(
    request: Request,
    user_details: UserInfo = Depends(get_user_details_from_sdk),
    auth_manager: AuthorizationManager = Depends(get_auth_manager),
    settings_manager: SettingsManager = Depends(get_settings_manager)
) -> Dict[str, FeatureAccessLevel]:
    """Get the effective feature permissions for the current user based on their groups."""
    logger.info(f"Request received for /api/user/permissions for user '{user_details.user or user_details.email}'")

    if not user_details.groups:
        logger.warning(f"User '{user_details.user or user_details.email}' has no groups. Returning empty permissions.")
        
        return {}

    try:
        # Apply override if set for this user
        applied_role_id = settings_manager.get_applied_role_override_for_user(user_details.email)
        if applied_role_id:
            role_perms = settings_manager.get_feature_permissions_for_role_id(applied_role_id)
            return role_perms
        # Otherwise compute from groups
        return auth_manager.get_user_effective_permissions(user_details.groups)

    except HTTPException:
        raise # Re-raise exceptions from dependencies
    except Exception as e:
        logger.error(f"Unexpected error calculating permissions for user '{user_details.user or user_details.email}': {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Error calculating user permissions."
        )

@router.get("/user/actual-permissions", response_model=UserPermissions)
async def get_actual_user_permissions(
    request: Request,
    user_details: UserInfo = Depends(get_user_details_from_sdk),
    auth_manager: AuthorizationManager = Depends(get_auth_manager)
) -> Dict[str, FeatureAccessLevel]:
    """Get actual feature permissions based on user groups, ignoring any role overrides.

    This endpoint always returns permissions computed from the user's group memberships,
    never applying role overrides. It's used for UI authorization decisions like determining
    if a user should be able to switch roles, regardless of their current role override.
    """
    logger.info(f"Request received for /api/user/actual-permissions for user '{user_details.user or user_details.email}'")

    if not user_details.groups:
        logger.warning(f"User '{user_details.user or user_details.email}' has no groups. Returning empty actual permissions.")
        return {}

    try:
        # Always compute from groups, never apply overrides
        return auth_manager.get_user_effective_permissions(user_details.groups)

    except HTTPException:
        raise # Re-raise exceptions from dependencies
    except Exception as e:
        logger.error(f"Unexpected error calculating actual permissions for user '{user_details.user or user_details.email}': {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Error calculating actual user permissions."
        )

# --- Role override endpoints ---
class RoleOverrideRequest(BaseModel):
    role_id: Optional[str] = None

@router.post("/user/role-override")
async def set_role_override(
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    payload: RoleOverrideRequest,
    user_details: UserInfo = Depends(get_user_details_from_sdk),
    auth_manager: AuthorizationManager = Depends(get_auth_manager),
    settings_manager: SettingsManager = Depends(get_settings_manager)
):
    """Set or clear the applied role override for the current user.

    Body: { "role_id": "<uuid>" } or { "role_id": null } to clear.

    Authorization: admins may override to any role (impersonation). Non-admins may only
    override to a role whose assigned_groups intersect their own groups. Clearing is
    always allowed.
    """
    role_id = payload.role_id
    # Determine if caller is an Ontos admin (member of an AppRole flagged is_admin).
    # Computed from groups so the override cannot bootstrap admin, and intentionally
    # decoupled from settings:ADMIN (see issue #404).
    caller_is_admin = auth_manager.is_user_ontos_admin(user_details.groups)

    try:
        settings_manager.set_applied_role_override_for_user(
            user_details.email,
            role_id,
            caller_groups=user_details.groups,
            caller_is_admin=caller_is_admin,
        )

        audit_manager.log_action(
            db=db,
            username=user_details.username if user_details else 'unknown',
            ip_address=request.client.host if request.client else None,
            feature='user',
            action='SET_ROLE_OVERRIDE',
            success=True,
            details={'role_id': role_id}
        )

        return {"status": "ok"}
    except PermissionError as e:
        logger.warning(
            "Forbidden role override for user %s -> role_id=%s: %s",
            user_details.email, role_id, e,
        )
        audit_manager.log_action(
            db=db,
            username=user_details.username if user_details else 'unknown',
            ip_address=request.client.host if request.client else None,
            feature='user',
            action='SET_ROLE_OVERRIDE',
            success=False,
            details={'role_id': role_id, 'reason': 'not_a_member'},
        )
        raise HTTPException(status_code=403, detail="Not a member of the requested role")
    except ValueError as e:
        logger.error("Invalid role override request for user %s: %s", user_details.email, e)
        raise HTTPException(status_code=400, detail="Invalid role override request")

@router.get("/user/role-override")
async def get_role_override(
    user_details: UserInfo = Depends(get_user_details_from_sdk),
    settings_manager: SettingsManager = Depends(get_settings_manager)
):
    """Return the currently applied role override id for the user (or null)."""
    role_id = settings_manager.get_applied_role_override_for_user(user_details.email)
    return {"role_id": role_id}

@router.get("/user/actual-role")
async def get_actual_role(
    user_details: UserInfo = Depends(get_user_details_from_sdk),
    settings_manager: SettingsManager = Depends(get_settings_manager)
):
    """Return the canonical role determined from the user's groups (ignores override)."""
    role = settings_manager.get_canonical_role_for_groups(user_details.groups)
    return {"role": role.dict() if role else None}



# --- Requestable Roles Endpoint ---
@router.get("/user/requestable-roles", response_model=List[AppRole])
async def get_requestable_roles(
    user_details: UserInfo = Depends(get_user_details_from_sdk),
    settings_manager: SettingsManager = Depends(get_settings_manager)
) -> List[AppRole]:
    """Get list of roles that the current user can request based on their current role(s).
    
    For users with no role, returns roles that are configured to be requestable by 
    users without any role (__NO_ROLE__).
    """
    logger.info(f"Request received for /api/user/requestable-roles for user '{user_details.user or user_details.email}'")
    
    try:
        requestable_roles = settings_manager.get_requestable_roles_for_user(user_details.groups)
        logger.info(f"User '{user_details.email}' can request {len(requestable_roles)} roles")
        return requestable_roles
    except Exception as e:
        logger.error(f"Error getting requestable roles for user '{user_details.email}': {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Error retrieving requestable roles."
        )


# --- Role Access Request Endpoint ---
@router.post("/user/request-role/{role_id}")
async def request_role_access(
    role_id: str,
    request_body: RoleAccessRequest,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    user_details: UserInfo = Depends(get_user_details_from_sdk),
    settings_manager: SettingsManager = Depends(get_settings_manager),
    notifications_manager: NotificationsManager = Depends(get_notifications_manager)
):
    """Initiates a request for a user to be added to an application role with optional reason."""
    logger.info(f"User '{user_details.email}' requesting access to role ID: {role_id}")

    requester_email = user_details.email
    if not requester_email:
         logger.error("Cannot process role request: User email not found in details.")
         raise HTTPException(status_code=400, detail="User email not found, cannot process request.")

    try:
        role = settings_manager.get_app_role(role_id)
        if not role:
            raise HTTPException(status_code=404, detail=f"Role with ID '{role_id}' not found.")
        role_name = role.name
    except Exception as e:
        logger.error(f"Error retrieving role {role_id}: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving role details.")

    # Validate that the user can request this role based on their current roles
    if not settings_manager.can_user_request_role(role_id, user_details.groups):
        logger.warning(f"User '{requester_email}' is not authorized to request role '{role_name}'")
        raise HTTPException(
            status_code=403,
            detail=f"You are not authorized to request the role '{role_name}'. Please check which roles you can request."
        )

    # Get the approver role names for this role
    approver_role_names = settings_manager.get_approver_role_names(role_id)
    if not approver_role_names:
        # Default to Admin if no approvers configured
        approver_role_names = ["Admin"]
        logger.warning(f"No approvers configured for role '{role_name}', defaulting to Admin")

    # Check for duplicate pending requests
    from src.db_models.notifications import NotificationDb
    import json

    try:
        existing_requests = db.query(NotificationDb).filter(
            NotificationDb.action_type == "handle_role_request",
            NotificationDb.read == False
        ).all()

        # Check if any match this user and role
        for existing in existing_requests:
            if existing.action_payload:
                try:
                    payload = json.loads(existing.action_payload)
                    if (payload.get("requester_email") == requester_email and
                        payload.get("role_id") == role_id):
                        logger.warning(f"Duplicate role request detected for user '{requester_email}' and role '{role_id}'")
                        raise HTTPException(
                            status_code=400,
                            detail=f"You already have a pending request for the role '{role_name}'. Please wait for review."
                        )
                except json.JSONDecodeError:
                    continue  # Skip malformed payload
    except HTTPException:
        raise  # Re-raise HTTPException
    except Exception as e:
        logger.error(f"Error checking for duplicate requests: {e}", exc_info=True)
        # Don't fail the request if duplicate check fails, just log it

    user_message = request_body.message.strip() if request_body.message else None

    # --- Trigger workflow for role access request --- #
    try:
        from src.common.workflow_triggers import get_trigger_registry
        from src.models.process_workflows import EntityType
        
        trigger_registry = get_trigger_registry(db)
        entity_data = {
            "role_id": role_id,
            "role_name": role_name,
            "requester_email": requester_email,
            "requester_message": user_message,
            "approver_role_names": approver_role_names,
        }
        
        executions = trigger_registry.on_request_access(
            entity_type=EntityType.ROLE,
            entity_id=role_id,
            entity_name=role_name,
            entity_data=entity_data,
            user_email=requester_email,
            blocking=True,  # Wait for workflow to complete/pause
        )
        
        if executions:
            logger.info(f"Triggered {len(executions)} workflow(s) for role access request")
            
            audit_manager.log_action(
                db=db,
                username=user_details.username if user_details else 'unknown',
                ip_address=request.client.host if request.client else None,
                feature='user',
                action='REQUEST_ROLE_ACCESS',
                success=True,
                details={'role_id': role_id, 'role_name': role_name}
            )
            
            db.commit()
            return {"message": "Role access request submitted successfully. Workflow triggered for approval."}
    except Exception as workflow_err:
        logger.error(f"Failed to trigger workflow for role access request: {workflow_err}", exc_info=True)

    # Fallback to direct notification if no workflow configured
    placeholder_id = str(uuid.uuid4())
    now = datetime.utcnow()

    try:
        approver_list = ", ".join(approver_role_names)
        user_desc = f"Your request to access the role '{role_name}' has been submitted for review by: {approver_list}."
        if user_message:
            user_desc += f"\n\nYour message: {user_message}"

        user_notification = Notification(
            id=placeholder_id,
            created_at=now,
            type=NotificationType.INFO,
            title="Role Access Request Submitted",
            subtitle=f"Role: {role_name}",
            description=user_desc,
            recipient=requester_email,
            can_delete=True
        )
        notifications_manager.create_notification(db=db, notification=user_notification)
        logger.info(f"No workflow configured; sent direct notification to requester '{requester_email}'")

        approver_desc = f"User '{requester_email}' has requested access to the role '{role_name}'."
        if user_message:
            approver_desc += f"\n\nRequester's message: {user_message}"

        for approver_role_name in approver_role_names:
            approver_notification = Notification(
                id=str(uuid.uuid4()),
                created_at=now,
                type=NotificationType.ACTION_REQUIRED,
                title="Role Access Request Received",
                subtitle=f"User: {requester_email}",
                description=approver_desc,
                recipient=approver_role_name,
                can_delete=False,
                action_type="handle_role_request",
                action_payload={
                    "requester_email": requester_email,
                    "role_id": role_id,
                    "role_name": role_name,
                    "requester_message": user_message
                }
            )
            notifications_manager.create_notification(db=db, notification=approver_notification)
            logger.info(f"Created notification for approver role '{approver_role_name}'")

        audit_manager.log_action(
            db=db,
            username=user_details.username if user_details else 'unknown',
            ip_address=request.client.host if request.client else None,
            feature='user',
            action='REQUEST_ROLE_ACCESS',
            success=True,
            details={'role_id': role_id, 'role_name': role_name}
        )

        db.commit()
        return {"message": "Role access request submitted successfully."} 

    except Exception as e:
        logger.error(f"Error creating notifications for role request (Role: {role_id}, User: {requester_email}): {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to process role access request due to an internal error.")


# --- Deployment Policy Endpoint ---

@router.get("/user/deployment-policy")
async def get_user_deployment_policy(
    user_details: UserInfo = Depends(get_user_details_from_sdk),
    deployment_manager: DeploymentPolicyManager = Depends(get_deployment_policy_manager)
):
    """Get current user's deployment policy (allowed catalogs/schemas).
    
    Returns the effective deployment policy after:
    - Resolving role overrides
    - Merging policies from all user's groups
    - Resolving template variables ({username}, {email}, etc.)
    """
    try:
        policy = deployment_manager.get_effective_policy(user_details)
        
        logger.info(
            f"Retrieved deployment policy for {user_details.email}: "
            f"{len(policy.allowed_catalogs)} catalogs, "
            f"require_approval={policy.require_approval}"
        )
        
        return policy.dict()
    
    except Exception as e:
        logger.error(f"Error retrieving deployment policy for {user_details.email}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve deployment policy"
        )


# Register routes function simply includes the module-level router
def register_routes(app):
    """Register user routes with the FastAPI app."""
    app.include_router(router)
    logger.info("User routes registered (info and details)")
