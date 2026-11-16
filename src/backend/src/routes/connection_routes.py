"""
CRUD routes for external data platform connections.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request, Body
from sqlalchemy.orm import Session

from ..common.database import get_db
from ..common.dependencies import (
    DBSessionDep,
    AuditManagerDep,
    AuditCurrentUserDep,
)
from ..common.config import get_settings
from ..common.workspace_client import get_workspace_client
from ..common.logging import get_logger
from ..common.authorization import PermissionChecker, get_user_details_from_sdk, user_has_feature_level
from ..common.features import FeatureAccessLevel
from ..common.manager_dependencies import get_auth_manager
from ..controller.connections_manager import ConnectionsManager
from ..db_models.connections import ConnectionDb
from ..models.connections import ConnectionCreate, ConnectionUpdate, ConnectionResponse
from ..models.users import UserInfo

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["Connections"])

FEATURE_ID = "settings-connectors"

# Connector types whose config names a Unity Catalog secret that the scheduled sync job
# reads as the app's service principal. Setting server_url/secret_name would let a
# settings writer send that secret to any host, so only administrators may set them.
SECRET_SOURCE_CONNECTOR_TYPES = frozenset({"tableau"})


def _require_admin_for_secret_sources(auth_manager, user: UserInfo, *connector_types: Optional[str]) -> None:
    if not any(t in SECRET_SOURCE_CONNECTOR_TYPES for t in connector_types if t):
        return
    if user_has_feature_level(auth_manager, user, FEATURE_ID, FeatureAccessLevel.ADMIN):
        return
    raise HTTPException(status_code=403, detail="Only administrators can create or change this connection type")


def _get_manager(db: Session = Depends(get_db)) -> ConnectionsManager:
    settings = get_settings()
    ws = None
    try:
        ws = get_workspace_client(settings=settings)
    except Exception:
        pass
    return ConnectionsManager(db=db, workspace_client=ws)


# ------------------------------------------------------------------
# CRUD
# ------------------------------------------------------------------

@router.get("/connections")
async def list_connections(
    connector_type: Optional[str] = None,
    manager: ConnectionsManager = Depends(_get_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """List all connections, optionally filtered by connector type."""
    return manager.list_connections(connector_type=connector_type)


@router.get("/connections/types")
async def list_connector_types(
    manager: ConnectionsManager = Depends(_get_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """List available connector types with metadata and config field hints."""
    return manager.list_connector_types()


@router.get("/connections/{connection_id}")
async def get_connection(
    connection_id: UUID,
    manager: ConnectionsManager = Depends(_get_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Get a single connection by ID."""
    conn = manager.get_connection(connection_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    return conn


@router.post("/connections", status_code=201)
async def create_connection(
    payload: ConnectionCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    manager: ConnectionsManager = Depends(_get_manager),
    audit_manager: AuditManagerDep = None,
    current_user: AuditCurrentUserDep = None,
    user_details: UserInfo = Depends(get_user_details_from_sdk),
    auth_manager=Depends(get_auth_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Create a new connection."""
    _require_admin_for_secret_sources(auth_manager, user_details, payload.connector_type)
    try:
        result = manager.create_connection(
            payload,
            created_by=current_user.username if current_user else "",
        )
        if audit_manager and current_user:
            background_tasks.add_task(
                audit_manager.log_action_background,
                username=current_user.username,
                ip_address=request.client.host if request.client else None,
                feature=FEATURE_ID,
                action="CONNECTION_CREATE",
                success=True,
                details={"connection_id": str(result.id), "name": result.name},
            )
        return result
    except Exception as e:
        logger.error(f"Error creating connection: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/connections/{connection_id}")
async def update_connection(
    connection_id: UUID,
    payload: ConnectionUpdate,
    background_tasks: BackgroundTasks,
    request: Request,
    manager: ConnectionsManager = Depends(_get_manager),
    audit_manager: AuditManagerDep = None,
    current_user: AuditCurrentUserDep = None,
    db: DBSessionDep = None,
    user_details: UserInfo = Depends(get_user_details_from_sdk),
    auth_manager=Depends(get_auth_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Update an existing connection."""
    existing = db.get(ConnectionDb, connection_id) if db is not None else None
    _require_admin_for_secret_sources(auth_manager, user_details, existing.connector_type if existing else None)
    result = manager.update_connection(connection_id, payload)
    if result is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    if audit_manager and current_user:
        background_tasks.add_task(
            audit_manager.log_action_background,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID,
            action="CONNECTION_UPDATE",
            success=True,
            details={"connection_id": str(connection_id), "name": result.name},
        )
    return result


@router.delete("/connections/{connection_id}")
async def delete_connection(
    connection_id: UUID,
    background_tasks: BackgroundTasks,
    request: Request,
    manager: ConnectionsManager = Depends(_get_manager),
    audit_manager: AuditManagerDep = None,
    current_user: AuditCurrentUserDep = None,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.ADMIN)),
):
    """Delete a connection (system connections cannot be deleted)."""
    try:
        deleted = manager.delete_connection(connection_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Connection not found")
        if audit_manager and current_user:
            background_tasks.add_task(
                audit_manager.log_action_background,
                username=current_user.username,
                ip_address=request.client.host if request.client else None,
                feature=FEATURE_ID,
                action="CONNECTION_DELETE",
                success=True,
                details={"connection_id": str(connection_id)},
            )
        return {"status": "deleted"}
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


# ------------------------------------------------------------------
# Test connection
# ------------------------------------------------------------------

@router.post("/connections/{connection_id}/test")
async def test_connection(
    connection_id: UUID,
    manager: ConnectionsManager = Depends(_get_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Test connectivity for a specific connection."""
    result = manager.test_connection(connection_id)
    return result


# ------------------------------------------------------------------
# Registration
# ------------------------------------------------------------------

def register_routes(app):
    """Register connection routes with the app."""
    app.include_router(router)
    logger.info("Connection routes registered")
