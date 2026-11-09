import json
from uuid import uuid4
from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.sql import func

from src.common.database import Base


class ChangeLogDb(Base):
    """Entity-level change history: who did what to which entity (entity_type, entity_id, action, details_json)."""
    __tablename__ = 'entity_change_log'

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    entity_type = Column(String, nullable=False, index=True)
    entity_id = Column(String, nullable=False, index=True)
    action = Column(String, nullable=False)
    username = Column(String, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    details_json = Column(Text, nullable=True)

    @property
    def details(self) -> dict:
        """``details_json`` parsed (empty when missing or not a JSON object)."""
        try:
            value = json.loads(self.details_json) if self.details_json else {}
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}


