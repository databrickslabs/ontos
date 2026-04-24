"""
Database model for agreement wizard sessions.

A wizard session tracks progress through an approval workflow (multi-step wizard).
On completion we create an agreement record (todo 4) and optionally run PDF generation.
"""

import uuid
from sqlalchemy import Column, String, Text, Integer, ForeignKey, func, TIMESTAMP
from sqlalchemy.orm import relationship

from src.common.database import Base


class AgreementWizardSessionDb(Base):
    """Store agreement wizard session state (multi-step approval flow)."""
    __tablename__ = 'agreement_wizard_sessions'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_id = Column(String, ForeignKey('process_workflows.id', ondelete='CASCADE'), nullable=False, index=True)
    entity_type = Column(String(100), nullable=False, index=True)
    entity_id = Column(String(255), nullable=False, index=True)
    completion_action = Column(String(50), nullable=True)  # e.g. 'subscribe' — run after wizard complete
    current_step_index = Column(Integer, nullable=False, default=0)
    step_results = Column(Text, nullable=True)  # JSON list of { step_id, payload } per completed step
    status = Column(String(50), nullable=False, default='in_progress')  # in_progress | completed | abandoned
    workflow_snapshot = Column(Text, nullable=True)  # Immutable JSON snapshot of workflow definition at session creation
    workflow_name = Column(String(255), nullable=True)  # Workflow name at session creation time
    created_by = Column(String(255), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<AgreementWizardSessionDb(id='{self.id}', workflow_id='{self.workflow_id}', status='{self.status}')>"
