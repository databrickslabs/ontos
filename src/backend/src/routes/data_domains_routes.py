from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Request, BackgroundTasks

from src.models.data_domains import DataDomainCreate, DataDomainUpdate, DataDomainRead
from src.controller.data_domains_manager import DataDomainManager
from src.common.database import get_db
from sqlalchemy.orm import Session
from src.common.authorization import PermissionChecker # Import PermissionChecker
from src.common.features import FeatureAccessLevel
from src.common.dependencies import (
    DBSessionDep,
    CurrentUserDep,
    AuditManagerDep,
    AuditCurrentUserDep,
    get_data_domain_manager
) 
from src.models.users import UserInfo # To type hint current_user
from src.common.errors import NotFoundError, ConflictError
from src.common.workflow_triggers import get_trigger_registry, fire_trigger_safe
from src.models.process_workflows import EntityType

from src.common.logging import get_logger
logger = get_logger(__name__)

# Define router
# Using kebab-case for endpoint path as per convention
router = APIRouter(prefix="/api", tags=["Data Domains"])

# --- Feature ID Constant --- #
DATA_DOMAINS_FEATURE_ID = "data-domains" # Use a consistent ID

# --- Route Definitions --- #

@router.post(
    "/data-domains",
    response_model=DataDomainRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(PermissionChecker(DATA_DOMAINS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))]
)
async def create_data_domain(
    request: Request,
    domain_in: DataDomainCreate,
    db: DBSessionDep,
    background_tasks: BackgroundTasks,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: DataDomainManager = Depends(get_data_domain_manager)
):
    """Creates a new data domain."""
    success = False
    details_for_audit = {
        "params": {"domain_name": domain_in.name},
    }
    created_domain_id = None

    logger.info(f"User '{current_user.email}' attempting to create data domain: {domain_in.name}")
    try:
        # Delivery handled via DeliveryMixin in manager
        created_domain = manager.create_domain(
            db=db,
            domain_in=domain_in,
            current_user_id=current_user.email,
            background_tasks=background_tasks,
        )
        db.commit()
        success = True
        created_domain_id = str(created_domain.id)

        # Fire on_create workflow trigger
        fire_trigger_safe(
            db, "on_create",
            entity_type=EntityType.DOMAIN,
            entity_id=str(created_domain.id),
            entity_name=created_domain.name,
            entity_data={"domain_id": str(created_domain.id), "name": created_domain.name},
            user_email=current_user.email if current_user else None,
            blocking=False,
        )

        return created_domain
    except ConflictError as e:
        db.rollback()
        logger.error("Data domain creation conflict for '%s': %s", domain_in.name, e)
        details_for_audit["exception"] = {"type": "ConflictError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Data domain already exists")
    except Exception as e:
        db.rollback()
        logger.exception("Failed to create data domain '%s'", domain_in.name)
        details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create data domain")
    finally:
        if created_domain_id:
            details_for_audit["created_resource_id"] = created_domain_id
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_DOMAINS_FEATURE_ID,
            action="CREATE",
            success=success,
            details=details_for_audit
        )

@router.get(
    "/data-domains", 
    response_model=List[DataDomainRead],
    dependencies=[Depends(PermissionChecker(DATA_DOMAINS_FEATURE_ID, FeatureAccessLevel.READ_ONLY))]
)
def get_all_data_domains(
    # Dependencies first
    db: DBSessionDep,
    manager: DataDomainManager = Depends(get_data_domain_manager),
    # Then query parameters
    skip: int = 0,
    limit: int = 100,
):
    """Lists all data domains."""
    logger.debug(f"Fetching all data domains (skip={skip}, limit={limit})")
    try:
        return manager.get_all_domains(db=db, skip=skip, limit=limit)
    except Exception as e:
        logger.exception(f"Failed to fetch data domains: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch data domains")

@router.get(
    "/data-domains/{domain_id}", 
    response_model=DataDomainRead,
    dependencies=[Depends(PermissionChecker(DATA_DOMAINS_FEATURE_ID, FeatureAccessLevel.READ_ONLY))]
)
def get_data_domain(
    domain_id: UUID,
    db: DBSessionDep,
    manager: DataDomainManager = Depends(get_data_domain_manager)
):
    """Gets a specific data domain by its ID."""
    logger.debug(f"Fetching data domain with id: {domain_id}")
    domain = manager.get_domain_by_id(db=db, domain_id=domain_id)
    if not domain:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Data domain with id '{domain_id}' not found")
    return domain

