import json
from typing import Any, Dict, Optional, Union, List
from datetime import datetime

from sqlalchemy.orm import Session

from src.common.repository import CRUDBase
from src.db_models.workflow_installations import WorkflowInstallationDb
from src.models.workflow_installations import WorkflowInstallation
from src.common.logging import get_logger

logger = get_logger(__name__)


class WorkflowInstallationRepository(CRUDBase[WorkflowInstallationDb, WorkflowInstallation, WorkflowInstallation]):
    """Repository for WorkflowInstallation CRUD operations."""

    def create(self, db: Session, *, obj_in: WorkflowInstallation) -> WorkflowInstallationDb:
        """Creates a WorkflowInstallation record."""
        db_obj_data = obj_in.model_dump()
        # Serialize last_job_state if it's a dict
        if 'last_job_state' in db_obj_data and db_obj_data['last_job_state']:
            db_obj_data['last_job_state'] = json.dumps(db_obj_data['last_job_state'])
        db_obj = self.model(**db_obj_data)
        db.add(db_obj)
        db.flush()
        db.refresh(db_obj)
        logger.info(f"Created WorkflowInstallationDb: workflow_id={db_obj.workflow_id}, job_id={db_obj.job_id}")
        return db_obj

    def update(self, db: Session, *, db_obj: WorkflowInstallationDb, obj_in: Union[WorkflowInstallation, Dict[str, Any]]) -> WorkflowInstallationDb:
        """Updates a WorkflowInstallation record."""
        if isinstance(obj_in, dict):
            update_data = obj_in
        else:
            update_data = obj_in.model_dump(exclude_unset=True)

        # Serialize last_job_state if present
        if 'last_job_state' in update_data and update_data['last_job_state']:
            if isinstance(update_data['last_job_state'], dict):
                update_data['last_job_state'] = json.dumps(update_data['last_job_state'])

        updated_db_obj = super().update(db, db_obj=db_obj, obj_in=update_data)
        logger.info(f"Updated WorkflowInstallationDb: workflow_id={updated_db_obj.workflow_id}")
        return updated_db_obj

    def get_by_workflow_id(self, db: Session, *, workflow_id: str) -> Optional[WorkflowInstallationDb]:
        """Retrieves a WorkflowInstallation by workflow_id."""
        return db.query(self.model).filter(self.model.workflow_id == workflow_id).first()

    def get_by_job_id(self, db: Session, *, job_id: int) -> Optional[WorkflowInstallationDb]:
        """Retrieves a WorkflowInstallation by Databricks job_id."""
        return db.query(self.model).filter(self.model.job_id == job_id).first()

    def get_all_installed(self, db: Session) -> List[WorkflowInstallationDb]:
        """Retrieves all installed workflows (status='installed')."""
        return db.query(self.model).filter(self.model.status == 'installed').all()

    def get_all(self, db: Session) -> List[WorkflowInstallationDb]:
        """Retrieves all workflow installations."""
        return self.get_multi(db=db)

    def update_last_polled(
        self,
        db: Session,
        *,
        workflow_id: str,
        job_state: Optional[Dict[str, Any]] = None,
        only_if_changed: bool = False,
    ) -> Optional[WorkflowInstallationDb]:
        """Updates last_polled_at and optionally last_job_state.

        When ``only_if_changed`` is True, the write is skipped entirely if the
        serialized ``job_state`` matches what is already stored. The background
        poll uses this so a quiet cycle (no run-state transition) performs zero
        Lakebase writes, letting the instance idle. ``last_polled_at`` is
        intentionally NOT bumped on a no-op — its only consumers are the
        incremental-window poll and human diagnostics, neither of which needs a
        heartbeat when nothing changed.
        """
        db_obj = self.get_by_workflow_id(db, workflow_id=workflow_id)
        if not db_obj:
            return None

        serialized_state = json.dumps(job_state) if job_state else None
        if only_if_changed and serialized_state is not None:
            if db_obj.last_job_state == serialized_state:
                return db_obj

        update_data = {
            'last_polled_at': datetime.utcnow()
        }
        if serialized_state is not None:
            update_data['last_job_state'] = serialized_state

        return self.update(db, db_obj=db_obj, obj_in=update_data)


# Create singleton instance of the repository
workflow_installation_repo = WorkflowInstallationRepository(WorkflowInstallationDb)
