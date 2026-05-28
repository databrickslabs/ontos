"""
Ontology Generation Run Database Model

Persists async ontology generation runs so they survive server restarts.
"""

from sqlalchemy import Column, String, DateTime, Text, func, Index
from sqlalchemy.dialects.postgresql import JSON
from uuid import uuid4

from src.common.database import Base


class OntologyGenerationRunDb(Base):
    """Tracks an async ontology generation run."""
    __tablename__ = 'ontology_generation_runs'

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, nullable=False, index=True)

    # pending | running | completed | failed | cancelled
    status = Column(String, nullable=False, default='pending')
    progress_message = Column(String, nullable=True)
    error = Column(Text, nullable=True)

    # Run parameters
    connection_id = Column(String, nullable=True)
    connection_name = Column(String, nullable=True)
    selected_paths = Column(JSON, nullable=True)
    guidelines = Column(Text, nullable=True)
    base_uri = Column(String, nullable=True)
    options = Column(JSON, nullable=True)

    # Live-updated agent steps (JSON array of step dicts)
    steps = Column(JSON, nullable=True)

    # Full result blob (GenerateOntologyResponse as dict) — set on completion
    result = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index('ix_ontology_runs_user_status', 'user_id', 'status'),
        Index('ix_ontology_runs_user_created', 'user_id', 'created_at'),
    )

    def __repr__(self):
        return f"<OntologyGenerationRunDb(id='{self.id}', user='{self.user_id}', status='{self.status}')>"
