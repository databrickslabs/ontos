import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Boolean, Text, Enum as SQLAlchemyEnum, Index, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID # Or keep generic UUID

from src.common.database import Base
from src.models.notifications import NotificationType # Import the Pydantic enum

class NotificationDb(Base):
    """In-app notifications: type, title, message, recipient (email or role), read flag; used for job progress, review requests, and alerts (NotificationsManager)."""
    __tablename__ = 'notifications'
    __table_args__ = (
        # get_by_action_type: equality on action_type, then read
        Index('ix_notifications_action_type_read', 'action_type', 'read'),
        # get_addressed_to / get_by_action_type: ORDER BY created_at, id
        Index('ix_notifications_created_at_id', 'created_at', 'id'),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    type = Column(String(50), nullable=False, index=True)
    title = Column(String, nullable=False)
    subtitle = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    message = Column(Text, nullable=True)  # Alternative to description for job progress
    link = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=True)  # For tracking updates
    read = Column(Boolean, default=False, nullable=False)
    can_delete = Column(Boolean, default=True, nullable=False)
    recipient = Column(String, nullable=True, index=True)  # Email, username, or role name (legacy)
    recipient_role_id = Column(String, nullable=True, index=True)  # Role UUID for role-based recipients
    target_roles = Column(String, nullable=True)  # JSON array of role names (legacy)
    action_type = Column(String, nullable=True) # For linking to actions
    action_payload = Column(String, nullable=True) # JSON string for action context
    data = Column(String, nullable=True)  # JSON string for additional data (job progress etc.)

    def __repr__(self):
        return f"<NotificationDb(id='{self.id}', title='{self.title}', recipient='{self.recipient}')>"


class NotificationTemplateDb(Base):
    """Reusable notification message templates with ${var} placeholders."""
    __tablename__ = 'notification_templates'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False, unique=True, index=True)
    title_template = Column(String, nullable=False)
    body_template = Column(Text, nullable=False)
    notification_type = Column(String(50), nullable=False, default='info')
    is_default = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<NotificationTemplateDb(id='{self.id}', name='{self.name}')>"