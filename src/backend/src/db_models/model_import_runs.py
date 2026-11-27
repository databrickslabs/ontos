"""
Model Import Run Database Model

A staged import of an external data model (erwin today) into Ontos concepts
and data contracts (PRD #1718). A run is created when a file is uploaded and
parsed; it holds the parsed model, the steward's options and the preview.
Nothing is written to concepts or contracts until the run is confirmed with
the token of its current preview. Confirmed runs execute in a background
thread and record their result here.
"""

from uuid import uuid4

from sqlalchemy import Column, DateTime, Index, Integer, LargeBinary, String, Text, func
from sqlalchemy.dialects.postgresql import JSON

from src.common.database import Base


class ModelImportRunDb(Base):
    """A staged, reviewable model import."""
    __tablename__ = 'model_import_runs'

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, nullable=False, index=True)

    # previewed | running | completed | failed | cancelled | expired
    status = Column(String, nullable=False, default='previewed')
    progress_message = Column(String, nullable=True)
    error = Column(Text, nullable=True)

    # Source: file_xml | file_json | mart | drop_zone
    source_kind = Column(String, nullable=False, default='file_xml')
    source_filename = Column(String, nullable=True)
    source_sha256 = Column(String(64), nullable=True, index=True)
    source_size_bytes = Column(Integer, nullable=True)

    # The model as parsed (erwin object id, name, version). source_model_id
    # finds earlier runs of the same model for re-imports.
    source_model_id = Column(String, nullable=True, index=True)
    source_model_name = Column(String, nullable=True)
    source_model_version = Column(String, nullable=True)

    # gzip-compressed JSON of the IR (src.model_import.erwin.ir.ErwinModel), so
    # a run can be confirmed or re-run without the original upload.
    model_ir = Column(LargeBinary, nullable=True)

    options = Column(JSON, nullable=True)
    preview = Column(JSON, nullable=True)
    # Hash of (options, preview); confirm must present the matching token.
    confirm_token = Column(String, nullable=True)
    result = Column(JSON, nullable=True)

    notification_id = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index('ix_model_import_runs_user_created', 'user_id', 'created_at'),
        Index('ix_model_import_runs_model_status', 'source_model_id', 'status'),
    )

    def __repr__(self):
        return f"<ModelImportRunDb(id='{self.id}', model='{self.source_model_name}', status='{self.status}')>"
