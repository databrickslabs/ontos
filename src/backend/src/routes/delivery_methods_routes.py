from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request

from src.models.delivery_methods import DeliveryMethodCreate, DeliveryMethodUpdate, DeliveryMethodRead
from src.controller.delivery_methods_manager import delivery_methods_manager
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

router = APIRouter(prefix="/api/delivery-methods", tags=["Delivery Methods"])
FEATURE_ID = "delivery-methods"
# Reads of the delivery-method catalog are a prerequisite for authoring a
# deliverable on a data product, so they are gated by the data-products
# feature (any product author can list/get) rather than the admin-managed
# delivery-methods feature. Writes stay gated by delivery-methods:READ_WRITE.
READ_FEATURE_ID = "data-products"


def get_delivery_methods_manager():
    return delivery_methods_manager


@router.post(
    "",
    response_model=DeliveryMethodRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def create_delivery_method(
    request: Request,
    obj_in: DeliveryMethodCreate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager=Depends(get_delivery_methods_manager),
):
    """Creates a new delivery method."""
    success = False
    details = {"params": {"name": obj_in.name}}
    created_id = None
    try:
        result = manager.create(db=db, obj_in=obj_in, current_user_id=current_user.email)
        success = True
        created_id = str(result.id)
        return result
    except ConflictError as e:
        details["exception"] = {"type": "ConflictError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create delivery method '%s'", obj_in.name)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create delivery method")
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
    response_model=List[DeliveryMethodRead],
    dependencies=[Depends(PermissionChecker(READ_FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
def get_all_delivery_methods(
    db: DBSessionDep,
    manager=Depends(get_delivery_methods_manager),
    skip: int = 0,
    limit: int = 100,
    category: Optional[str] = Query(None),
    method_status: Optional[str] = Query(None, alias="status"),
):
    """Lists all delivery methods."""
    return manager.get_all(db=db, skip=skip, limit=limit, category=category, status=method_status)


@router.get(
    "/{method_id}",
    response_model=DeliveryMethodRead,
    dependencies=[Depends(PermissionChecker(READ_FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
def get_delivery_method(
    method_id: UUID,
    db: DBSessionDep,
    manager=Depends(get_delivery_methods_manager),
):
    """Gets a specific delivery method by ID."""
    result = manager.get(db=db, obj_id=method_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Delivery method '{method_id}' not found")
    return result


@router.put(
    "/{method_id}",
    response_model=DeliveryMethodRead,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def update_delivery_method(
    method_id: UUID,
    request: Request,
    obj_in: DeliveryMethodUpdate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager=Depends(get_delivery_methods_manager),
):
    """Updates an existing delivery method."""
    success = False
    details = {"params": {"method_id": str(method_id)}}
    try:
        result = manager.update(db=db, obj_id=method_id, obj_in=obj_in, current_user_id=current_user.email)
        success = True
        return result
    except NotFoundError as e:
        details["exception"] = {"type": "NotFoundError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ConflictError as e:
        details["exception"] = {"type": "ConflictError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update delivery method %s", method_id)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update delivery method")
    finally:
        if success:
            details["updated_resource_id"] = str(method_id)
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="UPDATE", success=success, details=details,
        )


@router.delete(
    "/{method_id}",
    response_model=DeliveryMethodRead,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.ADMIN))],
)
def delete_delivery_method(
    method_id: UUID,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager=Depends(get_delivery_methods_manager),
):
    """Deletes a delivery method. Requires Admin."""
    success = False
    details = {"params": {"method_id": str(method_id)}}
    try:
        result = manager.delete(db=db, obj_id=method_id)
        success = True
        return result
    except NotFoundError as e:
        details["exception"] = {"type": "NotFoundError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.exception("Failed to delete delivery method %s", method_id)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete delivery method")
    finally:
        if success:
            details["deleted_resource_id"] = str(method_id)
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="DELETE", success=success, details=details,
        )


def register_routes(app):
    app.include_router(router)
    logger.info("Delivery methods routes registered with prefix /api/delivery-methods")
