from typing import Annotated
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from src.common.authorization import PermissionChecker
from src.common.config import Settings, get_settings
from src.common.features import FeatureAccessLevel
from src.common.workspace_client import get_workspace_client, WorkspaceClient
from src.common.dependencies import DBSessionDep, AuditManagerDep, AuditCurrentUserDep
from src.models.estate import Estate, CloudType, SyncStatus

# Annotated type for flat (non-embedded) Estate body parameter
EstateBody = Annotated[Estate, Body(embed=False)]
from src.controller.estate_manager import EstateManager

# Configure logging
from src.common.logging import get_logger
logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["Estates"])

def get_estate_manager(client: WorkspaceClient = Depends(get_workspace_client), settings: Settings = Depends(get_settings)) -> EstateManager:
    """Dependency provider for EstateManager.
    
    Manager auto-loads estates from YAML if file exists in data/estates.yaml.
    """
    return EstateManager(client, settings)

@router.get("/estates", response_model=list[Estate])
async def list_estates(
    estate_manager: EstateManager = Depends(get_estate_manager),
    _: bool = Depends(PermissionChecker('estate-manager', FeatureAccessLevel.READ_ONLY))
):
    """List all configured estates"""
    logger.info("Listing estates")
    return await estate_manager.list_estates()

@router.get("/estates/{estate_id}", response_model=Estate)
async def get_estate(
    estate_id: str,
    estate_manager: EstateManager = Depends(get_estate_manager),
    _: bool = Depends(PermissionChecker('estate-manager', FeatureAccessLevel.READ_ONLY))
):
    """Get a specific estate by ID"""
    estate = await estate_manager.get_estate(estate_id)
    if not estate:
        raise HTTPException(status_code=404, detail="Estate not found")
    return estate

@router.post("/estates", response_model=Estate)
async def create_estate(
    payload: EstateBody,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    estate_manager: EstateManager = Depends(get_estate_manager),
    _: bool = Depends(PermissionChecker('estate-manager', FeatureAccessLevel.ADMIN))
):
    """Create a new estate"""
    success = False
    details = {
        "params": {
            "estate_id": payload.id,
            "name": payload.name,
            "cloud_type": payload.cloud_type.value if payload.cloud_type else None,
            "enabled": payload.is_enabled
        }
    }

    try:
        result = await estate_manager.create_estate(payload)
        success = True
        return result
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        logger.exception("Failed creating estate %s", payload.id)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail="Failed to create estate")
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="estate-manager",
            action="CREATE",
            success=success,
            details=details
        )

@router.put("/estates/{estate_id}", response_model=Estate)
async def update_estate(
    estate_id: str,
    payload: EstateBody,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    estate_manager: EstateManager = Depends(get_estate_manager),
    _: bool = Depends(PermissionChecker('estate-manager', FeatureAccessLevel.ADMIN))
):
    """Update an existing estate"""
    success = False
    details = {
        "params": {
            "estate_id": estate_id,
            "name": payload.name,
            "enabled": payload.is_enabled
        }
    }

    try:
        updated_estate = await estate_manager.update_estate(estate_id, payload)
        if not updated_estate:
            raise HTTPException(status_code=404, detail="Estate not found")
        success = True
        return updated_estate
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        logger.exception("Failed updating estate %s", estate_id)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail="Failed to update estate")
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="estate-manager",
            action="UPDATE",
            success=success,
            details=details
        )

@router.delete("/estates/{estate_id}")
async def delete_estate(
    estate_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    estate_manager: EstateManager = Depends(get_estate_manager),
    _: bool = Depends(PermissionChecker('estate-manager', FeatureAccessLevel.ADMIN))
):
    """Delete an estate"""
    success = False
    details = {"params": {"estate_id": estate_id}}

    try:
        ok = await estate_manager.delete_estate(estate_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Estate not found")
        success = True
        return {"message": "Estate deleted successfully"}
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        logger.exception("Failed deleting estate %s", estate_id)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail="Failed to delete estate")
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="estate-manager",
            action="DELETE",
            success=success,
            details=details
        )

@router.post("/estates/{estate_id}/sync")
async def sync_estate(
    estate_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    estate_manager: EstateManager = Depends(get_estate_manager),
    _: bool = Depends(PermissionChecker('estate-manager', FeatureAccessLevel.ADMIN))
):
    """Trigger a sync for a specific estate"""
    success = False
    details = {"params": {"estate_id": estate_id}}

    try:
        ok = await estate_manager.sync_estate(estate_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Estate not found or sync disabled")
        success = True
        details["sync_triggered"] = True
        return {"message": "Estate sync triggered successfully"}
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        logger.exception("Failed syncing estate %s", estate_id)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail="Failed to sync estate")
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="estate-manager",
            action="SYNC",
            success=success,
            details=details
        ) 

def register_routes(app):
    """Register routes with the app"""
    app.include_router(router)
    logger.info("Estate manager routes registered")
