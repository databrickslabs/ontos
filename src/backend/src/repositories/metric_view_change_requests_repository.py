"""Database access for metric view definition change requests (#1124 phase 3)."""
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from src.common.repository import CRUDBase
from src.db_models.metric_view_change_requests import MetricViewChangeRequestDb


class MetricViewChangeRequestsRepository(
    CRUDBase[MetricViewChangeRequestDb, Dict[str, Any], Dict[str, Any]]
):
    def get_for_asset(
        self, db: Session, asset_id: UUID, request_id: UUID,
    ) -> Optional[MetricViewChangeRequestDb]:
        return db.query(self.model).filter(
            self.model.id == request_id, self.model.asset_id == asset_id,
        ).first()

    def list_for_asset(self, db: Session, asset_id: UUID) -> List[MetricViewChangeRequestDb]:
        """The asset's requests, newest first."""
        return (
            db.query(self.model)
            .filter(self.model.asset_id == asset_id)
            .order_by(self.model.created_at.desc(), self.model.id.desc())
            .all()
        )

    def delivered_with_digest(
        self, db: Session, fqn: str, digest: str,
    ) -> Optional[MetricViewChangeRequestDb]:
        """The latest delivered request of ``fqn`` proposing ``digest``, not yet read back."""
        return (
            db.query(self.model)
            .filter(
                self.model.metric_view_fqn == fqn,
                self.model.status == 'delivered',
                self.model.proposed_digest == digest,
                self.model.applied_at.is_(None),
            )
            .order_by(self.model.delivered_at.desc())
            .first()
        )

    def set_status_if(
        self, db: Session, request: MetricViewChangeRequestDb, expected: str,
        values: Dict[str, Any],
    ) -> bool:
        """Update ``request`` only while its status is ``expected``; True when it was.

        One conditional UPDATE, so of two decisions arriving at once (a cancel
        and an approval) only one takes effect.
        """
        changed = db.query(self.model).filter(
            self.model.id == request.id, self.model.status == expected,
        ).update(values, synchronize_session=False)
        db.flush()
        db.refresh(request)
        return bool(changed)


metric_view_change_requests_repo = MetricViewChangeRequestsRepository(MetricViewChangeRequestDb)
