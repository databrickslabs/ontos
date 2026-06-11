"""API routes for maturity levels management and evaluation."""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from src.common.dependencies import DBSessionDep
from src.common.authorization import PermissionChecker
from src.common.features import FeatureAccessLevel
from src.models.maturity import (
    MaturityLevelCreate,
    MaturityLevelRead,
    MaturityLevelUpdate,
    MaturityLevelReorder,
    MaturityGateCreate,
    MaturityGateRead,
    MaturityReport,
    MaturitySnapshotRead,
)
from src.repositories.maturity_repository import maturity_repo
from src.common.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["Maturity Levels"])
SETTINGS_FEATURE_ID = "settings"
DP_FEATURE_ID = "data-products"
DC_FEATURE_ID = "data-contracts"


# ---------------------------------------------------------------------------
# Helper: map DB gate to read model with policy name
# ---------------------------------------------------------------------------

def _gate_to_read(gate) -> MaturityGateRead:
    policy_name = None
    policy_rule = None
    if gate.compliance_policy:
        policy_name = gate.compliance_policy.name
        policy_rule = gate.compliance_policy.rule
    return MaturityGateRead(
        id=gate.id,
        maturity_level_id=gate.maturity_level_id,
        compliance_policy_id=gate.compliance_policy_id,
        compliance_policy_name=policy_name,
        compliance_policy_rule=policy_rule,
        required=gate.required,
        display_order=gate.display_order,
        created_at=gate.created_at,
    )


def _level_to_read(level) -> MaturityLevelRead:
    return MaturityLevelRead(
        id=level.id,
        level_order=level.level_order,
        name=level.name,
        description=level.description,
        icon=level.icon,
        color=level.color,
        entity_type=level.entity_type,
        gates=[_gate_to_read(g) for g in (level.gates or [])],
        created_at=level.created_at,
        updated_at=level.updated_at,
    )


# ===================================================================
# Admin CRUD for Maturity Levels
# ===================================================================

@router.get("/maturity-levels", response_model=List[MaturityLevelRead])
async def list_maturity_levels(
    db: DBSessionDep,
    entity_type: Optional[str] = None,
):
    """List all maturity levels, optionally filtered by entity_type."""
    levels = maturity_repo.get_all_ordered(db, entity_type=entity_type)
    return [_level_to_read(l) for l in levels]


