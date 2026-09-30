"""
Routes for the Schema Importer feature.

Provides endpoints to browse a remote system via an existing connection
and import selected resources as persisted Ontos assets.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.common.database import get_db
from src.common.dependencies import (
    AuditCurrentUserDep,
    AuditManagerDep,
    DBSessionDep,
)
from src.common.config import get_settings
from src.common.workspace_client import get_obo_workspace_client
from src.common.logging import get_logger
from src.common.authorization import PermissionChecker
from src.common.features import FeatureAccessLevel
from src.controller.connections_manager import ConnectionsManager
from src.controller.schema_import_manager import SchemaImportManager
from src.models.schema_import import (
    BrowseResponse,
    ImportPreviewItem,
    ImportRequest,
    ImportResult,
    SchemaImportRunDetail,
    SchemaImportRunSummary,
    StartImportRunResponse,
)
from src.models.assets import AssetMetadata

logger = get_logger(__name__)

router = APIRouter(prefix="/api/schema-import", tags=["Schema Import"])

FEATURE_ID = "schema-importer"


# ------------------------------------------------------------------
# Dependency: build SchemaImportManager per request
# ------------------------------------------------------------------

def _get_manager(request: Request, db: Session = Depends(get_db)) -> SchemaImportManager:
    settings = get_settings()
    ws = None
    try:
        ws = get_obo_workspace_client(request, settings)
    except Exception:
        pass
    connections_mgr = ConnectionsManager(db=db, workspace_client=ws)

    from src.common.manager_dependencies import get_assets_manager
    assets_mgr = get_assets_manager(request)

    return SchemaImportManager(
        connections_manager=connections_mgr,
        assets_manager=assets_mgr,
    )


# ------------------------------------------------------------------
# Browse
# ------------------------------------------------------------------

@router.get(
    "/browse/{connection_id}",
    response_model=BrowseResponse,
    summary="Browse remote system hierarchy",
)
async def browse(
    connection_id: UUID,
    path: Optional[str] = None,
    db: DBSessionDep = None,
    manager: SchemaImportManager = Depends(_get_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Browse the remote system for a given connection, optionally drilling into a path."""
    try:
        return manager.browse(db=db, connection_id=connection_id, path=path)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error(f"Browse failed for connection {connection_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ------------------------------------------------------------------
# Metadata (get asset metadata via connector for schema inference)
# ------------------------------------------------------------------

@router.get(
    "/metadata/{connection_id}",
    response_model=AssetMetadata,
    summary="Get asset metadata via connector",
)
async def get_asset_metadata(
    connection_id: UUID,
    path: str,
    db: DBSessionDep = None,
    manager: SchemaImportManager = Depends(_get_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Fetch detailed metadata (including schema/columns) for an asset via its connector."""
    try:
        connector = manager._connections.get_connector_for_connection(connection_id)
        if connector is None:
            raise HTTPException(status_code=404, detail=f"Connection '{connection_id}' not found")
        metadata = connector.get_asset_metadata(path)
        if metadata is None:
            raise HTTPException(status_code=404, detail=f"No metadata found for path '{path}'")
        return metadata
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Metadata fetch failed for {connection_id}/{path}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ------------------------------------------------------------------
# Preview (dry-run import)
# ------------------------------------------------------------------

@router.post(
    "/preview",
    response_model=list[ImportPreviewItem],
    summary="Preview what an import would create or skip",
)
async def preview_import(
    payload: ImportRequest,
    db: DBSessionDep = None,
    manager: SchemaImportManager = Depends(_get_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Return a list of items that would be created or skipped without persisting anything."""
    try:
        return manager.preview_import(db=db, request=payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error(f"Preview failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ------------------------------------------------------------------
# Execute import
# ------------------------------------------------------------------

@router.post(
    "/import",
    response_model=ImportResult,
    summary="Import selected resources as Ontos assets",
)
async def execute_import(
    payload: ImportRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: DBSessionDep = None,
    manager: SchemaImportManager = Depends(_get_manager),
    audit_manager: AuditManagerDep = None,
    current_user: AuditCurrentUserDep = None,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Import selected remote resources (and nested children) as persisted Ontos assets."""
    try:
        user_id = current_user.username if current_user else "system"
        result = manager.execute_import(db=db, request=payload, current_user_id=user_id)

        if audit_manager and current_user:
            background_tasks.add_task(
                audit_manager.log_action_background,
                username=current_user.username,
                ip_address=request.client.host if request.client else None,
                feature=FEATURE_ID,
                action="SCHEMA_IMPORT",
                success=True,
                details={
                    "connection_id": str(payload.connection_id),
                    "created": result.created,
                    "skipped": result.skipped,
                    "errors": result.errors,
                },
            )

        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error(f"Import failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ------------------------------------------------------------------
# Async import (background execution)
# ------------------------------------------------------------------

def _get_runs_manager(request: Request):
    """Fetch the singleton SchemaImportRunsManager from app state."""
    manager = getattr(request.app.state, "schema_import_runs_manager", None)
    if not manager:
        raise HTTPException(status_code=503, detail="Async schema import service not configured.")
    return manager


def _user_token(request: Request) -> Optional[str]:
    """OBO token forwarded by the Databricks app proxy (None in local dev)."""
    return request.headers.get("x-forwarded-access-token")


@router.post(
    "/import-async",
    response_model=StartImportRunResponse,
    status_code=202,
    summary="Start a background import; returns a run id to poll",
)
async def start_import_async(
    payload: ImportRequest,
    request: Request,
    db: DBSessionDep = None,
    current_user: AuditCurrentUserDep = None,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Kick off the import on a background thread. The response returns
    immediately with a run id; poll GET /runs/{run_id} (or watch the
    notification bell) for progress and completion."""
    runs_manager = _get_runs_manager(request)
    user_id = current_user.username if current_user else "system"
    try:
        run_id = runs_manager.start_run(
            db=db, request=payload, user_id=user_id, user_token=_user_token(request),
        )
        return StartImportRunResponse(run_id=run_id)
    except ValueError as exc:
        # Concurrency cap or connection resolution error
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        logger.error(f"Failed to start async import: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get(
    "/runs",
    response_model=list[SchemaImportRunSummary],
    summary="List the current user's recent import runs",
)
async def list_import_runs(
    request: Request,
    db: DBSessionDep = None,
    current_user: AuditCurrentUserDep = None,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    runs_manager = _get_runs_manager(request)
    user_id = current_user.username if current_user else "system"
    return runs_manager.list_runs_for_user(db, user_id)


@router.get(
    "/runs/{run_id}",
    response_model=SchemaImportRunDetail,
    summary="Get the status/progress of a background import run",
)
async def get_import_run(
    run_id: str,
    request: Request,
    db: DBSessionDep = None,
    current_user: AuditCurrentUserDep = None,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    runs_manager = _get_runs_manager(request)
    user_id = current_user.username if current_user else "system"
    run = runs_manager.get_run_for_user(db, run_id, user_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Import run '{run_id}' not found")
    # Pick up the latest values written by the background thread.
    db.refresh(run)
    return run


@router.post(
    "/runs/{run_id}/cancel",
    response_model=SchemaImportRunDetail,
    summary="Request cancellation of a running import",
)
async def cancel_import_run(
    run_id: str,
    request: Request,
    db: DBSessionDep = None,
    current_user: AuditCurrentUserDep = None,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    runs_manager = _get_runs_manager(request)
    user_id = current_user.username if current_user else "system"
    run = runs_manager.get_run_for_user(db, run_id, user_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Import run '{run_id}' not found")
    runs_manager.cancel_run(run_id)
    db.refresh(run)
    return run


# ------------------------------------------------------------------
# Registration
# ------------------------------------------------------------------

def register_routes(app):
    """Register schema import routes with the app."""
    app.include_router(router)
    logger.info("Schema import routes registered")
