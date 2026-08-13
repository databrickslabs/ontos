"""Database model for upload history + rollback (P2-1).

Each re-upload (a bulk versioning event applied by
``SemanticModelsManager.apply_upload_as_versioning_event``) records ONE
``upload_event`` row. The row is append-only and captures what each affected
concept looked like BEFORE the upload, so the upload can be rolled back FORWARD
(re-applying the prior states as a NEW versioning event) — never a delete.

``concept_prev_state`` is a list of ``{iri, prev_version|null, prev_status|null,
bucket}``. ``prev_version`` is the POINTER to the concept_version that was
current before the event (null = the concept was new/absent before); the frozen
triples for that version already live in ``concept_version`` / ``rdf_triples``,
so we never duplicate them here.
"""
import uuid

from sqlalchemy import Column, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.sql import func

from src.common.database import Base


class UploadEventDb(Base):
    """One recorded re-upload / rollback event for a semantic-model context."""
    __tablename__ = "upload_event"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # The file/model context this upload targeted.
    context_name = Column(Text, nullable=False, index=True)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(),
                        nullable=False, index=True)
    created_by = Column(String, nullable=True)

    # Diff summary counts: {unchanged, modified, new, removed}.
    summary = Column(JSON, nullable=True)

    # Per-concept before-state:
    #   [{iri, prev_version|null, prev_status|null, bucket}, ...]
    concept_prev_state = Column(JSON, nullable=True)

    def __repr__(self):
        return (
            f"<UploadEventDb(id='{self.id}', context_name='{self.context_name}', "
            f"created_by='{self.created_by}')>"
        )
