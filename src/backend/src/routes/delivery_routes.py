"""The delivery outbox on Settings > Delivery Modes: list it, deliver an entity again (#1688)."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from src.common.authorization import PermissionChecker
from src.common.dependencies import AuditCurrentUserDep, AuditManagerDep, DBSessionDep
from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger
from src.controller import delivery_outbox_manager as outbox
from src.controller.delivery_outbox_manager import (
    DeliveryEntityNotFoundError,
    DeliveryEntityTypeUnsupportedError,
    DeliveryNoActiveModeError,
    delivery_outbox_manager,
)
from src.models.delivery_outbox import DeliveryOutboxList, RedeliverResult

logger = get_logger(__name__)

router = APIRouter(prefix="/api/delivery", tags=["Delivery"])
# The delivery modes' settings page: an admin feature
FEATURE_ID = "settings-delivery"

_STATUS_OF_ERROR = {
    DeliveryEntityTypeUnsupportedError: status.HTTP_400_BAD_REQUEST,
    DeliveryEntityNotFoundError: status.HTTP_404_NOT_FOUND,
    DeliveryNoActiveModeError: status.HTTP_409_CONFLICT,
}


@router.get(
    "/outbox",
    response_model=DeliveryOutboxList,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
def list_delivery_outbox(
    db: DBSessionDep,
    statuses: Optional[List[str]] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
):
    """The changes still to deliver (``pending``) and those past their attempts
    (``failed``), unless ``status`` asks for others; the most recent first."""
    return delivery_outbox_manager.list_rows(db, statuses or outbox.OPEN_STATUSES, limit=limit)


@router.post(
    "/{entity_type}/{entity_id}/redeliver",
    response_model=RedeliverResult,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def redeliver_entity(
    entity_type: str,
    entity_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
):
    """Deliver an entity again through the active delivery modes, now; what isn't
    delivered stays in the outbox, which retries it."""
    success = False
    details = {"entity_type": entity_type, "entity_id": entity_id}
    try:
        row_ids = delivery_outbox_manager.redeliver(
            db, entity_type, entity_id, user=current_user.username)
        bind = db.get_bind()
        rows = outbox.attempt_all(lambda: Session(bind=bind, expire_on_commit=False), row_ids)
        result = RedeliverResult(
            entity_type=entity_type, entity_id=entity_id,
            delivery=outbox.outcome_of(rows), rows=rows,
        )
        success = True
        details["delivery"] = result.delivery.status if result.delivery else None
        return result
    except tuple(_STATUS_OF_ERROR) as e:
        details["exception"] = {"type": type(e).__name__, "code": e.code}
        raise HTTPException(status_code=_STATUS_OF_ERROR[type(e)], detail=str(e)) from e
    finally:
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="REDELIVER", success=success, details=details,
        )


def register_routes(app):
    app.include_router(router)
    logger.info("Delivery outbox routes registered with prefix /api/delivery")
