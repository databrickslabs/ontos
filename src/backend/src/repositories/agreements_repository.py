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
        workflow_version: Optional[int] = None,
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
            workflow_version=workflow_version,
        )
        db.add(agreement)
        db.commit()
        db.refresh(agreement)
        return agreement

    def get(self, db: Session, agreement_id: str) -> Optional[AgreementDb]:
        """Get agreement by id."""
        return db.query(AgreementDb).filter(AgreementDb.id == agreement_id).first()

    def list_recent(
        self,
        db: Session,
        *,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List recent agreements, optionally filtered by entity type/id."""
        query = db.query(AgreementDb)
        if entity_type:
            query = query.filter(AgreementDb.entity_type == entity_type)
        if entity_id:
            query = query.filter(AgreementDb.entity_id == entity_id)
        agreements = (
            query.order_by(AgreementDb.created_at.desc())
            .limit(limit)
            .all()
        )
        result = []
        for a in agreements:
            result.append({
                "id": a.id,
                "entity_type": a.entity_type,
                "entity_id": a.entity_id,
                "workflow_id": a.workflow_id,
                "workflow_name": a.workflow_name,
                "workflow_version": a.workflow_version,
                "wizard_session_id": a.wizard_session_id,
                "pdf_storage_path": a.pdf_storage_path,
                "created_by": a.created_by,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            })
        return result

    def update_step_results(
        self,
        db: Session,
        agreement_id: str,
        step_results: List[Dict[str, Any]],
    ) -> Optional[AgreementDb]:
        """Update step_results on an existing agreement (e.g. after persist_agreement created it early)."""
        import json
        agreement = self.get(db, agreement_id)
        if not agreement:
            return None
        agreement.step_results = json.dumps(step_results) if step_results is not None else None
        db.add(agreement)
        db.commit()
        db.refresh(agreement)
        return agreement

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

    def has_user_signed_workflow_at_version(
        self,
        db: Session,
        *,
        user_email: str,
        workflow_id: str,
        workflow_version: int,
    ) -> bool:
        """True iff ``user_email`` already has an agreement for ``workflow_id``
        at ``workflow_version`` or later. Used by the on_first_access trigger
        path to decide whether to prompt: a fresh user has no row, a user
        whose accepted version is older than the workflow's current version
        also returns False (re-prompt on text changes)."""
        latest = (
            db.query(AgreementDb)
            .filter(
                AgreementDb.created_by == user_email,
                AgreementDb.workflow_id == workflow_id,
            )
            .order_by(AgreementDb.workflow_version.desc().nulls_last())
            .first()
        )
        if not latest:
            return False
        if latest.workflow_version is None:
            # Legacy agreement without recorded version — treat as accepted
            # (don't re-prompt unnecessarily on cold-start environments).
            return True
        return latest.workflow_version >= workflow_version


agreements_repo = AgreementsRepository()
