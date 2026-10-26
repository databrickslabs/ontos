"""API routes for Metadata Generation (Generation Runs and Description Suggestions).

POST /runs returns 202 with a run id; the dbxmetagen background job does the
work. GET /runs/{run_id} refreshes the run from the Jobs API while it is in
flight, so the UI's polling drives completion and ingest.

POST /runs/{run_id}/review puts the pending suggestions up for Asset Review;
the review's reviewer reads them (GET .../suggestions/{id}) and decides
(POST .../decisions) under the data-asset-reviews feature permissions.

POST /runs/{run_id}/apply writes accepted suggestions of approved reviews to
UC (normally the review workflow does this); feature admins can force
Conflicts.
"""

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool

from src.common.authorization import PermissionChecker, is_user_feature_admin
from src.common.dependencies import AuditCurrentUserDep, AuditManagerDep, DBSessionDep
from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger
from src.controller.metadata_generation_manager import ActiveRunLimitError, MetadataGenerationManager
from src.models.metadata_generation import (
    ApplyRequest,
    ApplyResult,
    DescriptionSuggestion,
    GenerationRunDetail,
    GenerationRunStatus,
    GenerationRunSummary,
    RunListResponse,
    SelectionItem,
    StartRunRequest,
    StartRunResponse,
    SubmitReviewRequest,
    SubmitReviewResponse,
    SuggestionCounts,
    SuggestionDecisionBatch,
    SuggestionDecisionResult,
    SuggestionListResponse,
    SuggestionStatus,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/metadata-generation", tags=["Metadata Generation"])
FEATURE_ID = "metadata-generation"
REVIEWS_FEATURE_ID = "data-asset-reviews"


def _get_manager(request: Request) -> MetadataGenerationManager:
    manager = getattr(request.app.state, "metadata_generation_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Metadata Generation service not configured.")
    return manager


def _user_id(current_user) -> str:
    return current_user.email or current_user.username or "unknown"


def _to_summary(run) -> GenerationRunSummary:
    return GenerationRunSummary(
        run_id=run.id,
        user_id=run.user_id,
        status=GenerationRunStatus(run.status),
        progress_message=run.progress_message,
        error=run.error,
        selection=[SelectionItem(**item) for item in (run.selection or [])],
        options=run.options or {},
        job_run_id=run.job_run_id,
        suggestion_count=run.suggestion_count or 0,
        created_at=run.created_at,
        updated_at=run.updated_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


async def _get_visible_run(request: Request, db, current_user, manager: MetadataGenerationManager, run_id: str):
    """Owners see their runs, feature admins see all; others get 404."""
    run = manager.get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.user_id != _user_id(current_user):
        is_admin = await is_user_feature_admin(current_user.email, current_user.groups, FEATURE_ID, request)
        if not is_admin:
            raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post(
    "/runs",
    response_model=StartRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a Generation Run over UC catalogs, schemas or tables",
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def start_run(
    request: Request,
    body: StartRunRequest,
    background_tasks: BackgroundTasks,
    db: DBSessionDep = None,
    audit_manager: AuditManagerDep = None,
    current_user: AuditCurrentUserDep = None,
):
    manager = _get_manager(request)
    success = False
    details = {"selection_count": len(body.selection), "regenerate_existing": body.regenerate_existing}
    try:
        run = manager.start_run(
            db,
            user_id=_user_id(current_user),
            request=body,
            # Finished runs found on the way are ingested after the response
            defer_ingest=manager.make_deferrer(background_tasks.add_task),
        )
        success = True
        details["run_id"] = run.id
        return StartRunResponse(run_id=run.id, status=GenerationRunStatus(run.status))
    except HTTPException:
        # Includes ConflictError when the background job is not enabled
        raise
    except ActiveRunLimitError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Failed to start metadata generation run")
        details["exception"] = {"type": type(e).__name__}
        raise HTTPException(status_code=500, detail="Failed to start the Generation Run")
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID,
            action="START_METADATA_GENERATION",
            success=success,
            details=details,
        )


@router.get(
    "/runs",
    response_model=RunListResponse,
    summary="List Generation Runs (own runs; all runs for feature admins)",
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
async def list_runs(
    request: Request,
    db: DBSessionDep = None,
    current_user: AuditCurrentUserDep = None,
    limit: int = Query(50, ge=1, le=200),
):
    manager = _get_manager(request)
    is_admin = await is_user_feature_admin(current_user.email, current_user.groups, FEATURE_ID, request)
    runs = manager.list_runs(db, None if is_admin else _user_id(current_user), limit=limit)
    return RunListResponse(runs=[_to_summary(r) for r in runs])


@router.get(
    "/runs/{run_id}",
    response_model=GenerationRunDetail,
    summary="Get a Generation Run, refreshing its status from the Jobs API",
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
async def get_run(
    run_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: DBSessionDep = None,
    current_user: AuditCurrentUserDep = None,
):
    manager = _get_manager(request)
    run = await _get_visible_run(request, db, current_user, manager, run_id)
    try:
        # The Jobs API call stays off the event loop; a finished run's
        # warehouse ingest runs after the response, not during the poll
        run = await run_in_threadpool(
            manager.refresh_run,
            db,
            run,
            defer_ingest=manager.make_deferrer(background_tasks.add_task),
        )
    except Exception:
        logger.warning("Failed to refresh metadata generation run %s", run_id, exc_info=True)
        db.rollback()
    summary = _to_summary(run)
    unsubmitted, review_request_ids, applicable = manager.review_summary(db, run.id)
    return GenerationRunDetail(
        **summary.model_dump(),
        counts=SuggestionCounts(**manager.counts(db, run.id)),
        unsubmitted=unsubmitted,
        review_request_ids=review_request_ids,
        applicable=applicable,
    )


@router.get(
    "/runs/{run_id}/suggestions",
    response_model=SuggestionListResponse,
    summary="List a run's Description Suggestions",
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
async def list_suggestions(
    run_id: str,
    request: Request,
    db: DBSessionDep = None,
    current_user: AuditCurrentUserDep = None,
    status_filter: Optional[SuggestionStatus] = Query(None, alias="status"),
    limit: int = Query(1000, ge=1, le=5000),
    skip: int = Query(0, ge=0),
):
    manager = _get_manager(request)
    run = await _get_visible_run(request, db, current_user, manager, run_id)
    status_value = status_filter.value if status_filter else None
    rows = manager.list_suggestions(db, run.id, status=status_value, limit=limit, skip=skip)
    return SuggestionListResponse(
        suggestions=[DescriptionSuggestion.model_validate(r) for r in rows],
        total=manager.count_suggestions(db, run.id, status=status_value),
    )


@router.post(
    "/runs/{run_id}/cancel",
    response_model=GenerationRunSummary,
    summary="Cancel a running Generation Run",
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
async def cancel_run(
    run_id: str,
    request: Request,
    db: DBSessionDep = None,
    audit_manager: AuditManagerDep = None,
    current_user: AuditCurrentUserDep = None,
):
    manager = _get_manager(request)
    run = await _get_visible_run(request, db, current_user, manager, run_id)
    success = False
    try:
        run = await run_in_threadpool(manager.cancel_run, db, run)
        success = True
        return _to_summary(run)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception:
        logger.exception("Failed to cancel metadata generation run %s", run_id)
        raise HTTPException(status_code=500, detail="Failed to cancel the Generation Run")
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID,
            action="CANCEL_METADATA_GENERATION",
            success=success,
            details={"run_id": run_id},
        )


@router.delete(
    "/runs/{run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a finished Generation Run and its suggestions",
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
async def delete_run(
    run_id: str,
    request: Request,
    db: DBSessionDep = None,
    audit_manager: AuditManagerDep = None,
    current_user: AuditCurrentUserDep = None,
):
    manager = _get_manager(request)
    run = await _get_visible_run(request, db, current_user, manager, run_id)
    success = False
    try:
        manager.delete_run(db, run)
        success = True
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID,
            action="DELETE_METADATA_GENERATION_RUN",
            success=success,
            details={"run_id": run_id},
        )


@router.post(
    "/runs/{run_id}/review",
    response_model=SubmitReviewResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a run's pending Description Suggestions for Asset Review",
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
async def submit_for_review(
    run_id: str,
    body: SubmitReviewRequest,
    request: Request,
    db: DBSessionDep = None,
    audit_manager: AuditManagerDep = None,
    current_user: AuditCurrentUserDep = None,
):
    manager = _get_manager(request)
    run = await _get_visible_run(request, db, current_user, manager, run_id)
    success = False
    details = {"run_id": run_id}
    try:
        # Resolving a default reviewer reads workspace groups
        result = await run_in_threadpool(
            manager.create_review_for_run,
            db,
            run,
            requester_email=current_user.email or _user_id(current_user),
            reviewer_email=body.reviewer_email,
            notes=body.notes,
        )
        success = True
        details.update(review_request_id=result.review_request_id, suggestion_count=result.suggestion_count)
        return result
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.exception("Failed to submit metadata generation run %s for review", run_id)
        details["exception"] = {"type": type(e).__name__}
        raise HTTPException(status_code=500, detail="Failed to submit the Generation Run for review")
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID,
            action="SUBMIT_METADATA_GENERATION_REVIEW",
            success=success,
            details=details,
        )


async def _can_review(request: Request, db, current_user, manager: MetadataGenerationManager, run, suggestion) -> bool:
    """The suggestion's reviewer, the run's owner and feature admins may see it."""
    if run.user_id == _user_id(current_user):
        return True
    _, reviewer = manager.get_review_assignees(db, suggestion.review_request_id)
    if reviewer and current_user.email and reviewer.lower() == current_user.email.lower():
        return True
    return await is_user_feature_admin(current_user.email, current_user.groups, FEATURE_ID, request)


@router.get(
    "/runs/{run_id}/suggestions/{suggestion_id}",
    response_model=DescriptionSuggestion,
    summary="Get one Description Suggestion (for its reviewer)",
    dependencies=[Depends(PermissionChecker(REVIEWS_FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
async def get_suggestion(
    run_id: str,
    suggestion_id: str,
    request: Request,
    db: DBSessionDep = None,
    current_user: AuditCurrentUserDep = None,
):
    manager = _get_manager(request)
    run = manager.get_run(db, run_id)
    suggestion = manager.get_suggestion(db, suggestion_id)
    if run is None or suggestion is None or suggestion.run_id != run.id:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if not await _can_review(request, db, current_user, manager, run, suggestion):
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return DescriptionSuggestion.model_validate(suggestion)


@router.post(
    "/runs/{run_id}/decisions",
    response_model=SuggestionDecisionResult,
    summary="Record the reviewer's decisions on Description Suggestions",
    dependencies=[Depends(PermissionChecker(REVIEWS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
async def decide_suggestions(
    run_id: str,
    batch: SuggestionDecisionBatch,
    request: Request,
    db: DBSessionDep = None,
    audit_manager: AuditManagerDep = None,
    current_user: AuditCurrentUserDep = None,
):
    manager = _get_manager(request)
    run = manager.get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    is_admin = await is_user_feature_admin(current_user.email, current_user.groups, FEATURE_ID, request)
    success = False
    details = {"run_id": run_id, "decisions": len(batch.decisions)}
    try:
        result = await run_in_threadpool(
            manager.decide, db, run, batch, decided_by=current_user.email or _user_id(current_user), is_admin=is_admin,
        )
        success = True
        details.update(accepted=result.accepted, rejected=result.rejected, clarify=result.clarify, skipped=result.skipped)
        return result
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID,
            action="DECIDE_METADATA_SUGGESTIONS",
            success=success,
            details=details,
        )


@router.post(
    "/runs/{run_id}/apply",
    response_model=ApplyResult,
    summary="Apply a run's accepted, approved Description Suggestions to Unity Catalog",
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
async def apply_suggestions(
    run_id: str,
    body: ApplyRequest,
    request: Request,
    db: DBSessionDep = None,
    audit_manager: AuditManagerDep = None,
    current_user: AuditCurrentUserDep = None,
):
    manager = _get_manager(request)
    run = await _get_visible_run(request, db, current_user, manager, run_id)
    success = False
    details = {"run_id": run_id, "source": "manual", "force": body.force}
    try:
        if body.force and not await is_user_feature_admin(
            current_user.email, current_user.groups, FEATURE_ID, request
        ):
            raise HTTPException(status_code=403, detail="Only administrators can force-apply conflicts")
        # One UC read and write per object: keep it off the event loop
        result = await run_in_threadpool(
            manager.apply_suggestions,
            db,
            run,
            applied_by=current_user.email or _user_id(current_user),
            suggestion_ids=body.suggestion_ids,
            force=body.force,
        )
        success = result.failed == 0
        details.update(
            applied=result.applied, conflict=result.conflict,
            not_applicable=result.not_applicable, failed=result.failed,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to apply descriptions of metadata generation run %s", run_id)
        details["exception"] = {"type": type(e).__name__}
        raise HTTPException(status_code=500, detail="Failed to apply the descriptions")
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID,
            action="APPLY_METADATA_SUGGESTIONS",
            success=success,
            details=details,
        )


def register_routes(app):
    app.include_router(router)
    logger.info("Metadata generation routes registered")
