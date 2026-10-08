"""
Repository for schema import run CRUD operations.

Mirrors ontology_generation_runs_repository — the async Schema Importer reuses
the same in-app background-run pattern.
"""

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.db_models.schema_import_runs import SchemaImportRunDb

logger = get_logger(__name__)


class SchemaImportRunsRepository:

    def get(self, db: Session, run_id: str) -> Optional[SchemaImportRunDb]:
        return db.query(SchemaImportRunDb).filter(
            SchemaImportRunDb.id == run_id,
        ).first()

    def get_for_user(self, db: Session, run_id: str, user_id: str) -> Optional[SchemaImportRunDb]:
        return db.query(SchemaImportRunDb).filter(
            SchemaImportRunDb.id == run_id,
            SchemaImportRunDb.user_id == user_id,
        ).first()

    def list_for_user(
        self, db: Session, user_id: str, *, limit: int = 50, skip: int = 0
    ) -> List[SchemaImportRunDb]:
        return (
            db.query(SchemaImportRunDb)
            .filter(SchemaImportRunDb.user_id == user_id)
            .order_by(desc(SchemaImportRunDb.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

    def count_running_for_user(self, db: Session, user_id: str) -> int:
        return (
            db.query(SchemaImportRunDb)
            .filter(
                SchemaImportRunDb.user_id == user_id,
                SchemaImportRunDb.status.in_(('pending', 'running')),
            )
            .count()
        )

    def create(self, db: Session, *, run_id: str, user_id: str, **kwargs) -> SchemaImportRunDb:
        run = SchemaImportRunDb(id=run_id, user_id=user_id, status='pending', **kwargs)
        db.add(run)
        db.flush()
        db.refresh(run)
        return run

    def update_status(
        self,
        db: Session,
        run_id: str,
        status: str,
        *,
        progress_message: Optional[str] = None,
        error: Optional[str] = None,
        completed_at: Optional[datetime] = None,
    ) -> Optional[SchemaImportRunDb]:
        run = self.get(db, run_id)
        if not run:
            return None
        run.status = status
        if progress_message is not None:
            run.progress_message = progress_message
        if error is not None:
            run.error = error
        if completed_at is not None:
            run.completed_at = completed_at
        db.flush()
        return run

    def update_progress(
        self,
        db: Session,
        run_id: str,
        *,
        processed_items: Optional[int] = None,
        total_items: Optional[int] = None,
        created_count: Optional[int] = None,
        skipped_count: Optional[int] = None,
        error_count: Optional[int] = None,
        progress_message: Optional[str] = None,
    ) -> Optional[SchemaImportRunDb]:
        run = self.get(db, run_id)
        if not run:
            return None
        if processed_items is not None:
            run.processed_items = processed_items
        if total_items is not None:
            run.total_items = total_items
        if created_count is not None:
            run.created_count = created_count
        if skipped_count is not None:
            run.skipped_count = skipped_count
        if error_count is not None:
            run.error_count = error_count
        if progress_message is not None:
            run.progress_message = progress_message
        db.flush()
        return run

    def set_result(
        self,
        db: Session,
        run_id: str,
        result: dict,
        *,
        status: str = 'completed',
        created_count: Optional[int] = None,
        skipped_count: Optional[int] = None,
        error_count: Optional[int] = None,
    ) -> Optional[SchemaImportRunDb]:
        run = self.get(db, run_id)
        if not run:
            return None
        run.result = result
        run.status = status
        if created_count is not None:
            run.created_count = created_count
        if skipped_count is not None:
            run.skipped_count = skipped_count
        if error_count is not None:
            run.error_count = error_count
        run.completed_at = datetime.now(timezone.utc)
        db.flush()
        return run

    def delete(self, db: Session, run_id: str) -> bool:
        run = self.get(db, run_id)
        if not run:
            return False
        db.delete(run)
        db.flush()
        return True


schema_import_runs_repo = SchemaImportRunsRepository()
