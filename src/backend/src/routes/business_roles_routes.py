from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request

from src.models.business_roles import BusinessRoleCreate, BusinessRoleUpdate, BusinessRoleRead
from src.controller.business_roles_manager import business_roles_manager
from src.common.authorization import PermissionChecker
from src.common.features import FeatureAccessLevel
from src.common.dependencies import (
    DBSessionDep,
    AuditManagerDep,
    AuditCurrentUserDep,
)
from src.common.errors import NotFoundError, ConflictError
from src.common.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/business-roles", tags=["Business Roles"])
FEATURE_ID = "business-roles"


def get_business_roles_manager():
    return business_roles_manager


@router.post(
    "",
    response_model=BusinessRoleRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def create_role(
    request: Request,
    role_in: BusinessRoleCreate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager=Depends(get_business_roles_manager),
):
    """Creates a new business role."""
    success = False
    details = {"params": {"name": role_in.name}}
    created_id = None
    try:
        result = manager.create_role(db=db, role_in=role_in, current_user_id=current_user.email)
        success = True
        created_id = str(result.id)
        return result
    except ConflictError as e:
        details["exception"] = {"type": "ConflictError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create business role '%s'", role_in.name)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create business role")
    finally:
        if created_id:
            details["created_resource_id"] = created_id
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="CREATE", success=success, details=details,
        )


@router.get(
    "",
    response_model=List[BusinessRoleRead],
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
def get_all_roles(
    db: DBSessionDep,
    manager=Depends(get_business_roles_manager),
    skip: int = 0,
    limit: int = 100,
    category: Optional[str] = Query(None),
    role_status: Optional[str] = Query(None, alias="status"),
):
    """Lists all business roles."""
    return manager.get_all_roles(db=db, skip=skip, limit=limit, category=category, status=role_status)


@router.get(
    "/{role_id}",
    response_model=BusinessRoleRead,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
def get_role(
    role_id: UUID,
    db: DBSessionDep,
    manager=Depends(get_business_roles_manager),
):
    """Gets a specific business role by ID."""
    result = manager.get_role(db=db, role_id=role_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Business role '{role_id}' not found")
    return result


@router.put(
    "/{role_id}",
    response_model=BusinessRoleRead,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def update_role(
    role_id: UUID,
    request: Request,
    role_in: BusinessRoleUpdate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager=Depends(get_business_roles_manager),
):
    """Updates an existing business role."""
    success = False
    details = {"params": {"role_id": str(role_id)}}
    try:
        result = manager.update_role(db=db, role_id=role_id, role_in=role_in, current_user_id=current_user.email)
        success = True
        return result
    except NotFoundError as e:
        details["exception"] = {"type": "NotFoundError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ConflictError as e:
        details["exception"] = {"type": "ConflictError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update business role %s", role_id)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update business role")
    finally:
        if success:
            details["updated_resource_id"] = str(role_id)
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="UPDATE", success=success, details=details,
        )


@router.delete(
    "/{role_id}",
    response_model=BusinessRoleRead,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.ADMIN))],
)
def delete_role(
    role_id: UUID,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager=Depends(get_business_roles_manager),
):
    """Deletes a business role. Requires Admin."""
    success = False
    details = {"params": {"role_id": str(role_id)}}
    try:
        result = manager.delete_role(db=db, role_id=role_id)
        success = True
        return result
    except NotFoundError as e:
        details["exception"] = {"type": "NotFoundError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.exception("Failed to delete business role %s", role_id)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete business role")
    finally:
        if success:
            details["deleted_resource_id"] = str(role_id)
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="DELETE", success=success, details=details,
        )


@router.get(
    "/{role_id}/workflow-usage",
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
def get_role_workflow_usage(
    role_id: UUID,
    db: DBSessionDep,
):
    """Check if a business role is referenced by any workflow steps (approval/notification)."""
    from src.db_models.process_workflows import WorkflowStepDb, ProcessWorkflowDb

    search_token = f"business:{role_id}"
    # Search step configs for this role reference
    steps = (
        db.query(WorkflowStepDb)
        .filter(WorkflowStepDb.config.contains(search_token))
        .all()
    )

    workflows = []
    seen = set()
    for step in steps:
        wf = db.query(ProcessWorkflowDb).filter(ProcessWorkflowDb.id == step.workflow_id).first()
        if wf and str(wf.id) not in seen:
            seen.add(str(wf.id))
            workflows.append({"id": str(wf.id), "name": wf.name})

    return {"role_id": str(role_id), "used_in_workflows": workflows, "count": len(workflows)}


def register_routes(app):
    app.include_router(router)
    logger.info("Business roles routes registered with prefix /api/business-roles")
