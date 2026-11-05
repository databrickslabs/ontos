from sqlalchemy import JSON, TIMESTAMP, Column, PrimaryKeyConstraint, String
from sqlalchemy.sql import func

from src.common.database import Base


class SchedulerClaimDb(Base):
    """One run of a scheduled task, claimed by the app instance that runs it (#941).

    The primary key ``(task_key, slot)`` makes the claim the exactly-once guard
    across app instances: each instance inserts the row with ``ON CONFLICT DO
    NOTHING`` and only the one whose insert succeeds runs the slot.

    ``task_key`` is ``workflow:<workflow id>`` for a ``scheduled`` workflow (later
    sweeps use their own keys); ``slot`` is the scheduled time in UTC. ``outcome``
    records the result: ``status``, ``coalesced_slots`` (how many due slots the run
    stands for; more than 1 after missed runs) and, once the run started, the
    execution id, also kept in ``execution_id``.
    """
    __tablename__ = "scheduler_claims"
    __table_args__ = (PrimaryKeyConstraint('task_key', 'slot', name='pk_scheduler_claims'),)

    task_key = Column(String(255), nullable=False)
    slot = Column(TIMESTAMP(timezone=True), nullable=False)
    claimed_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    claimed_by = Column(String(255), nullable=True)
    execution_id = Column(String, nullable=True)
    outcome = Column(JSON, nullable=True)

    def __repr__(self):
        return f"<SchedulerClaimDb(task_key='{self.task_key}', slot='{self.slot}')>"
