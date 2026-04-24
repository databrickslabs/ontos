"""
Database model for agreements.

Agreements are created when an approval workflow wizard is completed.
They store step_results and optional pdf_storage_path; linked from entity change log.
"""

import uuid
from sqlalchemy import Column, String, Text, ForeignKey, func, TIMESTAMP

from src.common.database import Base


class AgreementDb(Base):
    """Store agreement records (output of completed approval workflow wizards)."""
    __tablename__ = 'agreements'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_type = Column(String(100), nullable=False, index=True)
    entity_id = Column(String(255), nullable=False, index=True)
    workflow_id = Column(String, ForeignKey('process_workflows.id', ondelete='SET NULL'), nullable=True, index=True)
    wizard_session_id = Column(String, nullable=True, index=True)  # FK optional to avoid circular dep on session table
    step_results = Column(Text, nullable=True)  # JSON list of step results
    pdf_storage_path = Column(String(1024), nullable=True)
    workflow_snapshot = Column(Text, nullable=True)  # Immutable JSON snapshot of workflow definition at agreement creation
    workflow_name = Column(String(255), nullable=True)  # Workflow name at agreement creation time
    created_by = Column(String(255), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<AgreementDb(id='{self.id}', entity_type='{self.entity_type}', entity_id='{self.entity_id}')>"
