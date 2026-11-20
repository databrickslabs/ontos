from itertools import islice
from typing import List, Optional, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import select

from src.common.repository import CRUDBase
from src.db_models.compliance import CompliancePolicyDb, ComplianceRunDb, ComplianceResultDb


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
        if not only_failed:
            stmt = stmt.order_by(ComplianceResultDb.created_at.desc()).limit(limit)
            return list(db.execute(stmt).scalars().all())
        from src.common.uc_table_enrichment import result_not_evaluated

        # A result not evaluated (a field the rule reads could not be loaded) is
        # stored as not passed, but it is not a failure; its details are parsed
        stmt = stmt.where(ComplianceResultDb.passed == False)  # noqa: E712
        stmt = stmt.order_by(ComplianceResultDb.created_at.desc())
        failed = (r for r in db.execute(stmt).scalars() if not result_not_evaluated(r.details_json))
        return list(islice(failed, limit))

    def not_evaluated_counts(self, db: Session, run_ids: List[str]) -> Dict[str, int]:
        """Results not evaluated, per run (runs without any are left out)."""
        from src.common.uc_table_enrichment import result_not_evaluated

        if not run_ids:
            return {}
        model = ComplianceResultDb
        # Not-evaluated details start with their code; action outcomes ('{"actions"...')
        # are not read. Each candidate is then parsed.
        rows = db.execute(
            select(model.run_id, model.details_json).where(
                model.run_id.in_(run_ids), model.passed == False,  # noqa: E712
                model.details_json.like('{"code": %'),
            )
        )
        counts: Dict[str, int] = {}
        for run_id, details in rows:
            if result_not_evaluated(details):
                counts[run_id] = counts.get(run_id, 0) + 1
        return counts


compliance_policy_repo = CompliancePolicyRepository()
compliance_run_repo = ComplianceRunRepository()
compliance_result_repo = ComplianceResultRepository()


