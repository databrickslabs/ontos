from datetime import datetime
from typing import List, Optional, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.common.repository import CRUDBase
from src.db_models.compliance import (
    ComplianceLlmCheckCacheDb,
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
            existing.created_at = datetime.utcnow()
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


compliance_policy_repo = CompliancePolicyRepository()
compliance_run_repo = ComplianceRunRepository()
compliance_result_repo = ComplianceResultRepository()
compliance_llm_check_cache_repo = ComplianceLlmCheckCacheRepository()