@router.post(
    "/maturity-levels",
    response_model=MaturityLevelRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_maturity_level(
    body: MaturityLevelCreate,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(SETTINGS_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Create a new maturity level. Admin only."""
    existing = maturity_repo.get_by_order(db, body.level_order, body.entity_type)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A maturity level with order {body.level_order} already exists for entity_type '{body.entity_type}'.",
        )
    try:
        level = maturity_repo.create(
            db,
            name=body.name,
            level_order=body.level_order,
            entity_type=body.entity_type,
            description=body.description,
            icon=body.icon,
            color=body.color,
        )
        db.commit()
        db.refresh(level)
        return _level_to_read(level)
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating maturity level: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create maturity level")


@router.put("/maturity-levels/reorder", response_model=List[MaturityLevelRead])
async def reorder_maturity_levels(
    body: MaturityLevelReorder,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(SETTINGS_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Bulk reorder maturity levels. Admin only."""
    order_map = {item["id"]: item["level_order"] for item in body.levels}
    try:
        result = maturity_repo.reorder(db, order_map=order_map)
        db.commit()
        return [_level_to_read(l) for l in result]
    except Exception as e:
        db.rollback()
        logger.error(f"Error reordering maturity levels: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to reorder maturity levels")


@router.put("/maturity-levels/{level_id}", response_model=MaturityLevelRead)
async def update_maturity_level(
    level_id: UUID,
    body: MaturityLevelUpdate,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(SETTINGS_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Update a maturity level. Admin only."""
    db_obj = maturity_repo.get_by_id(db, level_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Maturity level not found")

    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        return _level_to_read(db_obj)

    if "level_order" in update_data:
        et = update_data.get("entity_type", db_obj.entity_type)
        existing = maturity_repo.get_by_order(db, update_data["level_order"], et)
        if existing and existing.id != level_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Order {update_data['level_order']} is already taken for entity_type '{et}'.",
            )

    try:
        updated = maturity_repo.update(db, db_obj=db_obj, update_data=update_data)
        db.commit()
        db.refresh(updated)
        return _level_to_read(updated)
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating maturity level: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update maturity level")


@router.delete("/maturity-levels/{level_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_maturity_level(
    level_id: UUID,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(SETTINGS_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Delete a maturity level. Blocked if snapshots reference it."""
    db_obj = maturity_repo.get_by_id(db, level_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Maturity level not found")

    ref_count = maturity_repo.count_snapshots_for_level(db, db_obj.level_order)
    if ref_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete: {ref_count} snapshot(s) reference level order {db_obj.level_order}.",
        )

    try:
        maturity_repo.delete(db, db_obj=db_obj)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting maturity level: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete maturity level")


# ===================================================================
# Gate Management
# ===================================================================

@router.post(
    "/maturity-levels/{level_id}/gates",
    response_model=MaturityGateRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_gate(
    level_id: UUID,
    body: MaturityGateCreate,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(SETTINGS_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Add a compliance policy gate to a maturity level. Admin only."""
    level = maturity_repo.get_by_id(db, level_id)
    if not level:
        raise HTTPException(status_code=404, detail="Maturity level not found")

    from src.db_models.compliance import CompliancePolicyDb
    policy = db.get(CompliancePolicyDb, body.compliance_policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Compliance policy not found")

    try:
        gate = maturity_repo.add_gate(
            db,
            maturity_level_id=level_id,
            compliance_policy_id=body.compliance_policy_id,
            required=body.required,
            display_order=body.display_order,
        )
        db.commit()
        db.refresh(gate)
        return _gate_to_read(gate)
    except Exception as e:
        db.rollback()
        logger.error(f"Error adding gate: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to add gate")


@router.delete(
    "/maturity-levels/{level_id}/gates/{gate_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_gate(
    level_id: UUID,
    gate_id: UUID,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(SETTINGS_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Remove a gate from a maturity level. Admin only."""
    gate = maturity_repo.get_gate_by_id(db, gate_id)
    if not gate or gate.maturity_level_id != level_id:
        raise HTTPException(status_code=404, detail="Gate not found on this level")

    try:
        maturity_repo.remove_gate(db, db_obj=gate)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Error removing gate: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to remove gate")


# ===================================================================
# Evaluation Endpoints
# ===================================================================

def _get_evaluator(request: Request):
    from src.controller.maturity_evaluator import MaturityEvaluator
    evaluator = getattr(request.app.state, "maturity_evaluator", None)
    if not evaluator:
        evaluator = MaturityEvaluator()
    return evaluator


@router.get(
    "/data-products/{product_id}/maturity",
    response_model=MaturityReport,
    dependencies=[Depends(PermissionChecker(DP_FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
def get_product_maturity(product_id: str, db: DBSessionDep, request: Request):
    """Get current maturity assessment for a data product."""
    evaluator = _get_evaluator(request)
    report = evaluator.evaluate(db, entity_type="DataProduct", entity_id=product_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Data product {product_id} not found")
    return report


@router.post(
    "/data-products/{product_id}/maturity/evaluate",
    response_model=MaturityReport,
    dependencies=[Depends(PermissionChecker(DP_FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
def evaluate_product_maturity(product_id: str, db: DBSessionDep, request: Request):
    """Force re-evaluate maturity for a data product."""
    evaluator = _get_evaluator(request)
    report = evaluator.evaluate(db, entity_type="DataProduct", entity_id=product_id, persist=True)
    if not report:
        raise HTTPException(status_code=404, detail=f"Data product {product_id} not found")
    return report


@router.get(
    "/data-products/{product_id}/maturity/history",
    response_model=List[MaturitySnapshotRead],
    dependencies=[Depends(PermissionChecker(DP_FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
def get_product_maturity_history(product_id: str, db: DBSessionDep, limit: int = 50):
    """Get maturity evaluation history for a data product."""
    return maturity_repo.list_snapshots(db, entity_type="DataProduct", entity_id=product_id, limit=limit)


@router.get(
    "/data-contracts/{contract_id}/maturity",
    response_model=MaturityReport,
    dependencies=[Depends(PermissionChecker(DC_FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
def get_contract_maturity(contract_id: str, db: DBSessionDep, request: Request):
    """Get current maturity assessment for a data contract."""
    evaluator = _get_evaluator(request)
    report = evaluator.evaluate(db, entity_type="DataContract", entity_id=contract_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Data contract {contract_id} not found")
    return report


@router.post(
    "/data-contracts/{contract_id}/maturity/evaluate",
    response_model=MaturityReport,
    dependencies=[Depends(PermissionChecker(DC_FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
def evaluate_contract_maturity(contract_id: str, db: DBSessionDep, request: Request):
    """Force re-evaluate maturity for a data contract."""
    evaluator = _get_evaluator(request)
    report = evaluator.evaluate(db, entity_type="DataContract", entity_id=contract_id, persist=True)
    if not report:
        raise HTTPException(status_code=404, detail=f"Data contract {contract_id} not found")
    return report


@router.get(
    "/data-contracts/{contract_id}/maturity/history",
    response_model=List[MaturitySnapshotRead],
    dependencies=[Depends(PermissionChecker(DC_FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
def get_contract_maturity_history(contract_id: str, db: DBSessionDep, limit: int = 50):
    """Get maturity evaluation history for a data contract."""
    return maturity_repo.list_snapshots(db, entity_type="DataContract", entity_id=contract_id, limit=limit)


# ===================================================================
# Registration
# ===================================================================

def register_routes(app):
    app.include_router(router)
    logger.info("Maturity routes registered")
