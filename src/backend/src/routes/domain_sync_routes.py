"""
Routes for Sync Domains (#761).

Bidirectional sync of data domains between Ontos and Unity Catalog. UC domains
are account-scoped, so — unlike the Schema Importer — there is no connection to
choose: the caller's on-behalf-of workspace client targets the app's home
Databricks account. Requires the MANAGE DISCOVERY permission on that account.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from src.common.authorization import PermissionChecker
from src.common.config import get_settings
from src.common.dependencies import (
    AuditCurrentUserDep,
    AuditManagerDep,
    DBSessionDep,
)
from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger
from src.common.uc_domains_client import DomainPermissionError, UcDomainsClient
from src.common.workspace_client import get_obo_workspace_client
from src.controller.domain_sync_manager import DomainSyncManager
from src.models.domain_sync import (
    DomainSyncPreview,
    DomainSyncResult,
    ExportRequest,
    ImportRequest,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/domain-sync", tags=["Domain Sync"])

FEATURE_ID = "data-domains"


def _get_manager(request: Request) -> DomainSyncManager:
    """Build a DomainSyncManager backed by the caller's OBO workspace client."""
    settings = get_settings()
    ws = get_obo_workspace_client(request, settings)
    if ws is None:
        raise HTTPException(
            status_code=503,
            detail="No Databricks workspace client available for domain sync.",
        )
    return DomainSyncManager(uc_client=UcDomainsClient(ws))


def _handle(exc: Exception):
    if isinstance(exc, DomainPermissionError):
        raise HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc))
    logger.error("Domain sync failed: %s", exc, exc_info=True)
    raise HTTPException(status_code=500, detail=str(exc))


# ------------------------------------------------------------------
# Import (UC -> Ontos)
# ------------------------------------------------------------------

@router.post(
    "/import/preview",
    response_model=DomainSyncPreview,
    summary="Preview importing UC domains into Ontos",
)
async def import_preview(
    payload: ImportRequest,
    db: DBSessionDep = None,
    manager: DomainSyncManager = Depends(_get_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    try:
        return manager.preview_import(db=db, target_root_id=payload.target_root_id)
    except Exception as exc:  # noqa: BLE001
        _handle(exc)


@router.post(
    "/import/execute",
    response_model=DomainSyncResult,
    summary="Import UC domains into Ontos",
)
async def import_execute(
    payload: ImportRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: DBSessionDep = None,
    manager: DomainSyncManager = Depends(_get_manager),
    audit_manager: AuditManagerDep = None,
    current_user: AuditCurrentUserDep = None,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    try:
        user_id = current_user.email if current_user else "system"
        result = manager.execute_import(db=db, target_root_id=payload.target_root_id, user_id=user_id)
        _audit(background_tasks, audit_manager, current_user, request, "DOMAIN_SYNC_IMPORT", result)
        return result
    except Exception as exc:  # noqa: BLE001
        _handle(exc)


# ------------------------------------------------------------------
# Export (Ontos -> UC)
# ------------------------------------------------------------------

@router.post(
    "/export/preview",
    response_model=DomainSyncPreview,
    summary="Preview exporting Ontos domains to UC",
)
async def export_preview(
    payload: ExportRequest,
    db: DBSessionDep = None,
    manager: DomainSyncManager = Depends(_get_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    try:
        return manager.preview_export(db=db, anchor_domain_id=payload.anchor_domain_id)
    except Exception as exc:  # noqa: BLE001
        _handle(exc)


@router.post(
    "/export/execute",
    response_model=DomainSyncResult,
    summary="Export Ontos domains to UC",
)
async def export_execute(
    payload: ExportRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: DBSessionDep = None,
    manager: DomainSyncManager = Depends(_get_manager),
    audit_manager: AuditManagerDep = None,
    current_user: AuditCurrentUserDep = None,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    try:
        user_id = current_user.email if current_user else "system"
        result = manager.execute_export(db=db, anchor_domain_id=payload.anchor_domain_id, user_id=user_id)
        _audit(background_tasks, audit_manager, current_user, request, "DOMAIN_SYNC_EXPORT", result)
        return result
    except Exception as exc:  # noqa: BLE001
        _handle(exc)


def _audit(background_tasks, audit_manager, current_user, request, action, result: DomainSyncResult):
    if not (audit_manager and current_user):
        return
    background_tasks.add_task(
        audit_manager.log_action_background,
        username=current_user.username,
        ip_address=request.client.host if request.client else None,
        feature=FEATURE_ID,
        action=action,
        success=result.errors == 0,
        details={
            "direction": result.direction.value,
            "created": result.created,
            "matched": result.matched,
            "skipped": result.skipped,
            "errors": result.errors,
        },
    )


def register_routes(app):
    app.include_router(router)
    logger.info("Domain sync routes registered with prefix /api/domain-sync")
