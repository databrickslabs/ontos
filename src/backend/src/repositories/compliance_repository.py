from itertools import islice
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import case, func, select

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

    def iter_for_run(
        self, db: Session, *, run_id: str, only_failed: bool = False,
    ) -> Iterator[ComplianceResultDb]:
        """A run's results, newest first, read in batches (the caller filters and
        pages them). ``only_failed``: failures only, without the not-evaluated ones."""
        from src.common.uc_table_enrichment import result_not_evaluated

        stmt = select(ComplianceResultDb).where(ComplianceResultDb.run_id == run_id)
        if only_failed:
            stmt = stmt.where(ComplianceResultDb.passed == False)  # noqa: E712
        stmt = stmt.order_by(ComplianceResultDb.created_at.desc(), ComplianceResultDb.id)
        for r in db.execute(stmt.execution_options(yield_per=500)).scalars():
            if only_failed and result_not_evaluated(r.details_json):
                continue
            yield r

    def count_for_run(self, db: Session, *, run_id: str, only_failed: bool = False) -> int:
        """How many results ``iter_for_run`` yields, all viewers' rows included."""
        stmt = select(func.count()).select_from(ComplianceResultDb).where(
            ComplianceResultDb.run_id == run_id,
        )
        if only_failed:
            stmt = stmt.where(ComplianceResultDb.passed == False)  # noqa: E712
        total = int(db.execute(stmt).scalar() or 0)
        if only_failed:
            total -= self.not_evaluated_counts(db, [run_id]).get(run_id, 0)
        return total

    def typed_result_rows(
        self, db: Session, run_ids: List[str], object_types: Sequence[str],
    ) -> List[Tuple[str, str, str, bool, bool]]:
        """``(run_id, object_type, object_id, passed, not_evaluated)`` of the runs'
        results on ``object_types``, without their messages."""
        from src.common.uc_table_enrichment import result_not_evaluated

        if not run_ids:
            return []
        model = ComplianceResultDb
        # Only a not-passed result whose details start with a code can be not evaluated
        maybe_code = case(
            ((model.passed == False) & model.details_json.like('{"code": %'),  # noqa: E712
             model.details_json),
            else_=None,
        )
        rows = db.execute(
            select(model.run_id, model.object_type, model.object_id, model.passed, maybe_code)
            .where(model.run_id.in_(run_ids), model.object_type.in_(list(object_types)))
        )
        return [
            (run_id, object_type, object_id, bool(passed), result_not_evaluated(details))
            for run_id, object_type, object_id, passed, details in rows
        ]

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


