"""
Repository for agreements.
"""

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.db_models.agreements import AgreementDb
from src.common.logging import get_logger

logger = get_logger(__name__)


class AgreementsRepository:
    """Repository for AgreementDb."""

    def create(
        self,
        db: Session,
        *,
        entity_type: str,
        entity_id: str,
        workflow_id: Optional[str] = None,
        wizard_session_id: Optional[str] = None,
        step_results: Optional[List[Dict[str, Any]]] = None,
        pdf_storage_path: Optional[str] = None,
        created_by: Optional[str] = None,
        workflow_snapshot: Optional[str] = None,
        workflow_name: Optional[str] = None,
    ) -> AgreementDb:
        """Create an agreement record."""
        import json
        agreement = AgreementDb(
            entity_type=entity_type,
            entity_id=entity_id,
            workflow_id=workflow_id,
            wizard_session_id=wizard_session_id,
            step_results=json.dumps(step_results) if step_results is not None else None,
            pdf_storage_path=pdf_storage_path,
            created_by=created_by,
            workflow_snapshot=workflow_snapshot,
            workflow_name=workflow_name,
        )
        db.add(agreement)
        db.commit()
        db.refresh(agreement)
        return agreement

    def get(self, db: Session, agreement_id: str) -> Optional[AgreementDb]:
        """Get agreement by id."""
        return db.query(AgreementDb).filter(AgreementDb.id == agreement_id).first()

    def set_pdf_storage_path(
        self,
        db: Session,
        agreement_id: str,
        pdf_storage_path: str,
    ) -> Optional[AgreementDb]:
        """Set pdf_storage_path on an agreement."""
        agreement = self.get(db, agreement_id)
        if not agreement:
            return None
        agreement.pdf_storage_path = pdf_storage_path
        db.add(agreement)
        db.commit()
        db.refresh(agreement)
        return agreement


agreements_repo = AgreementsRepository()
