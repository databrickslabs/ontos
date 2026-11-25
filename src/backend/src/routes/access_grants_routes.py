"""
FastAPI routes for Access Grants management.

Endpoints for requesting, approving, and managing time-limited access grants.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, Request, status

from src.common.authorization import PermissionChecker, is_ontos_admin
from src.common.dependencies import (
    AuditCurrentUserDep,
    AuditManagerDep,
    CurrentUserDep,
    DBSessionDep,
    NotificationsManagerDep,
)
from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger
from src.controller.access_grants_manager import (
    AccessGrantsManager,
    AccessRequestAlreadyDecidedError,
    OwnAccessRequestError,
    get_access_grants_manager,
)
from src.models.access_grants import (
    AccessGrantCreateDirect,
    AccessGrantDurationConfigCreate,
    AccessGrantDurationConfigList,
    AccessGrantDurationConfigResponse,
    AccessGrantHandlePayload,
    AccessGrantList,
    AccessGrantRequestCreate,
    AccessGrantRequestList,
    AccessGrantRequestResponse,
    AccessGrantRequestStatus,
    AccessGrantResponse,
    AccessGrantRevokePayload,
    AccessGrantSummary,
    UserAccessGrantsSummary,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/access-grants", tags=["Access Grants"])

ACCESS_GRANTS_FEATURE_ID = "access-grants"


def register_routes(app):
    """Register access grants routes with the FastAPI app."""
    app.include_router(router)


def get_manager(
    request: Request,
    notifications: NotificationsManagerDep
) -> AccessGrantsManager:
    """Get the access grants manager with dependencies."""
    # Try to get from app state first
    manager = getattr(request.app.state, 'access_grants_manager', None)
    if manager:
        return manager
    
    # Create a new instance with notifications manager
    return AccessGrantsManager(notifications_manager=notifications)


# ============================================================================
# Access Request Endpoints
# ============================================================================

@router.post(
    "/request",
    response_model=AccessGrantRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Access Request",
    description="Submit a request for time-limited access to an asset."
)
async def create_access_request(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: CurrentUserDep,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    notifications: NotificationsManagerDep,
    payload: AccessGrantRequestCreate = Body(...),
):
    """Create a new access grant request."""
    success = False
    details = {
        "entity_type": payload.entity_type,
        "entity_id": payload.entity_id,
        "requested_duration_days": payload.requested_duration_days,
        "permission_level": payload.permission_level.value
    }
    
    try:
        if not current_user or not current_user.email:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        manager = get_manager(request, notifications)
        
        result = manager.create_request(
            db=db,
            requester_email=current_user.email,
            data=payload
        )
        
        success = True
        return result
        
    except ValueError as e:
        logger.warning(f"Invalid access request: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating access request: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create access request"
        )
    finally:
        background_tasks.add_task(
            audit_manager.log_action_background,
            username=audit_user.username if audit_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature=ACCESS_GRANTS_FEATURE_ID,
            action="CREATE_REQUEST",
            success=success,
            details=details
        )


@router.post(
    "/handle",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Handle Access Request",
    description=(
        "Approve or deny an access grant request. As on the workflow path, only an Ontos "
        "admin may decide their own request or grant more than was requested (audited as "
        "an override)."
    ),
)
async def handle_access_request(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: CurrentUserDep,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    notifications: NotificationsManagerDep,
    payload: AccessGrantHandlePayload = Body(...),
    _: bool = Depends(PermissionChecker(ACCESS_GRANTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """Handle (approve/deny) an access grant request."""
    success = False
    details = {
        "request_id": str(payload.request_id),
        "approved": payload.approved,
        "granted_duration_days": payload.granted_duration_days,
        "permission_level": payload.permission_level.value if payload.permission_level else None,
    }
    
    try:
        if not current_user or not current_user.email:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        manager = get_manager(request, notifications)
        
        decision = manager.decide_request(
            db,
            current_user.email,
            payload,
            admin=is_ontos_admin(request, current_user),
            caller_ids=(current_user.username,),
        )
        if decision.overridden:
            details.update({"override": True, "overridden": decision.overridden})
        
        success = True
        
        result = {
            "request": decision.request.model_dump(),
            "message": "Request approved" if payload.approved else "Request denied"
        }
        if decision.grant:
            result["grant"] = decision.grant.model_dump()
        
        return result
        
    except OwnAccessRequestError as e:
        # code: translated by the UI (workflows:approvalResponse.errors.*)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": e.code, "message": str(e)},
        )
    except AccessRequestAlreadyDecidedError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": e.code, "message": str(e), "params": e.params},
        )
    except ValueError as e:
        logger.warning(f"Invalid handle request: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error handling access request: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to handle access request"
        )
    finally:
        background_tasks.add_task(
            audit_manager.log_action_background,
            username=audit_user.username if audit_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature=ACCESS_GRANTS_FEATURE_ID,
            action="HANDLE_REQUEST",
            success=success,
            details=details
        )


@router.get(
    "/requests/pending",
    response_model=AccessGrantRequestList,
    summary="List Pending Requests",
    description="List all pending access requests (admin only)."
)
async def list_pending_requests(
    request: Request,
    db: DBSessionDep,
    notifications: NotificationsManagerDep,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: bool = Depends(PermissionChecker(ACCESS_GRANTS_FEATURE_ID, FeatureAccessLevel.READ_ONLY))
):
    """List all pending access requests for admin review."""
    manager = get_manager(request, notifications)
    return manager.get_all_pending_requests(db, limit, offset)


@router.get(
    "/requests/my",
    response_model=AccessGrantRequestList,
    summary="My Pending Requests",
    description="List the current user's pending access requests."
)
async def list_my_pending_requests(
    request: Request,
    current_user: CurrentUserDep,
    db: DBSessionDep,
    notifications: NotificationsManagerDep,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List the current user's pending access requests."""
    if not current_user or not current_user.email:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    manager = get_manager(request, notifications)
    return manager.get_my_pending_requests(db, current_user.email, limit, offset)


