"""Repository for staged upload previews (P1-0).

Tiny CRUD over ``upload_preview``: stash the incoming file content keyed by an
opaque token, fetch it back by token when the steward confirms, and delete it
(single-use consume). No update path — a preview is immutable once stashed.
"""
from typing import Optional
import uuid

from sqlalchemy.orm import Session

from src.db_models.upload_preview import UploadPreviewDb
from src.common.logging import get_logger

logger = get_logger(__name__)


class UploadPreviewRepository:
    """CRUD for the single-use upload-preview stash."""

    def create(
        self,
        db: Session,
        context_name: str,
        content_text: str,
        format: str = "skos",
        created_by: Optional[str] = None,
    ) -> UploadPreviewDb:
        row = UploadPreviewDb(
            token=uuid.uuid4(),
            context_name=context_name,
            content_text=content_text,
            format=format,
            created_by=created_by,
        )
        db.add(row)
        db.flush()
        db.refresh(row)
        return row

    def get(self, db: Session, token: str) -> Optional[UploadPreviewDb]:
        try:
            token_uuid = uuid.UUID(str(token))
        except (ValueError, TypeError):
            return None
        return db.query(UploadPreviewDb).filter(UploadPreviewDb.token == token_uuid).first()

    def delete(self, db: Session, token: str) -> bool:
        row = self.get(db, token)
        if row is None:
            return False
        db.delete(row)
        db.flush()
        return True


upload_preview_repo = UploadPreviewRepository()
