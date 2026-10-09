"""
Schema Import Run Database Model

Persists async Schema Importer runs so they survive server restarts and can be
polled for progress. Mirrors the ontology_generation_runs pattern used by the
Ontology Generator's in-app background execution.
"""

from sqlalchemy import Column, String, DateTime, Integer, Text, func, Index
from sqlalchemy.dialects.postgresql import JSON
from uuid import uuid4

from src.common.database import Base


class SchemaImportRunDb(Base):
    """Tracks an async Schema Importer run."""
    __tablename__ = 'schema_import_runs'

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, nullable=False, index=True)

    # pending | running | completed | failed | cancelled
    status = Column(String, nullable=False, default='pending')
    progress_message = Column(String, nullable=True)
    error = Column(Text, nullable=True)

    # Run parameters
    connection_id = Column(String, nullable=True)
    # The full ImportRequest payload (selected_paths, depth, excluded_paths,
    # path_mappings) so the run is self-describing and re-runnable.
    request = Column(JSON, nullable=True)

    # Progress counters (live-updated from the background thread)
    total_items = Column(Integer, nullable=True)
    processed_items = Column(Integer, nullable=False, default=0)
    created_count = Column(Integer, nullable=False, default=0)
    skipped_count = Column(Integer, nullable=False, default=0)
    error_count = Column(Integer, nullable=False, default=0)

    # Full ImportResult blob — set on completion
    result = Column(JSON, nullable=True)

    # The JOB_PROGRESS notification tracking this run (updated to terminal state)
    notification_id = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index('ix_schema_import_runs_user_status', 'user_id', 'status'),
        Index('ix_schema_import_runs_user_created', 'user_id', 'created_at'),
    )

    def __repr__(self):
        return f"<SchemaImportRunDb(id='{self.id}', user='{self.user_id}', status='{self.status}')>"
