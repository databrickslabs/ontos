"""
Repository for Generation Runs and Description Suggestions.
"""

from typing import Dict, List, Optional

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.db_models.metadata_generation import DescriptionSuggestionDb, MetadataGenerationRunDb

logger = get_logger(__name__)

ACTIVE_RUN_STATUSES = ('pending', 'running', 'ingesting')


class MetadataGenerationRunsRepository:

    def get(self, db: Session, run_id: str) -> Optional[MetadataGenerationRunDb]:
        return db.query(MetadataGenerationRunDb).filter(MetadataGenerationRunDb.id == run_id).first()

    def get_by_job_run_id(self, db: Session, job_run_id: str) -> Optional[MetadataGenerationRunDb]:
        return db.query(MetadataGenerationRunDb).filter(
            MetadataGenerationRunDb.job_run_id == job_run_id,
        ).first()

    def list_for_user(
        self, db: Session, user_id: str, *, limit: int = 50, skip: int = 0
    ) -> List[MetadataGenerationRunDb]:
        return (
            db.query(MetadataGenerationRunDb)
            .filter(MetadataGenerationRunDb.user_id == user_id)
            .order_by(desc(MetadataGenerationRunDb.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

    def list_all(self, db: Session, *, limit: int = 50, skip: int = 0) -> List[MetadataGenerationRunDb]:
        return (
            db.query(MetadataGenerationRunDb)
            .order_by(desc(MetadataGenerationRunDb.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

    def list_active(self, db: Session) -> List[MetadataGenerationRunDb]:
        return (
            db.query(MetadataGenerationRunDb)
            .filter(MetadataGenerationRunDb.status.in_(ACTIVE_RUN_STATUSES))
            .all()
        )

    def create(self, db: Session, *, user_id: str, **kwargs) -> MetadataGenerationRunDb:
        run = MetadataGenerationRunDb(user_id=user_id, status='pending', **kwargs)
        db.add(run)
        db.flush()
        db.refresh(run)
        return run

    def delete(self, db: Session, run: MetadataGenerationRunDb) -> None:
        db.delete(run)
        db.flush()


class DescriptionSuggestionsRepository:

    def list_for_run(
        self,
        db: Session,
        run_id: str,
        *,
        status: Optional[str] = None,
        limit: int = 1000,
        skip: int = 0,
    ) -> List[DescriptionSuggestionDb]:
        q = db.query(DescriptionSuggestionDb).filter(DescriptionSuggestionDb.run_id == run_id)
        if status:
            q = q.filter(DescriptionSuggestionDb.status == status)
        return (
            q.order_by(
                DescriptionSuggestionDb.table_fqn,
                # Table-level row (no column) first, then columns
                DescriptionSuggestionDb.column_name.isnot(None),
                DescriptionSuggestionDb.column_name,
            )
            .offset(skip)
            .limit(limit)
            .all()
        )

    def count_for_run(self, db: Session, run_id: str, *, status: Optional[str] = None) -> int:
        q = db.query(func.count(DescriptionSuggestionDb.id)).filter(DescriptionSuggestionDb.run_id == run_id)
        if status:
            q = q.filter(DescriptionSuggestionDb.status == status)
        return q.scalar() or 0

    def counts_by_status(self, db: Session, run_id: str) -> Dict[str, int]:
        rows = (
            db.query(DescriptionSuggestionDb.status, func.count(DescriptionSuggestionDb.id))
            .filter(DescriptionSuggestionDb.run_id == run_id)
            .group_by(DescriptionSuggestionDb.status)
            .all()
        )
        return {status: count for status, count in rows}

    def count_unsubmitted(self, db: Session, run_id: str) -> int:
        """Pending suggestions not (or no longer) in a review."""
        return (
            db.query(func.count(DescriptionSuggestionDb.id))
            .filter(
                DescriptionSuggestionDb.run_id == run_id,
                DescriptionSuggestionDb.status == 'pending',
                DescriptionSuggestionDb.review_request_id.is_(None),
            )
            .scalar()
        ) or 0

    def applicable_query(
        self, db: Session, run_id: str, *, statuses=('accepted',), review_request_id: Optional[str] = None,
    ):
        """Suggestions of ``statuses`` whose review was approved."""
        from src.db_models.data_asset_reviews import DataAssetReviewRequestDb

        approved = db.query(DataAssetReviewRequestDb.id).filter(DataAssetReviewRequestDb.status == 'approved')
        query = db.query(DescriptionSuggestionDb).filter(
            DescriptionSuggestionDb.run_id == run_id,
            DescriptionSuggestionDb.status.in_(statuses),
            DescriptionSuggestionDb.review_request_id.in_(approved),
        )
        if review_request_id:
            query = query.filter(DescriptionSuggestionDb.review_request_id == review_request_id)
        return query

    def count_applicable(self, db: Session, run_id: str) -> int:
        return self.applicable_query(db, run_id).count()

    def release_undecided(self, db: Session, review_request_id: str) -> int:
        """Take a closed review's undecided (pending) suggestions out of it."""
        return (
            db.query(DescriptionSuggestionDb)
            .filter(
                DescriptionSuggestionDb.review_request_id == review_request_id,
                DescriptionSuggestionDb.status == 'pending',
            )
            .update(
                {DescriptionSuggestionDb.review_request_id: None, DescriptionSuggestionDb.reviewed_asset_id: None},
                synchronize_session=False,
            )
        )

    def review_request_ids(self, db: Session, run_id: str) -> List[str]:
        """The reviews the run's suggestions are in, oldest suggestion first."""
        rows = (
            db.query(DescriptionSuggestionDb.review_request_id, func.min(DescriptionSuggestionDb.created_at))
            .filter(
                DescriptionSuggestionDb.run_id == run_id,
                DescriptionSuggestionDb.review_request_id.isnot(None),
            )
            .group_by(DescriptionSuggestionDb.review_request_id)
            .order_by(func.min(DescriptionSuggestionDb.created_at))
            .all()
        )
        return [review_id for review_id, _ in rows]

    def supersede_pending_for_targets(
        self, db: Session, *, run: MetadataGenerationRunDb, targets: List[tuple]
    ) -> int:
        """Mark not-yet-reviewed pending suggestions of *older* runs for the same targets as superseded.

        ``targets`` is a list of ``(table_fqn, column_name_or_None)``. Runs are
        ordered by creation, so a late ingest of an older run can't supersede
        a newer run's suggestions.
        """
        if not targets:
            return 0
        superseded = 0
        target_set = set(targets)
        candidates = (
            db.query(DescriptionSuggestionDb)
            .join(MetadataGenerationRunDb, MetadataGenerationRunDb.id == DescriptionSuggestionDb.run_id)
            .filter(
                DescriptionSuggestionDb.run_id != run.id,
                MetadataGenerationRunDb.created_at < run.created_at,
                DescriptionSuggestionDb.status == 'pending',
                DescriptionSuggestionDb.review_request_id.is_(None),
                DescriptionSuggestionDb.table_fqn.in_({t[0] for t in targets}),
            )
            .all()
        )
        for sug in candidates:
            if (sug.table_fqn, sug.column_name) in target_set:
                sug.status = 'superseded'
                superseded += 1
        db.flush()
        return superseded

    def targets_of_newer_runs(
        self, db: Session, *, run: MetadataGenerationRunDb, table_fqns: set
    ) -> set:
        """``(table_fqn, column_name)`` that runs created after ``run`` already have suggestions for."""
        if not table_fqns:
            return set()
        rows = (
            db.query(DescriptionSuggestionDb.table_fqn, DescriptionSuggestionDb.column_name)
            .join(MetadataGenerationRunDb, MetadataGenerationRunDb.id == DescriptionSuggestionDb.run_id)
            .filter(
                DescriptionSuggestionDb.run_id != run.id,
                MetadataGenerationRunDb.created_at > run.created_at,
                DescriptionSuggestionDb.table_fqn.in_(table_fqns),
            )
            .all()
        )
        return {(fqn, column) for fqn, column in rows}


metagen_runs_repo = MetadataGenerationRunsRepository()
metagen_suggestions_repo = DescriptionSuggestionsRepository()
