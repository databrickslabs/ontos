"""Connector sync routes: saved Schema Importer selections the connector_sync job imports again (#1312)."""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.common.authorization import PermissionChecker
from src.common.dependencies import AuditCurrentUserDep, AuditManagerDep, DBSessionDep
from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger
from src.common.manager_dependencies import get_jobs_manager
from src.controller.connector_sync_manager import connector_sync_manager
from src.db_models.connections import ConnectionDb
from src.db_models.connector_syncs import ConnectorSyncDb
from src.db_models.schema_import_runs import SchemaImportRunDb
from src.models.connector_syncs import (
    ConnectorSyncCreate,
    ConnectorSyncRead,
    ConnectorSyncRunStarted,
    ConnectorSyncUpdate,
)
from src.models.schema_import import SchemaImportRunSummary
from src.repositories.workflow_installations_repository import workflow_installation_repo

logger = get_logger(__name__)

router = APIRouter(prefix="/api/connector-syncs", tags=["Connector Syncs"])
FEATURE_ID = "schema-importer"
WORKFLOW_ID = "connector_sync"
JOB_NAME = "Connector Sync"


def _read(sync: ConnectorSyncDb, job_warning: Optional[str] = None) -> ConnectorSyncRead:
    request = sync.request or {}
    return ConnectorSyncRead(
        id=sync.id, name=sync.name, connection_id=sync.connection_id,
        selected_paths=request.get("selected_paths") or [], depth=request.get("depth") or "full_recursive",
        excluded_paths=request.get("excluded_paths") or [], interval_minutes=sync.interval_minutes,
        retire_after_misses=sync.retire_after_misses, enabled=sync.enabled, last_run_id=sync.last_run_id,
        last_run_at=sync.last_run_at, last_status=sync.last_status, last_complete_sync_at=sync.last_complete_sync_at,
        next_due_at=sync.next_due_at, created_by=sync.created_by, created_at=sync.created_at, job_warning=job_warning,
    )


def _get(db, sync_id: str) -> ConnectorSyncDb:
    sync = connector_sync_manager.get(db, sync_id)
    if sync is None:
        raise HTTPException(status_code=404, detail="Connector sync not found")
    return sync


def _ensure_job(request: Request, db) -> int:
    """Install the connector_sync job (once) and make sure its schedule runs; returns its job id."""
    jobs = get_jobs_manager(request)
    installation = workflow_installation_repo.get_by_workflow_id(db, workflow_id=WORKFLOW_ID)
    job_id = int(installation.job_id) if installation else jobs.install_workflow(WORKFLOW_ID)
    jobs.resume_job(job_id)
    return job_id


def _job_warning(request: Request, db) -> Optional[str]:
    try:
        _ensure_job(request, db)
        return None
    except Exception as exc:
        logger.warning(f"Could not install or start the {WORKFLOW_ID} job: {exc}", exc_info=True)
        return ("The sync was saved, but its scheduled job could not be installed or started. "
                "An administrator can enable the 'Connector Sync' workflow in Settings → Jobs.")


def _audit(audit_manager, current_user, request: Request, action: str, details: dict) -> None:
    if audit_manager and current_user:
        audit_manager.log_action(
            db=None, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action=action, success=True, details=details,
        )


@router.get("", response_model=List[ConnectorSyncRead])
def list_syncs(
    db: DBSessionDep,
    connection_id: Optional[UUID] = Query(None),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    return [_read(s) for s in connector_sync_manager.list(db, connection_id)]


@router.post("", response_model=ConnectorSyncRead, status_code=201)
def create_sync(
    payload: ConnectorSyncCreate,
    request: Request,
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
    audit_manager: AuditManagerDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    if db.get(ConnectionDb, payload.connection_id) is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    sync = connector_sync_manager.create(
        db, name=payload.name, connection_id=payload.connection_id,
        request=payload.model_dump(mode="json", include={"selected_paths", "depth", "excluded_paths"}),
        interval_minutes=payload.interval_minutes, retire_after_misses=payload.retire_after_misses,
        enabled=payload.enabled, created_by=current_user.username if current_user else None,
    )
    db.commit()
    warning = _job_warning(request, db) if sync.enabled else None
    _audit(audit_manager, current_user, request, "CREATE_CONNECTOR_SYNC",
           {"sync_id": sync.id, "connection_id": str(payload.connection_id)})
    return _read(sync, warning)


@router.get("/{sync_id}", response_model=ConnectorSyncRead)
def get_sync(
    sync_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    return _read(_get(db, sync_id))


@router.put("/{sync_id}", response_model=ConnectorSyncRead)
def update_sync(
    sync_id: str,
    payload: ConnectorSyncUpdate,
    request: Request,
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
    audit_manager: AuditManagerDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    sync = _get(db, sync_id)
    changes = payload.model_dump(exclude_unset=True, mode="json")
    selection = {k: changes.pop(k) for k in ("selected_paths", "depth", "excluded_paths") if k in changes}
    if selection:
        changes["request"] = {**(sync.request or {}), **selection}
    was_enabled = sync.enabled
    connector_sync_manager.update(db, sync, **changes)
    db.commit()
    warning = _job_warning(request, db) if sync.enabled and not was_enabled else None
    _audit(audit_manager, current_user, request, "UPDATE_CONNECTOR_SYNC", {"sync_id": sync.id})
    return _read(sync, warning)


@router.delete("/{sync_id}", status_code=204)
def delete_sync(
    sync_id: str,
    request: Request,
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
    audit_manager: AuditManagerDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    connector_sync_manager.delete(db, _get(db, sync_id))
    db.commit()
    _audit(audit_manager, current_user, request, "DELETE_CONNECTOR_SYNC", {"sync_id": sync_id})


@router.post("/{sync_id}/run", response_model=ConnectorSyncRunStarted, status_code=202)
def run_sync_now(
    sync_id: str,
    request: Request,
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
    audit_manager: AuditManagerDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Start the connector_sync job for this sync now (the job runs it even when it isn't due)."""
    sync = _get(db, sync_id)
    try:
        job_id = _ensure_job(request, db)
        run_id = get_jobs_manager(request).run_job(
            job_id, job_name=JOB_NAME, job_parameters={"sync_id": sync.id}, workflow_id=WORKFLOW_ID,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Could not start connector sync {sync_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=502, detail="Could not start the Connector Sync job")
    _audit(audit_manager, current_user, request, "RUN_CONNECTOR_SYNC", {"sync_id": sync.id, "job_run_id": run_id})
    return ConnectorSyncRunStarted(job_run_id=run_id)


@router.get("/{sync_id}/runs", response_model=List[SchemaImportRunSummary])
def list_sync_runs(
    sync_id: str,
    db: DBSessionDep,
    limit: int = Query(20, ge=1, le=100),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    _get(db, sync_id)
    return (
        db.query(SchemaImportRunDb)
        .filter(SchemaImportRunDb.sync_id == sync_id)
        .order_by(SchemaImportRunDb.created_at.desc())
        .limit(limit)
        .all()
    )


def register_routes(app):
    app.include_router(router)
    logger.info("Connector sync routes registered")