@router.put(
    "/data-domains/{domain_id}",
    response_model=DataDomainRead,
    dependencies=[Depends(PermissionChecker(DATA_DOMAINS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))]
)
async def update_data_domain(
    domain_id: UUID,
    request: Request,
    domain_in: DataDomainUpdate,
    db: DBSessionDep,
    background_tasks: BackgroundTasks,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: DataDomainManager = Depends(get_data_domain_manager)
):
    """Updates an existing data domain."""
    success = False
    details_for_audit = {
        "params": {"domain_id": str(domain_id)},
    }

    logger.info(f"User '{current_user.email}' attempting to update data domain: {domain_id}")
    try:
        # Delivery handled via DeliveryMixin in manager
        updated_domain = manager.update_domain(
            db=db,
            domain_id=domain_id,
            domain_in=domain_in,
            current_user_id=current_user.email,
            background_tasks=background_tasks,
        )
        db.commit()
        success = True

        # Fire on_update workflow trigger
        fire_trigger_safe(
            db, "on_update",
            entity_type=EntityType.DOMAIN,
            entity_id=str(domain_id),
            entity_name=getattr(updated_domain, 'name', None),
            entity_data=domain_in.model_dump(exclude_unset=True),
            user_email=current_user.email if current_user else None,
            blocking=False,
        )

        return updated_domain
    except NotFoundError as e:
        db.rollback()
        logger.error("Data domain not found for update %s: %s", domain_id, e)
        details_for_audit["exception"] = {"type": "NotFoundError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data domain not found")
    except ConflictError as e:
        db.rollback()
        logger.error("Data domain update conflict %s: %s", domain_id, e)
        details_for_audit["exception"] = {"type": "ConflictError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Data domain conflict")
    except Exception as e:
        db.rollback()
        logger.exception("Failed to update data domain %s", domain_id)
        details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update data domain")
    finally:
        if success:
            details_for_audit["updated_resource_id"] = str(domain_id)
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_DOMAINS_FEATURE_ID,
            action="UPDATE",
            success=success,
            details=details_for_audit
        )

@router.delete(
    "/data-domains/{domain_id}",
    response_model=DataDomainRead,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(PermissionChecker(DATA_DOMAINS_FEATURE_ID, FeatureAccessLevel.ADMIN))]
)
def delete_data_domain(
    domain_id: UUID,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: DataDomainManager = Depends(get_data_domain_manager)
):
    """Deletes a data domain. Requires Admin privileges."""
    success = False
    details_for_audit = {
        "params": {"domain_id": str(domain_id)},
    }

    logger.info(f"User '{current_user.email}' attempting to delete data domain: {domain_id}")
    try:
        deleted_domain = manager.delete_domain(db=db, domain_id=domain_id, current_user_id=current_user.email)
        db.commit()
        success = True

        # Fire on_delete workflow trigger
        fire_trigger_safe(
            db, "on_delete",
            entity_type=EntityType.DOMAIN,
            entity_id=str(domain_id),
            entity_name=getattr(deleted_domain, 'name', None),
            entity_data={"domain_id": str(domain_id)},
            user_email=current_user.email if current_user else None,
            blocking=False,
        )

        return deleted_domain
    except NotFoundError as e:
        db.rollback()
        logger.error("Data domain not found for deletion %s: %s", domain_id, e)
        details_for_audit["exception"] = {"type": "NotFoundError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data domain not found")
    except Exception as e:
        db.rollback()
        logger.exception("Failed to delete data domain %s", domain_id)
        details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete data domain")
    finally:
        if success:
            details_for_audit["deleted_resource_id"] = str(domain_id)
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_DOMAINS_FEATURE_ID,
            action="DELETE",
            success=success,
            details=details_for_audit
        )

def register_routes(app):
    app.include_router(router)
    logger.info("Data Domain routes registered with prefix /api/data-domains") 