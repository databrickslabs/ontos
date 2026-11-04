"""API routes for certification levels management."""
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from src.common.dependencies import AuditCurrentUserDep, AuditManagerDep, DBSessionDep
from src.common.authorization import PermissionChecker
from src.common.features import FeatureAccessLevel
from src.controller.certified_deprecation_guard import (
    GateExemptionNotFoundError,
    guard_exemptions,
    save_guard_exemptions,
)
from src.models.process_workflows import GateExemptions
from src.models.certification_levels import (
    CertificationLevelCreate,
    CertificationLevelRead,
    CertificationLevelUpdate,
    CertificationLevelReorder,
)
from src.repositories.certification_levels_repository import certification_levels_repo
from src.common.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["Certification Levels"])

SETTINGS_FEATURE_ID = "settings-certification-levels"


@router.get(
    "/certification-levels",
    response_model=List[CertificationLevelRead],
)
async def list_certification_levels(db: DBSessionDep):
    """List all certification levels, ordered by level_order."""
    return certification_levels_repo.get_all_ordered(db)


@router.post(
    "/certification-levels",
    response_model=CertificationLevelRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_certification_level(
    body: CertificationLevelCreate,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(SETTINGS_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Create a new certification level. Admin only."""
    existing = certification_levels_repo.get_by_order(db, body.level_order)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A certification level with order {body.level_order} already exists.",
        )
    try:
        level = certification_levels_repo.create(
            db,
            name=body.name,
            level_order=body.level_order,
            description=body.description,
            icon=body.icon,
            color=body.color,
        )
        db.commit()
        return level
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating certification level: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create certification level")


@router.put(
    "/certification-levels/reorder",
    response_model=List[CertificationLevelRead],
)
async def reorder_certification_levels(
    body: CertificationLevelReorder,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(SETTINGS_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Bulk reorder certification levels. Admin only."""
    order_map = {item["id"]: item["level_order"] for item in body.levels}
    try:
        result = certification_levels_repo.reorder(db, order_map=order_map)
        db.commit()
        return result
    except Exception as e:
        db.rollback()
        logger.error(f"Error reordering certification levels: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to reorder certification levels")


@router.put(
    "/certification-levels/{level_id}",
    response_model=CertificationLevelRead,
)
async def update_certification_level(
    level_id: UUID,
    body: CertificationLevelUpdate,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(SETTINGS_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Update a certification level. Admin only."""
    db_obj = certification_levels_repo.get_by_id(db, level_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Certification level not found")

    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        return db_obj

    if "level_order" in update_data:
        existing = certification_levels_repo.get_by_order(db, update_data["level_order"])
        if existing and existing.id != level_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Order {update_data['level_order']} is already taken.",
            )

    try:
        updated = certification_levels_repo.update(db, db_obj=db_obj, update_data=update_data)
        db.commit()
        return updated
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating certification level: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update certification level")


@router.delete(
    "/certification-levels/{level_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_certification_level(
    level_id: UUID,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(SETTINGS_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Delete a certification level. Blocked if entities reference it."""
    db_obj = certification_levels_repo.get_by_id(db, level_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Certification level not found")

    ref_count = certification_levels_repo.count_entities_using_level(db, db_obj.level_order)
    if ref_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete: {ref_count} entities are certified at this level.",
        )

    try:
        certification_levels_repo.delete(db, db_obj=db_obj)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting certification level: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete certification level")


@router.get(
    "/certified-deprecation-guard",
    response_model=GateExemptions,
)
async def get_certified_deprecation_guard(
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(SETTINGS_FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Where the certified deprecation guard is switched off (domains, products, contracts).

    The guard refuses a direct deprecation of a certified product or contract;
    for the entities listed here it lets it through, and audits each skip.
    """
    return guard_exemptions(db)


@router.put(
    "/certified-deprecation-guard",
    response_model=GateExemptions,
)
async def update_certified_deprecation_guard(
    body: GateExemptions,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    _: bool = Depends(PermissionChecker(SETTINGS_FEATURE_ID, FeatureAccessLevel.ADMIN)),
):
    """Switch the certified deprecation guard off for domains, products and contracts.

    Needs Admin on certification levels: it lifts a governance control.
    Every listed entity must exist (``gate_exemption_not_found`` otherwise).
    """
    try:
        saved = save_guard_exemptions(db, body)
    except GateExemptionNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else 'anonymous',
        ip_address=request.client.host if request.client else None,
        feature=SETTINGS_FEATURE_ID,
        action='UPDATE_CERTIFIED_DEPRECATION_GUARD',
        success=True,
        details={'disabled_for': saved.model_dump()},
    )
    return saved


def register_routes(app):
    app.include_router(router)
    logger.info("Certification levels routes registered")
