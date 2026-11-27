"""
Routes for staged model imports (erwin; PRD #1718).

  POST   /api/model-import/runs                 upload + parse → previewed run
  GET    /api/model-import/runs                 recent runs (own; all for admins)
  GET    /api/model-import/runs/{id}            run with preview / result
  PATCH  /api/model-import/runs/{id}            change options → new preview + token
  POST   /api/model-import/runs/{id}/confirm    apply (background); needs the preview token
  POST   /api/model-import/runs/{id}/cancel     cancel a previewed or running run

Nothing is written to concepts or contracts before confirm. Writing concepts
needs Read/Write on semantic-models, writing contracts Read/Write on
data-contracts; the checks follow the run's options.
"""

import hashlib
import json
import os
import tempfile
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import ValidationError

from src.common.authorization import enforce_feature_permission, is_user_feature_admin
from src.common.dependencies import AuditManagerDep, CurrentUserDep, DBSessionDep
from src.common.features import FeatureAccessLevel
from src.common.file_security import sanitize_filename
from src.common.logging import get_logger
from src.controller.model_import_manager import ModelImportConflict, ModelImportError, ModelImportManager
from src.db_models.model_import_runs import ModelImportRunDb
from src.model_import.erwin.xml_reader import ErwinParseError
from src.models.model_import import (
    ConfirmModelImportRequest,
    ModelImportOptions,
    ModelImportRunDetail,
    ModelImportRunSummary,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/model-import", tags=["Model Import"])

# Enterprise erwin models are far larger than an ODCS file; the shared 5 MiB
# upload cap does not apply here.
MODEL_IMPORT_MAX_BYTES = int(os.environ.get("MODEL_IMPORT_MAX_BYTES", str(100 * 1024 * 1024)))
_CHUNK = 1024 * 1024
AUDIT_FEATURE = "data-contracts"


def _get_manager(request: Request) -> ModelImportManager:
    manager = getattr(request.app.state, "model_import_manager", None)
    if not manager:
        raise HTTPException(status_code=503, detail="Model import service not configured.")
    return manager


async def _require_write(options: ModelImportOptions, user, request: Request) -> None:
    if not (options.import_logical or options.import_physical):
        raise HTTPException(status_code=422, detail="Select the logical layer, the physical layer, or both.")
    if options.import_logical:
        await enforce_feature_permission("semantic-models", FeatureAccessLevel.READ_WRITE, user, request)
    if options.import_physical:
        await enforce_feature_permission("data-contracts", FeatureAccessLevel.READ_WRITE, user, request)


async def _is_admin(user, request: Request) -> bool:
    try:
        return await is_user_feature_admin(user.email, user.groups, "data-contracts", request)
    except Exception:
        return False


async def _get_visible_run(db, run_id: str, manager: ModelImportManager, user, request: Request) -> ModelImportRunDb:
    run = manager.get_run(db, run_id)
    if run is None or (run.user_id != user.email and not await _is_admin(user, request)):
        raise HTTPException(status_code=404, detail="Import run not found.")
    return run


def _detail(run: ModelImportRunDb) -> ModelImportRunDetail:
    return ModelImportRunDetail(
        id=run.id, status=run.status, source_kind=run.source_kind,
        source_filename=run.source_filename, source_model_name=run.source_model_name,
        source_model_version=run.source_model_version, progress_message=run.progress_message,
        error=run.error, user_id=run.user_id, created_at=run.created_at,
        completed_at=run.completed_at, expires_at=run.expires_at,
        source_sha256=run.source_sha256, source_size_bytes=run.source_size_bytes,
        options=ModelImportOptions.model_validate(run.options) if run.options else None,
        preview=run.preview,
        confirm_token=run.confirm_token if run.status == "previewed" else None,
        result=run.result,
    )


def _summary(run: ModelImportRunDb) -> ModelImportRunSummary:
    return ModelImportRunSummary(
        id=run.id, status=run.status, source_kind=run.source_kind,
        source_filename=run.source_filename, source_model_name=run.source_model_name,
        source_model_version=run.source_model_version, progress_message=run.progress_message,
        error=run.error, user_id=run.user_id, created_at=run.created_at,
        completed_at=run.completed_at, expires_at=run.expires_at,
    )


def _audit(background_tasks, audit_manager, request, user, action: str, success: bool, details: dict) -> None:
    if audit_manager and user:
        background_tasks.add_task(
            audit_manager.log_action_background,
            username=user.username or user.email,
            ip_address=request.client.host if request.client else None,
            feature=AUDIT_FEATURE,
            action=action,
            success=success,
            details=details,
        )


@router.post("/runs", response_model=ModelImportRunDetail, status_code=status.HTTP_201_CREATED,
             summary="Upload an erwin model export and stage a previewed import run")
async def create_run(
    request: Request,
    background_tasks: BackgroundTasks,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    audit_manager: AuditManagerDep,
    file: UploadFile = File(...),
    options: Optional[str] = Form(None, description="ModelImportOptions as JSON"),
    manager: ModelImportManager = Depends(_get_manager),
):
    try:
        opts = ModelImportOptions.model_validate(json.loads(options)) if options else ModelImportOptions()
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid options: {exc}")
    await _require_write(opts, current_user, request)

    filename = sanitize_filename(file.filename or "model.xml", default="model.xml")
    sha = hashlib.sha256()
    size = 0
    with tempfile.TemporaryFile() as tmp:
        while True:
            chunk = await file.read(_CHUNK)
            if not chunk:
                break
            size += len(chunk)
            if size > MODEL_IMPORT_MAX_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File exceeds the {MODEL_IMPORT_MAX_BYTES // (1024 * 1024)} MiB limit for model imports.",
                )
            sha.update(chunk)
            tmp.write(chunk)
        if size == 0:
            raise HTTPException(status_code=422, detail="The file is empty.")
        tmp.seek(0)
        try:
            run = manager.create_run(
                db, stream=tmp, filename=filename, size_bytes=size, sha256=sha.hexdigest(),
                user_id=current_user.email, options=opts,
            )
        except ErwinParseError as exc:
            _audit(background_tasks, audit_manager, request, current_user, "MODEL_IMPORT_STAGE", False,
                   {"filename": filename, "error": str(exc)})
            raise HTTPException(status_code=422, detail=str(exc))
        except ModelImportError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    _audit(background_tasks, audit_manager, request, current_user, "MODEL_IMPORT_STAGE", True,
           {"run_id": run.id, "filename": filename, "sha256": run.source_sha256, "model": run.source_model_name})
    return _detail(run)


@router.get("/runs", response_model=List[ModelImportRunSummary], summary="Recent model import runs")
async def list_runs(
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    limit: int = 50,
    manager: ModelImportManager = Depends(_get_manager),
):
    await enforce_feature_permission("data-contracts", FeatureAccessLevel.READ_ONLY, current_user, request)
    user_id = None if await _is_admin(current_user, request) else current_user.email
    return [_summary(r) for r in manager.list_runs(db, user_id, limit=max(1, min(limit, 200)))]


@router.get("/runs/{run_id}", response_model=ModelImportRunDetail, summary="A model import run")
async def get_run(
    run_id: str,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    manager: ModelImportManager = Depends(_get_manager),
):
    await enforce_feature_permission("data-contracts", FeatureAccessLevel.READ_ONLY, current_user, request)
    return _detail(await _get_visible_run(db, run_id, manager, current_user, request))


@router.patch("/runs/{run_id}", response_model=ModelImportRunDetail,
              summary="Change a previewed run's options and recompute its preview")
async def update_run(
    run_id: str,
    options: ModelImportOptions,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    manager: ModelImportManager = Depends(_get_manager),
):
    await _require_write(options, current_user, request)
    run = await _get_visible_run(db, run_id, manager, current_user, request)
    if run.user_id != current_user.email:
        raise HTTPException(status_code=403, detail="Only the user who uploaded the model can change this run.")
    try:
        return _detail(manager.update_options(db, run, options))
    except ModelImportError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/runs/{run_id}/confirm", response_model=ModelImportRunDetail, status_code=status.HTTP_202_ACCEPTED,
             summary="Apply a previewed run in the background")
