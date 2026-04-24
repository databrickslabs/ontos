"""
Repository for agreement wizard sessions.
"""

import json
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from src.db_models.agreement_wizard_sessions import AgreementWizardSessionDb
from src.common.logging import get_logger

logger = get_logger(__name__)


class AgreementWizardSessionsRepository:
    """Repository for AgreementWizardSessionDb."""

    def create(
        self,
        db: Session,
        *,
        workflow_id: str,
        entity_type: str,
        entity_id: str,
        completion_action: Optional[str] = None,
        created_by: Optional[str] = None,
        workflow_snapshot: Optional[str] = None,
        workflow_name: Optional[str] = None,
    ) -> AgreementWizardSessionDb:
        """Create a new wizard session."""
        session = AgreementWizardSessionDb(
            workflow_id=workflow_id,
            entity_type=entity_type,
            entity_id=entity_id,
            completion_action=completion_action,
            current_step_index=0,
            step_results=json.dumps([]),
            status='in_progress',
            created_by=created_by,
            workflow_snapshot=workflow_snapshot,
            workflow_name=workflow_name,
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    def get(self, db: Session, session_id: str) -> Optional[AgreementWizardSessionDb]:
        """Get a session by id."""
        return db.query(AgreementWizardSessionDb).filter(
            AgreementWizardSessionDb.id == session_id
        ).first()

    def get_by_created_by(
        self,
        db: Session,
        created_by: str,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[AgreementWizardSessionDb], int]:
        """Get all sessions created by a user (any status), newest first."""
        query = db.query(AgreementWizardSessionDb).filter(
            AgreementWizardSessionDb.created_by == created_by
        )
        total = query.count()
        sessions = (
            query.order_by(AgreementWizardSessionDb.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return sessions, total

    def get_step_results(self, session: AgreementWizardSessionDb) -> List[Dict[str, Any]]:
        """Parse step_results JSON; return list of { step_id, payload }."""
        if not session.step_results:
            return []
        try:
            data = json.loads(session.step_results)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    def append_step_result(
        self,
        db: Session,
        session_id: str,
        step_id: str,
        payload: Dict[str, Any],
    ) -> Optional[AgreementWizardSessionDb]:
        """Append a step result and optionally advance current_step_index or set status."""
        session = self.get(db, session_id)
        if not session or session.status != 'in_progress':
            return None
        results = self.get_step_results(session)
        results.append({'step_id': step_id, 'payload': payload})
        session.step_results = json.dumps(results)
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    def set_current_step_index(
        self,
        db: Session,
        session_id: str,
        index: int,
    ) -> Optional[AgreementWizardSessionDb]:
        """Set current step index (for Next step)."""
        session = self.get(db, session_id)
        if not session or session.status != 'in_progress':
            return None
        session.current_step_index = index
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    def set_completed(self, db: Session, session_id: str) -> Optional[AgreementWizardSessionDb]:
        """Mark session as completed."""
        session = self.get(db, session_id)
        if not session:
            return None
        session.status = 'completed'
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    def set_abandoned(self, db: Session, session_id: str) -> Optional[AgreementWizardSessionDb]:
        """Mark session as abandoned."""
        session = self.get(db, session_id)
        if not session:
            return None
        session.status = 'abandoned'
        db.add(session)
        db.commit()
        db.refresh(session)
        return session


agreement_wizard_sessions_repo = AgreementWizardSessionsRepository()
