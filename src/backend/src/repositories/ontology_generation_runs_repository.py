"""
Repository for ontology generation run CRUD operations.
"""

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.db_models.ontology_generation_runs import OntologyGenerationRunDb

logger = get_logger(__name__)


class OntologyGenerationRunsRepository:

    def get(self, db: Session, run_id: str) -> Optional[OntologyGenerationRunDb]:
        return db.query(OntologyGenerationRunDb).filter(
            OntologyGenerationRunDb.id == run_id,
        ).first()

    def get_for_user(self, db: Session, run_id: str, user_id: str) -> Optional[OntologyGenerationRunDb]:
        return db.query(OntologyGenerationRunDb).filter(
            OntologyGenerationRunDb.id == run_id,
            OntologyGenerationRunDb.user_id == user_id,
        ).first()

    def list_for_user(
        self, db: Session, user_id: str, *, limit: int = 50, skip: int = 0
    ) -> List[OntologyGenerationRunDb]:
        return (
            db.query(OntologyGenerationRunDb)
            .filter(OntologyGenerationRunDb.user_id == user_id)
            .order_by(desc(OntologyGenerationRunDb.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

    def list_all(
        self, db: Session, *, limit: int = 50, skip: int = 0
    ) -> List[OntologyGenerationRunDb]:
        return (
            db.query(OntologyGenerationRunDb)
            .order_by(desc(OntologyGenerationRunDb.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

    def count_running_for_user(self, db: Session, user_id: str) -> int:
        return (
            db.query(OntologyGenerationRunDb)
            .filter(
                OntologyGenerationRunDb.user_id == user_id,
                OntologyGenerationRunDb.status.in_(('pending', 'running')),
            )
            .count()
        )

    def create(self, db: Session, *, run_id: str, user_id: str, **kwargs) -> OntologyGenerationRunDb:
        run = OntologyGenerationRunDb(id=run_id, user_id=user_id, status='pending', **kwargs)
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
    ) -> Optional[OntologyGenerationRunDb]:
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

    def update_steps(
        self, db: Session, run_id: str, steps: list, progress_message: Optional[str] = None
    ) -> None:
        run = self.get(db, run_id)
        if not run:
            return
        run.steps = steps
        if progress_message is not None:
            run.progress_message = progress_message
        db.flush()

    def set_result(self, db: Session, run_id: str, result: dict) -> None:
        run = self.get(db, run_id)
        if not run:
            return
        run.result = result
        run.status = 'completed'
        run.completed_at = datetime.now(timezone.utc)
        db.flush()

    def delete(self, db: Session, run_id: str) -> bool:
        run = self.get(db, run_id)
        if not run:
            return False
        db.delete(run)
        db.flush()
        return True


ontology_generation_runs_repo = OntologyGenerationRunsRepository()
