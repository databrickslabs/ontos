"""
Asset Bulk Import/Export Routes

Provides endpoints for exporting assets as CSV/XLSX and importing
assets from uploaded files with preview and validation.
"""

from typing import List, Optional, Tuple
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from src.common.authorization import PermissionChecker
from src.common.dependencies import (
    AuditCurrentUserDep,
    AuditManagerDep,
    DBSessionDep,
    SettingsDep,
)
from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger
from src.controller.asset_bulk_manager import (
    AssetBulkManager,
    ImportPreviewResult,
    ImportResult,
)
from src.controller.uc_description_sync_manager import (
    ImportWriteLimitError, UcDescriptionSyncManager, import_writes_failed_warning,
)
from src.db_models.assets import AssetDb

logger = get_logger(__name__)

router = APIRouter(prefix="/api/assets/bulk", tags=["Asset Bulk"])
FEATURE_ID = "assets"

_bulk_manager: Optional[AssetBulkManager] = None


def get_bulk_manager() -> AssetBulkManager:
    global _bulk_manager
    if _bulk_manager is None:
        _bulk_manager = AssetBulkManager()
    return _bulk_manager


# ------------------------------------------------------------------
# Export
# ------------------------------------------------------------------

@router.get(
    "/export",
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
def export_assets(
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    fmt: str = Query("csv", alias="format", description="Export format: csv or xlsx"),
    ids: Optional[str] = Query(None, description="Comma-separated asset IDs to export (overrides other filters)"),
    asset_type_id: Optional[UUID] = Query(None),
    platform: Optional[str] = Query(None),
    domain_id: Optional[str] = Query(None),
    asset_status: Optional[str] = Query(None, alias="status"),
    manager: AssetBulkManager = Depends(get_bulk_manager),
):
    """Export filtered assets as CSV or XLSX file download. When `ids` is provided, only those assets are exported."""
    success = False
    asset_ids = None
    if ids:
        try:
            asset_ids = [UUID(i.strip()) for i in ids.split(",") if i.strip()]
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid asset ID format in 'ids' parameter")
    details = {"params": {"format": fmt, "ids_count": len(asset_ids) if asset_ids else None, "asset_type_id": str(asset_type_id) if asset_type_id else None}}
    try:
        file_bytes, filename, content_type = manager.export_assets(
            db, fmt=fmt,
            asset_ids=asset_ids,
            asset_type_id=asset_type_id, platform=platform,
            domain_id=domain_id, status=asset_status,
        )
        success = True
        return Response(
            content=file_bytes,
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        logger.exception("Failed to export assets")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to export assets")
    finally:
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="EXPORT_ASSETS", success=success, details=details,
        )


@router.get(
    "/export/template",
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
def export_template(
    db: DBSessionDep,
    asset_type: Optional[str] = Query(None, description="Asset type name for the template"),
    fmt: str = Query("csv", alias="format", description="Template format: csv or xlsx"),
    manager: AssetBulkManager = Depends(get_bulk_manager),
):
    """Download an empty import template with correct headers and an example row."""
    try:
        file_bytes, filename, content_type = manager.export_template(
            db, asset_type_name=asset_type, fmt=fmt,
        )
        return Response(
            content=file_bytes,
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        logger.exception("Failed to generate template")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to generate template")


# ------------------------------------------------------------------
# Import
# ------------------------------------------------------------------

@router.post(
    "/import/preview",
    response_model=ImportPreviewResult,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
async def preview_import(
    db: DBSessionDep,
    file: UploadFile = File(..., description="CSV or XLSX file to preview"),
    manager: AssetBulkManager = Depends(get_bulk_manager),
):
    """Upload a file and preview what will be created, updated, or skipped."""
    try:
        contents = await file.read()
        filename = file.filename or "upload.csv"
        result = manager.preview_import(db, file_bytes=contents, filename=filename)
        return result
    except Exception as e:
        logger.exception("Failed to preview import")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to preview import: {str(e)}")


@router.post(
    "/import",
    response_model=ImportResult,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
async def execute_import(
    request: Request,
    settings: SettingsDep,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    file: UploadFile = File(..., description="CSV or XLSX file to import"),
    manager: AssetBulkManager = Depends(get_bulk_manager),
):
    """Upload a file and execute the import, creating/updating assets.

    With the "write asset descriptions to Unity Catalog" setting on, imported
    table, view and column descriptions are written there as the user once
    the import is committed; a failed write is a warning on its row, never
    an error. An empty description cell doesn't remove a Unity Catalog comment.
    """
    success = False
    details: dict = {"params": {"filename": file.filename}}
    saved: List[Tuple[UUID, Optional[str]]] = []

    def record_saved(asset_id: UUID, previous_description: Optional[str]) -> None:
        saved.append((asset_id, previous_description))

    try:
        contents = await file.read()
        filename = file.filename or "upload.csv"
        # Sync database and Unity Catalog work stays off the event loop
        result = await run_in_threadpool(
            manager.execute_import, db, file_bytes=contents, filename=filename,
            current_user_id=current_user.email, after_save=record_saved,
        )
        db.commit()
        await run_in_threadpool(
            _write_imported_descriptions, db, settings, request, result, saved)
        success = result.errors == 0
        details["result"] = {
            "created": result.created,
            "updated": result.updated,
            "errors": result.errors,
            "warnings": result.warnings,
        }
        return result
    except Exception as e:
        logger.exception("Failed to execute import")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to import: {str(e)}")
    finally:
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="IMPORT_ASSETS", success=success, details=details,
        )


def _write_imported_descriptions(
    db, settings, request: Request, result: ImportResult,
    saved: List[Tuple[UUID, Optional[str]]],
) -> None:
    """Write the committed rows' descriptions to Unity Catalog; failures become warnings.

    The user's client is built once per import, and at most
    ``UC_DESCRIPTION_IMPORT_WRITE_LIMIT`` descriptions are written; the rows
    over the limit get a warning. Never raises: the import is committed, so
    a failure here is a warning on the result.
    """
    try:
        from src.routes.assets_routes import _user_workspace_client

        description_sync = UcDescriptionSyncManager(settings)
        limit = int(getattr(settings, 'UC_DESCRIPTION_IMPORT_WRITE_LIMIT', 100) or 0)
        items = {item.asset_id: item for item in result.items if item.asset_id}
    except Exception:
        logger.warning("Could not prepare the Unity Catalog writes of an import", exc_info=True)
        result.warning_messages.append(import_writes_failed_warning())
        return

    client: dict = {}

    def user_client():
        """The user's client, built on the first write; one write per call."""
        if client.get('writes', 0) >= limit:
            raise ImportWriteLimitError('The import write limit is reached.', limit=limit)
        if 'error' in client:
            raise client['error']
        if 'ws' not in client:
            try:
                client['ws'] = _user_workspace_client(request)
            except Exception as e:
                client['error'] = e
                raise
        client['writes'] = client.get('writes', 0) + 1
        return client['ws']

    for asset_id, previous_description in saved:
        try:
            asset = db.get(AssetDb, asset_id)
            warning, _ = description_sync.sync_after_update(
                db, asset_id,
                description_sent=bool(asset is not None and asset.description),
                previous_description=previous_description,
                user_client=user_client,
            )
        except Exception:
            logger.warning("Writing the imported description of asset %s failed", asset_id,
                           exc_info=True)
            continue
        item = items.get(str(asset_id))
        if warning is not None and item is not None:
            item.warnings.append(warning)
            result.warnings += 1


def register_routes(app):
    app.include_router(router)
    logger.info("Asset bulk import/export routes registered with prefix /api/assets/bulk")
