from __future__ import annotations
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from src.common.dependencies import DBSessionDep, CurrentUserDep, AuditManagerDep, AuditCurrentUserDep
from src.common.features import FeatureAccessLevel
from src.common.authorization import PermissionChecker
from src.common.logging import get_logger
from src.controller.costs_manager import CostsManager
from src.common.manager_dependencies import get_metadata_manager  # reuse style; provide a getter here
from src.models.costs import CostItem, CostItemCreate, CostItemUpdate, CostSummary

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["Costs"])

FEATURE_ID = "data-domains"  # align with metadata until dedicated feature is added


def get_costs_manager() -> CostsManager:
    return CostsManager()


@router.post("/entities/{entity_type}/{entity_id}/cost-items", response_model=CostItem, status_code=status.HTTP_201_CREATED)
async def create_cost_item(
    entity_type: str,
    entity_id: str,
    payload: CostItemCreate,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    manager: CostsManager = Depends(get_costs_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    success = False
    details = {
        "params": {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "cost_center": payload.cost_center,
            "amount_cents": payload.amount_cents,
            "currency": payload.currency
        }
    }

    try:
        if payload.entity_type != entity_type or payload.entity_id != entity_id:
            raise HTTPException(status_code=400, detail="Entity path does not match body")
        result = manager.create(db, data=payload, user_email=current_user.email)
        success = True
        details["cost_item_id"] = result.id
        return result
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        logger.exception("Failed creating cost item for %s/%s", entity_type, entity_id)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail="Failed to create cost item")
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="costs",
            action="CREATE",
            success=success,
            details=details
        )


@router.get("/entities/{entity_type}/{entity_id}/cost-items", response_model=List[CostItem])
async def list_cost_items(
    entity_type: str,
    entity_id: str,
    month: Optional[str] = Query(None, description="YYYY-MM to filter active recurring items"),
    db: DBSessionDep = None,
    manager: CostsManager = Depends(get_costs_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    month_date = None
    if month:
        try:
            month_date = datetime.strptime(month + "-01", "%Y-%m-%d").date()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid month format. Use YYYY-MM")
    return manager.list(db, entity_type=entity_type, entity_id=entity_id, month=month_date)


@router.get("/entities/{entity_type}/{entity_id}/cost-items/summary", response_model=CostSummary)
async def summarize_cost_items(
    entity_type: str,
    entity_id: str,
    month: str = Query(..., description="YYYY-MM month to summarize"),
    db: DBSessionDep = None,
    manager: CostsManager = Depends(get_costs_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    try:
        month_date = datetime.strptime(month + "-01", "%Y-%m-%d").date()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid month format. Use YYYY-MM")
    return manager.summarize(db, entity_type=entity_type, entity_id=entity_id, month=month_date)


@router.put("/cost-items/{id}", response_model=CostItem)
async def update_cost_item(
    id: str,
    payload: CostItemUpdate,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    manager: CostsManager = Depends(get_costs_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    success = False
    details = {
        "params": {
            "cost_item_id": id,
            "has_amount_update": payload.amount_cents is not None,
            "has_title_update": payload.title is not None
        }
    }

    try:
        updated = manager.update(db, id=id, data=payload, user_email=current_user.email)
        if not updated:
            raise HTTPException(status_code=404, detail="Cost item not found")
        success = True
        return updated
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        logger.exception("Failed updating cost item %s", id)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail="Failed to update cost item")
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="costs",
            action="UPDATE",
            success=success,
            details=details
        )


@router.delete("/cost-items/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cost_item(
    id: str,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    manager: CostsManager = Depends(get_costs_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    success = False
    details = {"params": {"cost_item_id": id}}

    try:
        ok = manager.delete(db, id=id, user_email=current_user.email)
        if not ok:
            raise HTTPException(status_code=404, detail="Cost item not found")
        success = True
        return
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        logger.exception("Failed deleting cost item %s", id)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail="Failed to delete cost item")
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="costs",
            action="DELETE",
            success=success,
            details=details
        )


def register_routes(app):
    app.include_router(router)
    logger.info("Costs routes registered with prefix /api")


