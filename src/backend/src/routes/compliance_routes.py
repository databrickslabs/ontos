from typing import Optional

from fastapi import APIRouter, FastAPI, HTTPException, Depends, Body, Query, Request

from src.common.dependencies import DBSessionDep, AuditManagerDep, AuditCurrentUserDep
from src.common.features import FeatureAccessLevel
from src.common.authorization import PermissionChecker
from src.controller.compliance_manager import ComplianceManager
from src.models.compliance import (
    CompliancePolicy,
    CompliancePolicyCreate,
    ComplianceRun,
    ComplianceResult,
    ComplianceRunRequest,
    ComplianceResultsResponse,
)
from src.db_models.compliance import CompliancePolicyDb, ComplianceRunDb, ComplianceResultDb
from src.common.compliance_dsl import evaluate_rule_on_object as eval_dsl

from src.common.logging import get_logger
logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["Compliance"])
manager = ComplianceManager()

FEATURE_ID = 'compliance'


# DEPRECATED: Demo data loading has been moved to SQL-based approach.
# Demo data is now loaded via POST /api/settings/demo-data/load?preset=<retail|hls|fsi|mfg|auto>.
# Each preset is a self-contained file: src/backend/src/data/demo_data_{preset}.sql.


@router.get("/compliance/policies")
async def get_policies(
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Get all compliance policies with stats and scores."""
    return manager.get_policies_with_stats(db)


@router.get("/compliance/policies/{policy_id}")
async def get_policy(
    policy_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Get a specific compliance policy with examples."""
    policy = manager.get_policy_with_examples(db, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    return policy


@router.post("/compliance/policies")
async def create_policy(
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    policy: CompliancePolicyCreate = Body(...),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    created = manager.create_policy(
        db, 
        policy, 
        current_user=current_user.username if current_user else None
    )
    
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else 'unknown',
        ip_address=request.client.host if request.client else None,
        feature=FEATURE_ID,
        action='CREATE_POLICY',
        success=True,
        details={'policy_id': created.id, 'policy_name': created.name}
    )
    
    return {
        'id': created.id,
        'name': created.name,
        'description': created.description,
        'rule': created.rule,
        'created_at': created.created_at,
        'updated_at': created.updated_at,
        'is_active': created.is_active,
        'severity': created.severity,
        'category': created.category,
        'compliance': 0.0,
        'history': [],
    }


@router.put("/compliance/policies/{policy_id}")
async def update_policy(
    policy_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    policy: CompliancePolicy = Body(...),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    updated = manager.update_policy(
        db, 
        policy_id, 
        policy,
        current_user=current_user.username if current_user else None
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Policy not found")
    
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else 'unknown',
        ip_address=request.client.host if request.client else None,
        feature=FEATURE_ID,
        action='UPDATE_POLICY',
        success=True,
        details={'policy_id': policy_id, 'policy_name': updated.name}
    )
    
    return {
        'id': updated.id,
        'name': updated.name,
        'description': updated.description,
        'rule': updated.rule,
        'created_at': updated.created_at,
        'updated_at': updated.updated_at,
        'is_active': updated.is_active,
        'severity': updated.severity,
        'category': updated.category,
    }


@router.delete("/compliance/policies/{policy_id}")
async def delete_policy(
    policy_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    # Get policy name before deleting for audit
    policy = manager.get_policy(db, policy_id)
    policy_name = policy.name if policy else 'unknown'
    
    ok = manager.delete_policy(
        db, 
        policy_id,
        current_user=current_user.username if current_user else None
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Policy not found")
    
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else 'unknown',
        ip_address=request.client.host if request.client else None,
        feature=FEATURE_ID,
        action='DELETE_POLICY',
        success=True,
        details={'policy_id': policy_id, 'policy_name': policy_name}
    )
    
    return {"status": "success"}


@router.post("/compliance/policies/{policy_id}/runs")
async def run_policy(
    policy_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    payload: ComplianceRunRequest = Body(default=ComplianceRunRequest()),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    policy = manager.get_policy(db, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    # For now, implement inline only; async can be backed by Databricks job later
    run = manager.run_policy_inline(
        db, 
        policy=policy, 
        limit=payload.limit,
        current_user=current_user.username if current_user else None
    )
    
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else 'unknown',
        ip_address=request.client.host if request.client else None,
        feature=FEATURE_ID,
        action='RUN_POLICY',
        success=True,
        details={'policy_id': policy_id, 'policy_name': policy.name, 'run_id': run.id}
    )
    
    return {
        'id': run.id,
        'policy_id': run.policy_id,
        'status': run.status,
        'started_at': run.started_at,
        'finished_at': run.finished_at,
        'success_count': run.success_count,
        'failure_count': run.failure_count,
        'score': run.score,
        'error_message': run.error_message,
    }


@router.get("/compliance/policies/{policy_id}/runs")
async def list_runs(
    policy_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    policy = manager.get_policy(db, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    runs = manager.list_runs(db, policy_id=policy_id, limit=50)
    return [
        {
            'id': r.id,
            'policy_id': r.policy_id,
            'status': r.status,
            'started_at': r.started_at,
            'finished_at': r.finished_at,
            'success_count': r.success_count,
            'failure_count': r.failure_count,
            'score': r.score,
            'error_message': r.error_message,
        } for r in runs
    ]


@router.get("/compliance/runs/{run_id}/results")
async def get_run_results(
    run_id: str,
    db: DBSessionDep,
    only_failed: Optional[bool] = Query(default=False),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    run = db.get(ComplianceRunDb, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    results = manager.list_results(db, run_id=run_id, only_failed=bool(only_failed), limit=2000)
    return {
        'run': {
            'id': run.id,
            'policy_id': run.policy_id,
            'status': run.status,
            'started_at': run.started_at,
            'finished_at': run.finished_at,
            'success_count': run.success_count,
            'failure_count': run.failure_count,
            'score': run.score,
            'error_message': run.error_message,
        },
        'results': [
            {
                'id': r.id,
                'run_id': r.run_id,
                'object_type': r.object_type,
                'object_id': r.object_id,
                'object_name': r.object_name,
                'passed': r.passed,
                'message': r.message,
                'details_json': r.details_json,
                'created_at': r.created_at,
            } for r in results
        ],
        'only_failed': bool(only_failed),
        'total': len(results),
    }


@router.get("/compliance/stats")
async def get_stats(
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    return manager.get_compliance_stats(db)


@router.get("/compliance/trend")
async def get_compliance_trend(
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    return manager.get_compliance_trend(db)


def register_routes(app: FastAPI) -> None:
    app.include_router(router)


@router.post("/compliance/validate-inline")
async def validate_inline(
    body: dict = Body(...),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Validate a single object against a DSL rule inline (no DB writes)."""
    try:
        rule = body.get('rule') or ''
        obj = body.get('object') or {}
        passed, msg = eval_dsl(rule, obj)
        return {"passed": passed, "message": msg}
    except Exception as e:
        logger.error("DSL evaluation failed", exc_info=True)
        raise HTTPException(status_code=400, detail="DSL evaluation failed")
