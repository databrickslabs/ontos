import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Index, String, Text, func

from src.common.database import Base


class NotificationRecipientDb(Base):
    """Named notification target that compliance policies reference as ``NOTIFY recipient:'<name>'``.

    ``targets`` is a JSON list of emails, groups and app roles; ``allowed_role_ids`` is a JSON
    list of app role ids whose members may use the recipient in their policies (admins always may).
    """
    __tablename__ = 'notification_recipients'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False, unique=True)
    description = Column(Text, nullable=True)
    targets = Column(Text, nullable=False, default='[]', server_default='[]')
    allowed_role_ids = Column(Text, nullable=False, default='[]', server_default='[]')
    is_active = Column(Boolean, nullable=False, default=True, server_default='true')
    created_by = Column(String, nullable=True)
    updated_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Names are unique without case (the manager checks, this keeps concurrent creates apart)
    __table_args__ = (Index('uq_notification_recipients_name_ci', func.lower(name), unique=True),)
