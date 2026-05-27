from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request

from src.models.business_owners import (
    BusinessOwnerCreate, BusinessOwnerUpdate, BusinessOwnerRead,
    BusinessOwnerRemove, BusinessOwnerHistory,
    ImportFromTeamRequest, ImportFromTeamResponse,
)
from src.controller.business_owners_manager import business_owners_manager
from src.common.authorization import PermissionChecker
from src.common.features import FeatureAccessLevel
from src.common.dependencies import (
    DBSessionDep,
    CurrentUserDep,
    AuditManagerDep,
    AuditCurrentUserDep,
)
from src.common.errors import NotFoundError, ConflictError
from src.common.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/business-owners", tags=["Business Owners"])
user_router = APIRouter(prefix="/api", tags=["Business Owners"])
FEATURE_ID = "business-owners"


def get_business_owners_manager():
    return business_owners_manager


# --- Owner Assignment ---

@router.post(
    "",
    response_model=BusinessOwnerRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def assign_owner(
    request: Request,
    owner_in: BusinessOwnerCreate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager=Depends(get_business_owners_manager),
):
    """Assigns a business owner to an object."""
    success = False
    details = {
        "params": {
            "object": f"{owner_in.object_type}:{owner_in.object_id}",
            "user": owner_in.user_email,
            "role_id": str(owner_in.role_id),
        }
    }
    created_id = None
    try:
        result = manager.assign_owner(db=db, owner_in=owner_in, current_user_id=current_user.email)
        success = True
        created_id = str(result.id)
        return result
    except NotFoundError as e:
        details["exception"] = {"type": "NotFoundError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ConflictError as e:
        details["exception"] = {"type": "ConflictError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        logger.exception("Failed to assign owner")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to assign owner")
    finally:
        if created_id:
            details["created_resource_id"] = created_id
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="ASSIGN_OWNER", success=success, details=details,
        )


@router.get(
    "",
    response_model=List[BusinessOwnerRead],
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
def get_all_owners(
    db: DBSessionDep,
    manager=Depends(get_business_owners_manager),
    skip: int = 0,
    limit: int = 100,
    object_type: Optional[str] = Query(None),
    role_id: Optional[UUID] = Query(None),
    active_only: bool = Query(True),
):
    """Lists all owner assignments with optional filters."""
    return manager.get_all_owners(
        db=db, skip=skip, limit=limit,
        object_type=object_type, role_id=role_id, active_only=active_only,
    )


@router.get(
    "/by-object/{object_type}/{object_id}",
    response_model=List[BusinessOwnerRead],
)
def get_owners_for_object(
    object_type: str,
    object_id: str,
    db: DBSessionDep,
    manager=Depends(get_business_owners_manager),
    active_only: bool = Query(True),
):
    """Gets all owners for a specific object.

    Authenticated-only (no feature-permission gate). Rationale: a user who
    can already view an entity (e.g. a data product in the marketplace)
    needs to see who owns it for the access-request flow — the Data
    Consumer role hits this endpoint as a side-effect of opening the data
    product detail page, and gating it as ``business-owners:READ_ONLY``
    silently 403s the entire owners panel on a page they otherwise have
    legitimate access to.

    Write operations on this router (POST/PATCH/DELETE) remain gated
    behind ``business-owners:READ_WRITE`` so only roles with explicit
    permission can change ownership assignments.
    """
    return manager.get_owners_for_object(
        db=db, object_type=object_type, object_id=object_id, active_only=active_only
    )


@router.get(
    "/history/{object_type}/{object_id}",
    response_model=BusinessOwnerHistory,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
def get_owner_history(
    object_type: str,
    object_id: str,
    db: DBSessionDep,
    manager=Depends(get_business_owners_manager),
):
    """Gets the full ownership history (current + previous) for an object."""
    return manager.get_owner_history(db=db, object_type=object_type, object_id=object_id)


@router.get(
    "/by-user/{user_email}",
    response_model=List[BusinessOwnerRead],
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
def get_ownerships_for_user(
    user_email: str,
    db: DBSessionDep,
    manager=Depends(get_business_owners_manager),
    active_only: bool = Query(True),
):
    """Gets all ownership assignments for a specific user."""
    return manager.get_ownerships_for_user(db=db, user_email=user_email, active_only=active_only)


@router.get(
    "/{owner_id}",
    response_model=BusinessOwnerRead,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
def get_owner(
    owner_id: UUID,
    db: DBSessionDep,
    manager=Depends(get_business_owners_manager),
):
    """Gets a specific owner assignment by ID."""
    result = manager.get_owner(db=db, owner_id=owner_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Owner assignment '{owner_id}' not found")
    return result


@router.put(
    "/{owner_id}",
    response_model=BusinessOwnerRead,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def update_owner(
    owner_id: UUID,
    request: Request,
    owner_in: BusinessOwnerUpdate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager=Depends(get_business_owners_manager),
):
    """Updates an existing owner assignment."""
    success = False
    details = {"params": {"owner_id": str(owner_id)}}
    try:
        result = manager.update_owner(db=db, owner_id=owner_id, owner_in=owner_in, current_user_id=current_user.email)
        success = True
        return result
    except NotFoundError as e:
        details["exception"] = {"type": "NotFoundError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ConflictError as e:
        details["exception"] = {"type": "ConflictError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update owner assignment %s", owner_id)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update owner assignment")
    finally:
        if success:
            details["updated_resource_id"] = str(owner_id)
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="UPDATE_OWNER", success=success, details=details,
        )


@router.post(
    "/{owner_id}/remove",
    response_model=BusinessOwnerRead,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def remove_owner(
    owner_id: UUID,
    request: Request,
    removal: BusinessOwnerRemove,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager=Depends(get_business_owners_manager),
):
    """Deactivates an owner assignment (soft delete with reason tracking)."""
    success = False
    details = {"params": {"owner_id": str(owner_id), "reason": removal.removal_reason}}
    try:
        result = manager.remove_owner(db=db, owner_id=owner_id, removal=removal, current_user_id=current_user.email)
        success = True
        return result
    except NotFoundError as e:
        details["exception"] = {"type": "NotFoundError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ConflictError as e:
        details["exception"] = {"type": "ConflictError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        logger.exception("Failed to remove owner %s", owner_id)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to remove owner")
    finally:
        if success:
            details["removed_resource_id"] = str(owner_id)
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="REMOVE_OWNER", success=success, details=details,
        )


# --- Bulk Import from Team ---

@router.post(
    "/import-from-team",
    response_model=ImportFromTeamResponse,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def import_from_team(
    request: Request,
    body: ImportFromTeamRequest,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager=Depends(get_business_owners_manager),
):
    """Bulk-import team members as business owners.

    Accepts a list of username/role mappings and creates Business Owner records.
    Skips members who are already active owners on the target object.
    Works for both ODCS/ODPS imported team members and Ontos Team members.
    """
    created = 0
    skipped = 0
    errors: List[str] = []

    for member in body.members:
        try:
            owner_in = BusinessOwnerCreate(
                object_type=body.object_type,
                object_id=body.object_id,
                user_email=member.username,
                user_name=member.name,
                role_id=member.role_id,
            )
            manager.assign_owner(db=db, owner_in=owner_in, current_user_id=current_user.email)
            created += 1
        except ConflictError:
            skipped += 1
        except NotFoundError as e:
            errors.append(f"{member.username}: {str(e)}")
        except Exception as e:
            logger.warning("Failed to import team member %s: %s", member.username, str(e))
            errors.append(f"{member.username}: {str(e)}")

    audit_manager.log_action(
        db=db, username=current_user.username,
        ip_address=request.client.host if request.client else None,
        feature=FEATURE_ID, action="IMPORT_FROM_TEAM", success=True,
        details={
            "object": f"{body.object_type}:{body.object_id}",
            "created": created,
            "skipped": skipped,
            "errors": errors,
        },
    )

    return ImportFromTeamResponse(created=created, skipped=skipped, errors=errors)


# --- Current user's ownerships (on separate prefix) ---

@user_router.get(
    "/user/ownerships",
    response_model=List[BusinessOwnerRead],
)
def get_my_ownerships(
    db: DBSessionDep,
    current_user: CurrentUserDep,
    manager=Depends(get_business_owners_manager),
):
    """Gets all ownership assignments for the current user."""
    return manager.get_ownerships_for_user(db=db, user_email=current_user.email, active_only=True)


def register_routes(app):
    app.include_router(router)
    app.include_router(user_router)
    logger.info("Business owners routes registered with prefix /api/business-owners")