@router.get(
    "/my-requests",
    response_model=AccessGrantRequestList,
    summary="My Requests (all statuses)",
    description=(
        "List the access requests created by the current user (pending, approved, denied, "
        "cancelled), newest first. `status` keeps one status; `total` counts the matching "
        "requests, not only the returned page."
    ),
)
async def list_my_requests(
    request: Request,
    current_user: CurrentUserDep,
    db: DBSessionDep,
    notifications: NotificationsManagerDep,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    request_status: Optional[AccessGrantRequestStatus] = Query(None, alias="status"),
    _: bool = Depends(PermissionChecker(ACCESS_GRANTS_FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """List the access requests created by the current user, optionally of one status."""
    if not current_user or not current_user.email:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    manager = get_manager(request, notifications)
    return manager.get_my_requests(
        db, current_user.email, limit, offset,
        request_status.value if request_status else None,
    )


@router.delete(
    "/requests/{request_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel Request",
    description="Cancel a pending access request (by the requester)."
)
async def cancel_request(
    request_id: UUID,
    request: Request,
    current_user: CurrentUserDep,
    db: DBSessionDep,
    notifications: NotificationsManagerDep,
):
    """Cancel a pending access request."""
    if not current_user or not current_user.email:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    manager = get_manager(request, notifications)
    
    try:
        success = manager.cancel_request(db, str(request_id), current_user.email)
        if not success:
            raise HTTPException(status_code=404, detail="Request not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================================================
# Access Grant Endpoints
# ============================================================================

@router.get(
    "/entity/{entity_type}/{entity_id}",
    response_model=AccessGrantList,
    summary="Get Entity Grants",
    description="Get access grants for a specific entity."
)
async def get_entity_grants(
    entity_type: str,
    entity_id: str,
    request: Request,
    db: DBSessionDep,
    notifications: NotificationsManagerDep,
    include_inactive: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Get access grants for a specific entity."""
    manager = get_manager(request, notifications)
    return manager.get_grants_for_entity(
        db, entity_type, entity_id, include_inactive, limit, offset
    )


@router.get(
    "/entity/{entity_type}/{entity_id}/requests",
    response_model=AccessGrantRequestList,
    summary="Get Entity Pending Requests",
    description="Get pending access requests for a specific entity."
)
async def get_entity_pending_requests(
    entity_type: str,
    entity_id: str,
    request: Request,
    db: DBSessionDep,
    notifications: NotificationsManagerDep,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Get pending access requests for a specific entity."""
    manager = get_manager(request, notifications)
    return manager.get_pending_requests_for_entity(db, entity_type, entity_id, limit, offset)


@router.get(
    "/entity/{entity_type}/{entity_id}/summary",
    response_model=AccessGrantSummary,
    summary="Get Entity Summary",
    description="Get a summary of grants and requests for an entity."
)
async def get_entity_summary(
    entity_type: str,
    entity_id: str,
    request: Request,
    db: DBSessionDep,
    notifications: NotificationsManagerDep,
):
    """Get grant summary for an entity."""
    manager = get_manager(request, notifications)
    return manager.get_entity_summary(db, entity_type, entity_id)


@router.get(
    "/my",
    response_model=AccessGrantList,
    summary="My Grants",
    description="Get the current user's active access grants."
)
async def get_my_grants(
    request: Request,
    current_user: CurrentUserDep,
    db: DBSessionDep,
    notifications: NotificationsManagerDep,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Get the current user's active access grants."""
    if not current_user or not current_user.email:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    manager = get_manager(request, notifications)
    return manager.get_my_grants(db, current_user.email, limit, offset)


@router.get(
    "/my/summary",
    response_model=UserAccessGrantsSummary,
    summary="My Access Summary",
    description="Get a summary of the current user's grants and requests."
)
async def get_my_summary(
    request: Request,
    current_user: CurrentUserDep,
    db: DBSessionDep,
    notifications: NotificationsManagerDep,
):
    """Get access summary for the current user."""
    if not current_user or not current_user.email:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    manager = get_manager(request, notifications)
    return manager.get_user_summary(db, current_user.email)


@router.post(
    "/{grant_id}/revoke",
    response_model=AccessGrantResponse,
    summary="Revoke Grant",
    description="Revoke an active access grant (admin or owner only)."
)
async def revoke_grant(
    grant_id: UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: CurrentUserDep,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    notifications: NotificationsManagerDep,
    payload: AccessGrantRevokePayload = Body(default=AccessGrantRevokePayload()),
    _: bool = Depends(PermissionChecker(ACCESS_GRANTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """Revoke an active access grant."""
    success = False
    details = {"grant_id": str(grant_id), "reason": payload.reason}
    
    try:
        if not current_user or not current_user.email:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        manager = get_manager(request, notifications)
        result = manager.revoke_grant(
            db=db,
            grant_id=str(grant_id),
            revoked_by=current_user.email,
            reason=payload.reason
        )
        
        success = True
        return result
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error revoking grant: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to revoke grant")
    finally:
        background_tasks.add_task(
            audit_manager.log_action_background,
            username=audit_user.username if audit_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature=ACCESS_GRANTS_FEATURE_ID,
            action="REVOKE_GRANT",
            success=success,
            details=details
        )


# ============================================================================
# Duration Configuration Endpoints
# ============================================================================

@router.get(
    "/config",
    response_model=List[AccessGrantDurationConfigResponse],
    summary="List Duration Configs",
    description="List all duration configurations."
)
async def list_duration_configs(
    request: Request,
    db: DBSessionDep,
    notifications: NotificationsManagerDep,
):
    """List all duration configurations."""
    manager = get_manager(request, notifications)
    return manager.get_all_duration_configs(db)


@router.get(
    "/config/{entity_type}",
    response_model=AccessGrantDurationConfigResponse,
    summary="Get Duration Config",
    description="Get duration configuration for an entity type."
)
async def get_duration_config(
    entity_type: str,
    request: Request,
    db: DBSessionDep,
    notifications: NotificationsManagerDep,
):
    """Get duration configuration for an entity type."""
    manager = get_manager(request, notifications)
    config = manager.get_duration_config(db, entity_type)
    
    if not config:
        # Return default config
        return AccessGrantDurationConfigResponse(
            id=UUID('00000000-0000-0000-0000-000000000000'),
            entity_type=entity_type,
            allowed_durations=[30, 60, 90],
            default_duration=30,
            expiry_warning_days=7,
            allow_renewal=True,
            max_renewals=3,
            created_at=None,
            updated_at=None,
            duration_options=[30, 60, 90]
        )
    
    return config


@router.get(
    "/config/{entity_type}/options",
    response_model=List[int],
    summary="Get Duration Options",
    description="Get available duration options for an entity type."
)
async def get_duration_options(
    entity_type: str,
    request: Request,
    db: DBSessionDep,
    notifications: NotificationsManagerDep,
):
    """Get available duration options for an entity type."""
    manager = get_manager(request, notifications)
    return manager.get_duration_options(db, entity_type)


@router.put(
    "/config/{entity_type}",
    response_model=AccessGrantDurationConfigResponse,
    summary="Update Duration Config",
    description="Create or update duration configuration for an entity type (admin only)."
)
async def upsert_duration_config(
    entity_type: str,
    request: Request,
    current_user: CurrentUserDep,
    db: DBSessionDep,
    notifications: NotificationsManagerDep,
    payload: AccessGrantDurationConfigCreate = Body(...),
    _: bool = Depends(PermissionChecker(ACCESS_GRANTS_FEATURE_ID, FeatureAccessLevel.ADMIN))
):
    """Create or update duration configuration."""
    if not current_user or not current_user.email:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    # Ensure entity_type matches
    if payload.entity_type != entity_type:
        payload.entity_type = entity_type
    
    manager = get_manager(request, notifications)
    return manager.upsert_duration_config(db, payload, current_user.email)

