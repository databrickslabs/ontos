"""
Connector Sync Database Model

A saved Schema Importer selection that is imported again on a schedule. The
``connector_sync`` Databricks job runs the due syncs: each run walks the selection
completely, refreshes what changed in the source, and retires assets the source
no longer has (after ``retire_after_misses`` complete runs).
"""

from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSON, UUID as PG_UUID

from src.common.database import Base


class ConnectorSyncDb(Base):
    __tablename__ = "connector_syncs"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    name = Column(String, nullable=False)
    connection_id = Column(PG_UUID(as_uuid=True), ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True)
    # The ImportRequest selection: selected_paths, depth, excluded_paths
    request = Column(JSON, nullable=False)

    interval_minutes = Column(Integer, nullable=False, default=1440)
    retire_after_misses = Column(Integer, nullable=False, default=3)
    enabled = Column(Boolean, nullable=False, default=True)

    # State of the last run
    last_run_id = Column(String, nullable=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    # completed | incomplete | failed
    last_status = Column(String, nullable=True)
    last_complete_sync_at = Column(DateTime(timezone=True), nullable=True)
    next_due_at = Column(DateTime(timezone=True), nullable=True, index=True)

    created_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<ConnectorSyncDb(id='{self.id}', name='{self.name}', enabled={self.enabled})>"
