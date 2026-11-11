"""Database access for metric view baselines (#1124)."""
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.common.repository import CRUDBase
from src.db_models.metric_view_baselines import MetricViewBaselineDb


class MetricViewBaselinesRepository(CRUDBase[MetricViewBaselineDb, Dict[str, Any], Dict[str, Any]]):
    def get_by_fqn(self, db: Session, fqn: str) -> Optional[MetricViewBaselineDb]:
        return db.query(self.model).filter(self.model.metric_view_fqn == fqn).first()

    def create_if_absent(
        self, db: Session, *, fqn: str, definition: Dict[str, Any], digest: str,
        checked_at: datetime, created_by: Optional[str],
    ) -> MetricViewBaselineDb:
        """Record a baseline unless the metric view has one, and return the row that's stored.

        In a savepoint, so a concurrent request that recorded it first (unique FQN)
        only drops this insert, not the caller's transaction.
        """
        try:
            with db.begin_nested():
                row = self.model(
                    metric_view_fqn=fqn, definition=definition, digest=digest,
                    drift_state='in_sync', observed_digest=digest, last_checked_at=checked_at,
                    created_by=created_by,
                )
                db.add(row)
                db.flush()
            return row
        except IntegrityError:
            existing = self.get_by_fqn(db, fqn)
            if existing is None:
                raise
            return existing

    def record_observation(
        self, db: Session, baseline: MetricViewBaselineDb, *, observed_digest: str,
        drift_state: str, checked_at: datetime,
    ) -> bool:
        """Store a check's result; True when ``observed_digest`` differs from the last one.

        A single conditional UPDATE, so of two requests that read the same new
        definition at once only one sees the change (and notifies it).
        """
        changed = db.query(self.model).filter(
            self.model.id == baseline.id,
            or_(self.model.observed_digest.is_(None),
                self.model.observed_digest != observed_digest),
        ).update({
            'observed_digest': observed_digest, 'drift_state': drift_state,
            'last_checked_at': checked_at,
        }, synchronize_session=False)
        if not changed:
            db.query(self.model).filter(self.model.id == baseline.id).update(
                {'drift_state': drift_state, 'last_checked_at': checked_at},
                synchronize_session=False,
            )
        db.flush()
        db.refresh(baseline)
        return bool(changed)

    def record_unknown(self, db: Session, baseline: MetricViewBaselineDb, *,
                       checked_at: datetime) -> None:
        """The definition couldn't be parsed: the state is unknown, the last observation kept."""
        baseline.drift_state = 'unknown'
        baseline.last_checked_at = checked_at
        db.flush()


metric_view_baselines_repo = MetricViewBaselinesRepository(MetricViewBaselineDb)
