"""FastAPI routes for the Term Mapping feature.

Exposes:
  POST   /api/term-mappings/runs                    create + execute a run
  GET    /api/term-mappings/runs                    list recent runs
  GET    /api/term-mappings/runs/{run_id}           get one run
  GET    /api/term-mappings/runs/{run_id}/suggestions   list suggestions for run
  POST   /api/term-mappings/runs/{run_id}/decisions     bulk accept/reject
  POST   /api/term-mappings/runs/{run_id}/apply         materialise links
  POST   /api/term-mappings/runs/{run_id}/undo          revert last apply (ADMIN)
  GET    /api/term-mappings/entities/{type}/{id}/suggestions  per-entity badge data
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..common.authorization import PermissionChecker
from ..common.database import get_db
from ..common.dependencies import CurrentUserDep
from ..common.features import FeatureAccessLevel
from ..common.logging import get_logger
from ..controller.term_mapping_manager import TermMappingManager
from ..models.term_mappings import (
    ApplyResult,
    GenerateReviewRequest,
    GenerateReviewResponse,
    InlineSuggestRequest,
    InlineSuggestResponse,
    PendingSuggestionCount,
    RunCreate,
    RunRead,
    RunSummary,
    SuggestionDecisionBatch,
    SuggestionDecisionResult,
    SuggestionRead,
    UndoResult,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/api/term-mappings", tags=["Term Mapping"])

FEATURE_ID = "term-mapping"


def _get_manager(request: Request) -> TermMappingManager:
    mgr: Optional[TermMappingManager] = getattr(request.app.state, "term_mapping_manager", None)
    if mgr is None:
        raise HTTPException(
            status_code=503,
            detail="TermMappingManager not initialised (semantic models manager unavailable?)",
        )
    return mgr


# ------------------------------------------------------------------
# Run lifecycle
# ------------------------------------------------------------------

@router.post("/runs", response_model=RunRead, status_code=201)
async def create_run(
    payload: RunCreate,
    request: Request,
    user: CurrentUserDep,
    db: Session = Depends(get_db),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
) -> RunRead:
    """Create a term-mapping run and execute the configured engines synchronously.

    Returns the persisted run with stats. For large estates this becomes a
    background-job-backed endpoint in a future phase.
    """
    try:
        return _get_manager(request).create_run(
            db, payload=payload, created_by=getattr(user, "email", None)
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/runs", response_model=List[RunSummary])
async def list_runs(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
) -> List[RunSummary]:
    return _get_manager(request).list_runs(db, limit=limit)


@router.get("/runs/{run_id}", response_model=RunRead)
async def get_run(
    run_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
) -> RunRead:
    run = _get_manager(request).get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return run


# ------------------------------------------------------------------
# Suggestion queue
# ------------------------------------------------------------------

@router.get("/runs/{run_id}/suggestions", response_model=List[SuggestionRead])
async def list_suggestions(
    run_id: str,
    request: Request,
    status: Optional[str] = Query(None, description="Filter by suggestion status"),
    source_entity_type: Optional[str] = Query(None),
    source_entity_id: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
) -> List[SuggestionRead]:
    return _get_manager(request).list_suggestions(
        db,
        run_id=run_id,
        status=status,
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/runs/{run_id}/decisions",
    response_model=SuggestionDecisionResult,
)
async def decide_suggestions(
    run_id: str,
    batch: SuggestionDecisionBatch,
    request: Request,
    user: CurrentUserDep,
    db: Session = Depends(get_db),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
) -> SuggestionDecisionResult:
    # run_id is currently informational — decisions are keyed by suggestion id
    # (each one already carries its run via the FK), but accepting it in the
    # path keeps the route hierarchy readable and prevents accidental
    # cross-run posts from a malformed UI.
    return _get_manager(request).decide(
        db, batch=batch, decided_by=getattr(user, "email", None)
    )


# ------------------------------------------------------------------
# Apply / Undo
# ------------------------------------------------------------------

@router.post("/runs/{run_id}/apply", response_model=ApplyResult)
async def apply_run(
    run_id: str,
    request: Request,
    user: CurrentUserDep,
    apply_auto: bool = Query(
        True,
        description="When true, also apply pending suggestions with auto_apply=True.",
    ),
    db: Session = Depends(get_db),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
) -> ApplyResult:
    try:
        return _get_manager(request).apply_run(
            db, run_id=run_id, apply_auto=apply_auto, applied_by=getattr(user, "email", None)
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/runs/{run_id}/undo", response_model=UndoResult)
async def undo_run(
    run_id: str,
    request: Request,
    user: CurrentUserDep,
    db: Session = Depends(get_db),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.ADMIN)),
) -> UndoResult:
    """ADMIN-only: remove every entity_semantic_links row this run produced
    and revert applied suggestions back to ``accepted``."""
    try:
        return _get_manager(request).undo_run(
            db, run_id=run_id, undone_by=getattr(user, "email", None)
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ------------------------------------------------------------------
# Per-entity badge data
# ------------------------------------------------------------------

@router.get(
    "/entities/{entity_type}/{entity_id:path}/suggestions",
    response_model=List[SuggestionRead],
)
async def list_entity_suggestions(
    entity_type: str,
    entity_id: str,
    request: Request,
    include_decided: bool = Query(False),
    db: Session = Depends(get_db),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
) -> List[SuggestionRead]:
    """All term-mapping suggestions for a single entity, across runs.

    Backs the per-entity-panel 'N pending suggestions' panel. entity_id is
    declared with :path so contract-property compound ids (containing '#')
    pass through without re-encoding.
    """
    return _get_manager(request).list_suggestions_for_entity(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        include_decided=include_decided,
    )


@router.get(
    "/entities/{entity_type}/{entity_id:path}/pending-count",
    response_model=PendingSuggestionCount,
)
async def pending_count(
    entity_type: str,
    entity_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
) -> PendingSuggestionCount:
    return _get_manager(request).pending_count_for_entity(
        db, entity_type=entity_type, entity_id=entity_id
    )


# ------------------------------------------------------------------
# Review spawn (MDM-style write-through copy of the suggestion queue)
# ------------------------------------------------------------------

@router.post("/runs/{run_id}/review", response_model=GenerateReviewResponse, status_code=201)
async def generate_review_for_run(
    run_id: str,
    payload: GenerateReviewRequest,
    request: Request,
    user: CurrentUserDep,
    db: Session = Depends(get_db),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
) -> GenerateReviewResponse:
    """Spawn a DataAssetReviewRequest for the run's pending suggestions.

    Same pattern as MDM: every pending suggestion becomes a ReviewedAsset
    with FQN `term-mapping://{run_id}/{suggestion_id}`. The TermMappingSuggestionReview
    editor in the AR UI talks back to this feature's `/decisions` endpoint, which
    updates the suggestion and forward-syncs ReviewedAsset.status. Deleting the
    review nulls the suggestion back-pointers; the suggestion (and its decision)
    survives.
    """
    try:
        return _get_manager(request).create_review_for_run(
            db,
            run_id=run_id,
            payload=payload,
            requester_email=getattr(user, "email", None),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ------------------------------------------------------------------
# Inline suggester (ConceptSelectDialog "Suggested by mapping" tier)
# ------------------------------------------------------------------

@router.post("/suggestions-for", response_model=InlineSuggestResponse)
async def suggestions_for_entity(
    payload: InlineSuggestRequest,
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
) -> InlineSuggestResponse:
    """Ad-hoc heuristic suggestions for a single entity. No persistence."""
    try:
        return _get_manager(request).suggest_inline(db, payload=payload)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ------------------------------------------------------------------
# Registration
# ------------------------------------------------------------------

def register_routes(app):
    app.include_router(router)
    logger.info("Term-mapping routes registered")
