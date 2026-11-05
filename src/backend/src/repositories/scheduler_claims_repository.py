"""Claims of scheduled runs (``scheduler_claims``): insert-once, then record the outcome."""
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from src.db_models.scheduler_claims import SchedulerClaimDb


class SchedulerClaimsRepository:
    """The exactly-once guard of the workflow scheduler (#941)."""

    model = SchedulerClaimDb

    def claim(
        self,
        db: Session,
        *,
        task_key: str,
        slot: datetime,
        claimed_by: str,
        outcome: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Insert the claim of ``(task_key, slot)`` and commit; False if it exists already.

        ``INSERT ... ON CONFLICT DO NOTHING`` on the primary key: of several app
        instances claiming the same slot, exactly one insert writes a row.
        """
        statement = self.claim_statement(
            db.get_bind().dialect.name, task_key=task_key, slot=slot,
            claimed_by=claimed_by, outcome=outcome,
        )
        result = db.execute(statement)
        db.commit()
        return result.rowcount == 1

    @staticmethod
    def claim_statement(
        dialect: str,
        *,
        task_key: str,
        slot: datetime,
        claimed_by: str,
        outcome: Optional[Dict[str, Any]] = None,
    ):
        """The claim's ``INSERT ... ON CONFLICT (task_key, slot) DO NOTHING`` for a dialect."""
        insert = sqlite_insert if dialect == 'sqlite' else pg_insert
        return insert(SchedulerClaimDb).values(
            task_key=task_key, slot=slot, claimed_by=claimed_by, outcome=outcome,
        ).on_conflict_do_nothing(index_elements=['task_key', 'slot'])

    def get(self, db: Session, *, task_key: str, slot: datetime) -> Optional[SchedulerClaimDb]:
        return db.get(SchedulerClaimDb, (task_key, slot))

    def latest_slot(self, db: Session, *, task_key: str) -> Optional[datetime]:
        """The most recent claimed slot of ``task_key``."""
        return db.query(func.max(SchedulerClaimDb.slot)).filter(
            SchedulerClaimDb.task_key == task_key
        ).scalar()

    def record_outcome(
        self,
        db: Session,
        *,
        task_key: str,
        slot: datetime,
        outcome: Dict[str, Any],
        execution_id: Optional[str] = None,
    ) -> None:
        """Store the outcome (and execution id) of a claimed slot and commit."""
        db.query(SchedulerClaimDb).filter(
            SchedulerClaimDb.task_key == task_key, SchedulerClaimDb.slot == slot,
        ).update({'outcome': outcome, 'execution_id': execution_id}, synchronize_session=False)
        db.commit()


scheduler_claims_repo = SchedulerClaimsRepository()