async def confirm_run(
    run_id: str,
    payload: ConfirmModelImportRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    audit_manager: AuditManagerDep,
    manager: ModelImportManager = Depends(_get_manager),
):
    run = await _get_visible_run(db, run_id, manager, current_user, request)
    if run.user_id != current_user.email:
        raise HTTPException(status_code=403, detail="Only the user who uploaded the model can confirm this run.")
    await _require_write(ModelImportOptions.model_validate(run.options or {}), current_user, request)
    try:
        run = manager.confirm_run(db, run, payload.confirm_token, current_user.email)
    except ModelImportConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ModelImportError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    _audit(background_tasks, audit_manager, request, current_user, "MODEL_IMPORT_CONFIRM", True,
           {"run_id": run.id, "model": run.source_model_name, "options": run.options})
    return _detail(run)


@router.post("/runs/{run_id}/cancel", response_model=ModelImportRunDetail, summary="Cancel a run")
async def cancel_run(
    run_id: str,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    manager: ModelImportManager = Depends(_get_manager),
):
    run = await _get_visible_run(db, run_id, manager, current_user, request)
    if run.user_id != current_user.email and not await _is_admin(current_user, request):
        raise HTTPException(status_code=403, detail="Not allowed to cancel this run.")
    try:
        return _detail(manager.cancel_run(db, run))
    except ModelImportError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


def register_routes(app):
    app.include_router(router)
    logger.info("Model import routes registered")
