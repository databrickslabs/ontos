"""Repository for ``upload_event`` rows (upload history + rollback, P2-1).

Append-only history of re-upload / rollback events per semantic-model context.
Mirrors the concept_versions_repository singleton style.
"""
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.common.repository import CRUDBase
from src.db_models.upload_event import UploadEventDb
from src.common.logging import get_logger

logger = get_logger(__name__)


class UploadEventRepository(CRUDBase[UploadEventDb, dict, dict]):
    """CRUD + read helpers for ``upload_event``."""

    def record(
        self,
        db: Session,
        context_name: str,
        summary: Optional[Dict[str, Any]] = None,
        concept_prev_state: Optional[List[Dict[str, Any]]] = None,
        created_by: Optional[str] = None,
    ) -> UploadEventDb:
        """Insert one upload_event row and flush it (so its id is available)."""
        row = UploadEventDb(
            context_name=context_name,
            summary=summary,
            concept_prev_state=concept_prev_state,
            created_by=created_by,
        )
        db.add(row)
        db.flush()
        return row

    def list_by_context(self, db: Session, context_name: str) -> List[UploadEventDb]:
        """All upload events for a context, newest-first."""
        return (
            db.query(UploadEventDb)
            .filter(UploadEventDb.context_name == context_name)
            .order_by(UploadEventDb.created_at.desc())
            .all()
        )


# Singleton instance (matches concept_versions_repo pattern).
upload_event_repo = UploadEventRepository(UploadEventDb)
