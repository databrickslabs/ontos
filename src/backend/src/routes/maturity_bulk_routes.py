"""API routes for the bulk maturity evaluation of table and view assets.

Kept apart from maturity_routes.py; registered by its register_routes.
"""
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from src.common.authorization import PermissionChecker
from src.common.dependencies import CurrentUserDep
from src.common.features import FeatureAccessLevel
from src.models.maturity import (
    MaturityBulkEvaluationRequest,
    MaturityBulkEvaluationRun,
)

router = APIRouter(prefix="/api", tags=["Maturity Levels"])

SETTINGS_FEATURE_ID = "settings"


# ===================================================================
# Bulk evaluation of table and view assets (same permission as the levels)
# ===================================================================

@router.post(
    "/maturity-evaluations/assets",
    response_model=MaturityBulkEvaluationRun,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_bulk_asset_maturity_evaluation(
    body: MaturityBulkEvaluationRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUserDep,
    _: bool = Depends(PermissionChecker(SETTINGS_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Start a bulk evaluation of the table and view assets in a scope. Admin only.

    Answers 202 with the run; poll ``GET /api/maturity-evaluations/assets/latest`` for
    progress. 409 ``maturity_bulk_run_in_progress`` while another run is going.
    """
    from src.controller import maturity_bulk_evaluator as bulk

    try:
        scope = bulk.normalize_scope(body.catalog, body.schema_name, body.asset_types)
        run = bulk.start_run(
            scope, started_by=current_user.email,
            max_workers=body.max_workers, batch_size=body.batch_size,
        )
    except bulk.MaturityBulkScopeError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except bulk.MaturityBulkRunInProgressError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    background_tasks.add_task(
        bulk.execute_run, run["id"], scope, evaluated_by=current_user.email,
    )
    return run


@router.get(
    "/maturity-evaluations/assets/latest",
    response_model=Optional[MaturityBulkEvaluationRun],
)
def get_latest_bulk_asset_maturity_evaluation(
    _: bool = Depends(PermissionChecker(SETTINGS_FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """The running bulk evaluation, else the last one (null when none ran yet)."""
    from src.controller import maturity_bulk_evaluator as bulk

    return bulk.get_latest_run()
