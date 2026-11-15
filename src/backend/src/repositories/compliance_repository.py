from typing import List, Optional, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from src.common.repository import CRUDBase
from src.common.timestamps import utc_now
from src.db_models.compliance import (
    ComplianceLlmCheckCacheDb,
    ComplianceLlmCheckUsageDb,
    CompliancePolicyDb,
    ComplianceResultDb,
    ComplianceRunDb,
)


class CompliancePolicyRepository(CRUDBase[CompliancePolicyDb, Dict[str, Any], Dict[str, Any]]):
    def __init__(self):
        super().__init__(CompliancePolicyDb)

    def list_all(self, db: Session) -> List[CompliancePolicyDb]:
        stmt = select(CompliancePolicyDb).order_by(CompliancePolicyDb.updated_at.desc())
        return list(db.execute(stmt).scalars().all())


class ComplianceRunRepository(CRUDBase[ComplianceRunDb, Dict[str, Any], Dict[str, Any]]):
    def __init__(self):
        super().__init__(ComplianceRunDb)

    def list_for_policy(self, db: Session, *, policy_id: str, limit: int = 50) -> List[ComplianceRunDb]:
        stmt = (
            select(ComplianceRunDb)
            .where(ComplianceRunDb.policy_id == policy_id)
            .order_by(ComplianceRunDb.started_at.desc())
            .limit(limit)
        )
        return list(db.execute(stmt).scalars().all())


class ComplianceResultRepository(CRUDBase[ComplianceResultDb, Dict[str, Any], Dict[str, Any]]):
    def __init__(self):
        super().__init__(ComplianceResultDb)

    def list_for_run(self, db: Session, *, run_id: str, only_failed: bool = False, limit: int = 1000) -> List[ComplianceResultDb]:
        stmt = select(ComplianceResultDb).where(ComplianceResultDb.run_id == run_id)
        if only_failed:
            stmt = stmt.where(ComplianceResultDb.passed == False)  # noqa: E712
        stmt = stmt.order_by(ComplianceResultDb.created_at.desc()).limit(limit)
        return list(db.execute(stmt).scalars().all())


class ComplianceLlmCheckCacheRepository(
    CRUDBase[ComplianceLlmCheckCacheDb, Dict[str, Any], Dict[str, Any]]
):
    """Cached LLM_CHECK verdicts (see ComplianceLlmCheckCacheDb)."""

    def __init__(self):
        super().__init__(ComplianceLlmCheckCacheDb)

    def get_verdict(self, db: Session, key: str) -> Optional[ComplianceLlmCheckCacheDb]:
        return db.get(ComplianceLlmCheckCacheDb, key)

    def put_verdict(self, db: Session, *, key: str, model: str, passed: bool, reason: str) -> None:
        """Store a verdict, in a savepoint: a row another run wrote first is kept.

        A row past its max age (asked again) is overwritten with the new verdict.
        Nothing is committed here; the run commits once when it completes.
        """
        existing = db.get(ComplianceLlmCheckCacheDb, key)
        if existing is not None:
            existing.model, existing.passed, existing.reason = model, passed, reason
            existing.created_at = utc_now()
            return
        try:
            with db.begin_nested():
                db.add(ComplianceLlmCheckCacheDb(
                    key=key, model=model, passed=passed, reason=reason,
                ))
        except IntegrityError:
            # Written by a concurrent run between the read and the insert
            pass


    def delete_older_than(self, db: Session, cutoff) -> int:
        """Delete the verdicts written before ``cutoff``, in a savepoint; how many."""
        with db.begin_nested():
            return (
                db.query(ComplianceLlmCheckCacheDb)
                .filter(ComplianceLlmCheckCacheDb.created_at < cutoff)
                .delete(synchronize_session=False)
            )


class ComplianceLlmCheckUsageRepository(
    CRUDBase[ComplianceLlmCheckUsageDb, Dict[str, Any], Dict[str, Any]]
):
    """LLM_CHECK model calls per user and day (see ComplianceLlmCheckUsageDb)."""

    def __init__(self):
        super().__init__(ComplianceLlmCheckUsageDb)

    @staticmethod
    def _calls(db: Session, username: str, day) -> Optional[int]:
        """The stored count (read from the database, not the session), or None."""
        model = ComplianceLlmCheckUsageDb
        return db.execute(
            select(model.calls).where(model.username == username, model.day == day)
        ).scalar_one_or_none()

    def used(self, db: Session, username: str, day) -> int:
        return int(self._calls(db, username, day) or 0)

    def reserve(self, db: Session, username: str, day, calls: int, limit: int) -> bool:
        """Add ``calls`` to the user's day if the total stays within ``limit``.

        One conditional UPDATE, so two runs of the same user can't both take the
        last calls; the day's first reservation inserts the row (in a savepoint;
        a row a concurrent run inserted first is updated instead). Not committed.
        """
        if calls > limit:
            return False
        model = ComplianceLlmCheckUsageDb
        for _ in range(2):
            result = db.execute(
                update(model)
                .where(model.username == username, model.day == day,
                       model.calls + calls <= limit)
                .values(calls=model.calls + calls)
                .execution_options(synchronize_session=False)
            )
            if result.rowcount:
                return True
            if self._calls(db, username, day) is not None:
                return False
            try:
                with db.begin_nested():
                    db.add(model(username=username, day=day, calls=calls))
                return True
            except IntegrityError:
                continue  # inserted by a concurrent run: update it
        return False

    def release(self, db: Session, username: str, day, calls: int) -> None:
        """Take back ``calls`` reserved but not made. Not committed."""
        model = ComplianceLlmCheckUsageDb
        db.execute(
            update(model)
            .where(model.username == username, model.day == day, model.calls >= calls)
            .values(calls=model.calls - calls)
            .execution_options(synchronize_session=False)
        )


compliance_policy_repo = CompliancePolicyRepository()
compliance_run_repo = ComplianceRunRepository()
compliance_result_repo = ComplianceResultRepository()
compliance_llm_check_cache_repo = ComplianceLlmCheckCacheRepository()
compliance_llm_check_usage_repo = ComplianceLlmCheckUsageRepository()


