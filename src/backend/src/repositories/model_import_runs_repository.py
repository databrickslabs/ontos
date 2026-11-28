"""
Repository for model import runs (PRD #1718).
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from src.db_models.model_import_runs import ModelImportRunDb

ACTIVE_STATUSES = ('running',)
# A running run whose row has not been touched for this long lost its worker
# (restart, crash): progress updates touch updated_at at least per contract.
STALE_RUNNING_AFTER = timedelta(minutes=30)


class ModelImportRunsRepository:

    def get(self, db: Session, run_id: str) -> Optional[ModelImportRunDb]:
        return db.query(ModelImportRunDb).filter(ModelImportRunDb.id == run_id).first()

    def list(
        self, db: Session, *, user_id: Optional[str] = None, limit: int = 50, skip: int = 0,
    ) -> List[ModelImportRunDb]:
        q = db.query(ModelImportRunDb)
        if user_id is not None:
            q = q.filter(ModelImportRunDb.user_id == user_id)
        return q.order_by(desc(ModelImportRunDb.created_at)).offset(skip).limit(limit).all()

    def latest_completed_for_model(
        self, db: Session, source_model_id: str, *, exclude_run_id: Optional[str] = None,
    ) -> Optional[ModelImportRunDb]:
        q = db.query(ModelImportRunDb).filter(
            ModelImportRunDb.source_model_id == source_model_id,
            ModelImportRunDb.status == 'completed',
        )
        if exclude_run_id:
            q = q.filter(ModelImportRunDb.id != exclude_run_id)
        return q.order_by(desc(ModelImportRunDb.completed_at)).first()

    def count_running_for_model(self, db: Session, source_model_id: str) -> int:
        return db.query(ModelImportRunDb).filter(
            ModelImportRunDb.source_model_id == source_model_id,
            ModelImportRunDb.status.in_(ACTIVE_STATUSES),
        ).count()

    def claim(self, db: Session, run_id: str, token: str) -> bool:
        """Flip a previewed run to running if its token still matches (atomic).

        Raises IntegrityError (at flush or commit) if another run of the same
        model is running: see the partial unique index on the table.
        """
        updated = db.query(ModelImportRunDb).filter(
            ModelImportRunDb.id == run_id,
            ModelImportRunDb.status == 'previewed',
            ModelImportRunDb.confirm_token == token,
        ).update(
            {ModelImportRunDb.status: 'running', ModelImportRunDb.confirm_token: None,
             ModelImportRunDb.updated_at: datetime.now(timezone.utc)},
            synchronize_session=False,
        )
        db.flush()
        return updated == 1

    @staticmethod
    def is_stale(run: ModelImportRunDb, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now(timezone.utc)
        touched = run.updated_at or run.created_at
        if touched is None:
            return True
        if touched.tzinfo is None:
            touched = touched.replace(tzinfo=timezone.utc)
        return now - touched > STALE_RUNNING_AFTER

    def count_running_for_user(self, db: Session, user_id: str) -> int:
        return db.query(ModelImportRunDb).filter(
            ModelImportRunDb.user_id == user_id,
            ModelImportRunDb.status.in_(ACTIVE_STATUSES),
        ).count()

    def expire_stale(self, db: Session, now: Optional[datetime] = None) -> int:
        """Expire previewed runs past their expiry (dropping their stored model) and
        fail running runs that lost their worker."""
        now = now or datetime.now(timezone.utc)
        orphaned = [r for r in db.query(ModelImportRunDb).filter(
            ModelImportRunDb.status.in_(ACTIVE_STATUSES)).all() if self.is_stale(r, now)]
        for run in orphaned:
            run.status = 'failed'
            run.error = 'The import stopped without finishing (server restart?). Upload the model again.'
            run.completed_at = now
        stale = db.query(ModelImportRunDb).filter(
            ModelImportRunDb.status == 'previewed',
            ModelImportRunDb.expires_at.isnot(None),
            ModelImportRunDb.expires_at < now,
        ).all()
        for run in stale:
            run.status = 'expired'
            run.model_ir = None
            run.confirm_token = None
        return len(stale) + len(orphaned)

    def add(self, db: Session, run: ModelImportRunDb) -> ModelImportRunDb:
        db.add(run)
        db.flush()
        return run


model_import_runs_repo = ModelImportRunsRepository()
