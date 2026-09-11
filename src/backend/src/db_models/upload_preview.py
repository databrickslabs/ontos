"""Database model for staged upload previews (P1-0: steward preview + confirm).

A file re-upload no longer auto-applies. Instead the manager computes a
concept-level diff (``compute_concept_diff``) and stashes the incoming file
content here, keyed by an opaque ``token``. The steward is shown a PREVIEW
(modifies N / adds M / removes K, plus reference counts) and NOTHING is applied
until they confirm. ``confirm_upload(token)`` re-parses the stashed content and
runs the existing ``apply_upload_as_versioning_event`` primitive, then deletes
the stash row. A token is single-use: confirming consumes (deletes) it.
"""
import uuid

from sqlalchemy import Column, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.sql import func

from src.common.database import Base


class UploadPreviewDb(Base):
    """A pending, not-yet-applied upload stash.

    ``token`` (PK) is the opaque handle the steward confirms against. The raw
    ``content_text`` + ``format`` are stashed so confirm can re-parse and apply
    WITHOUT the user re-uploading the file. Single-use: consumed on confirm.
    """
    __tablename__ = "upload_preview"

    token = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    context_name = Column(Text, nullable=False)
    content_text = Column(Text, nullable=False)
    format = Column(String(20), nullable=False, default="skos")
    created_by = Column(String, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
