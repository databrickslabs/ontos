"""Rows of the delivery outbox (``delivery_outbox``): queue, claim, record, list, prune."""
import uuid
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.db_models.delivery_outbox import DeliveryOutboxDb

PENDING = 'pending'
DELIVERED = 'delivered'
FAILED = 'failed'
OPEN_STATUSES = (PENDING, FAILED)


class DeliveryOutboxRepository:
    """No commits here: the caller's transaction decides (the change's, or the attempt's)."""

    model = DeliveryOutboxDb

    def add(
        self,
        db: Session,
        *,
        entity_type: str,
        entity_id: str,
        change_type: str,
        mode: str,
        queued_by: Optional[str],
        next_attempt_at: datetime,
    ) -> DeliveryOutboxDb:
        """Add a pending row to ``db``'s transaction (flushed, not committed)."""
        row = DeliveryOutboxDb(
            id=str(uuid.uuid4()), entity_type=entity_type, entity_id=entity_id,
            change_type=change_type, mode=mode, status=PENDING, attempts=0,
            next_attempt_at=next_attempt_at, queued_by=queued_by,
        )
        db.add(row)
        db.flush()
        return row

    def get(self, db: Session, row_id: str) -> Optional[DeliveryOutboxDb]:
        return db.get(DeliveryOutboxDb, row_id)

    def claim(self, db: Session, row_id: str) -> Optional[DeliveryOutboxDb]:
        """Lock the pending row ``row_id`` for an attempt, or None when it isn't
        pending or another session holds it (``FOR UPDATE SKIP LOCKED`` on Postgres)."""
        return db.query(DeliveryOutboxDb).filter(
            DeliveryOutboxDb.id == row_id, DeliveryOutboxDb.status == PENDING,
        ).with_for_update(skip_locked=True).one_or_none()

    def claim_next_due(self, db: Session, now: datetime) -> Optional[DeliveryOutboxDb]:
        """Lock the pending row due the longest, skipping the ones other sessions hold."""
        return db.query(DeliveryOutboxDb).filter(
            DeliveryOutboxDb.status == PENDING, DeliveryOutboxDb.next_attempt_at <= now,
        ).order_by(
            DeliveryOutboxDb.next_attempt_at, DeliveryOutboxDb.id,
        ).limit(1).with_for_update(skip_locked=True).one_or_none()

    def next_due_at(self, db: Session) -> Optional[datetime]:
        """When the next pending row is due (None: no pending row)."""
        return db.query(func.min(DeliveryOutboxDb.next_attempt_at)).filter(
            DeliveryOutboxDb.status == PENDING,
        ).scalar()

    def for_entity(
        self, db: Session, entity_type: str, entity_id: str,
        statuses: Iterable[str] = OPEN_STATUSES, lock: bool = False,
    ) -> List[DeliveryOutboxDb]:
        """The entity's rows with one of ``statuses``. With ``lock`` they are locked
        (``FOR UPDATE SKIP LOCKED`` on Postgres): the rows another session holds are left out."""
        query = db.query(DeliveryOutboxDb).filter(
            DeliveryOutboxDb.entity_type == entity_type,
            DeliveryOutboxDb.entity_id == entity_id,
            DeliveryOutboxDb.status.in_(list(statuses)),
        ).order_by(DeliveryOutboxDb.created_at, DeliveryOutboxDb.id)
        if lock:
            query = query.with_for_update(skip_locked=True)
        return query.all()

    def fail_attempt(
        self, db: Session, row_id: str, *, now: datetime, code: str, max_attempts: int,
        retry_after: Any,
    ) -> bool:
        """Count a failed attempt on a row whose delivery broke before an outcome was
        recorded: pending again after ``retry_after(attempts)``, or failed at
        ``max_attempts``. False when the row is gone, no longer pending or held elsewhere."""
        row = self.claim(db, row_id)
        if row is None:
            return False
        attempts = (row.attempts or 0) + 1
        if attempts >= max_attempts:
            status, next_attempt = FAILED, None
        else:
            status, next_attempt = PENDING, now + retry_after(attempts)
        self.record(row, status=status, now=now, code=code, params={'mode': row.mode},
                    next_attempt_at=next_attempt)
        return True

    def by_ids(self, db: Session, row_ids: Iterable[str]) -> List[DeliveryOutboxDb]:
        ids = list(row_ids)
        if not ids:
            return []
        rows = db.query(DeliveryOutboxDb).filter(DeliveryOutboxDb.id.in_(ids)).all()
        order = {row_id: index for index, row_id in enumerate(ids)}
        return sorted(rows, key=lambda row: order[row.id])

    def list(
        self, db: Session, statuses: Iterable[str] = OPEN_STATUSES, limit: int = 100,
    ) -> List[DeliveryOutboxDb]:
        """Rows with one of ``statuses``, the most recently changed first."""
        return db.query(DeliveryOutboxDb).filter(
            DeliveryOutboxDb.status.in_(list(statuses)),
        ).order_by(
            DeliveryOutboxDb.updated_at.desc(), DeliveryOutboxDb.id,
        ).limit(limit).all()

    def count(self, db: Session, statuses: Iterable[str] = OPEN_STATUSES) -> Dict[str, int]:
        rows = db.query(DeliveryOutboxDb.status, func.count(DeliveryOutboxDb.id)).filter(
            DeliveryOutboxDb.status.in_(list(statuses)),
        ).group_by(DeliveryOutboxDb.status).all()
        return {status: count for status, count in rows}

    @staticmethod
    def record(
        row: DeliveryOutboxDb,
        *,
        status: str,
        now: datetime,
        code: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        next_attempt_at: Optional[datetime] = None,
        counted: bool = True,
    ) -> None:
        """Set the outcome of an attempt on a claimed row (the caller commits)."""
        if counted:
            row.attempts = (row.attempts or 0) + 1
            row.last_attempt_at = now
        row.status = status
        row.code = code
        row.params = params or None
        row.next_attempt_at = next_attempt_at
        row.delivered_at = now if status == DELIVERED else None
        row.updated_at = now

    def prune_delivered(self, db: Session, *, before: datetime) -> int:
        """Delete the rows delivered before ``before`` (the caller commits)."""
        return db.query(DeliveryOutboxDb).filter(
            DeliveryOutboxDb.status == DELIVERED, DeliveryOutboxDb.delivered_at < before,
        ).delete(synchronize_session=False)


delivery_outbox_repo = DeliveryOutboxRepository()
