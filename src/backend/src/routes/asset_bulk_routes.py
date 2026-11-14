"""
Asset Bulk Import/Export Routes

Provides endpoints for exporting assets as CSV/XLSX and importing
assets from uploaded files with preview and validation.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response

from src.common.authorization import PermissionChecker
from src.common.dependencies import (
    AuditCurrentUserDep,
    AuditManagerDep,
    DBSessionDep,
)
from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger
from src.controller.asset_bulk_manager import (
    AssetBulkManager,
    ImportPreviewResult,
    ImportResult,
)

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
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    file: UploadFile = File(..., description="CSV or XLSX file to import"),
    manager: AssetBulkManager = Depends(get_bulk_manager),
):
    """Upload a file and execute the import, creating/updating assets."""
    success = False
    details: dict = {"params": {"filename": file.filename}}
    try:
        contents = await file.read()
        filename = file.filename or "upload.csv"
        result = manager.execute_import(
            db, file_bytes=contents, filename=filename, current_user_id=current_user.email,
        )
        # Tags of imported assets are indexed for search: refresh each touched asset's entry
        assets_manager = getattr(request.app.state, "assets_manager", None)
        if assets_manager is not None:
            for item in result.items:
                if item.asset_id:
                    try:
                        assets_manager.refresh_search_entry(db, UUID(item.asset_id))
                    except Exception as e:
                        logger.warning(f"Search refresh failed for imported asset {item.asset_id}: {e}")
        success = result.errors == 0
        details["result"] = {
            "created": result.created,
            "updated": result.updated,
            "errors": result.errors,
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


def register_routes(app):
    app.include_router(router)
    logger.info("Asset bulk import/export routes registered with prefix /api/assets/bulk")
