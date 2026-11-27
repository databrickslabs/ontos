import json
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.common.repository import CRUDBase
from src.db_models.notification_recipients import NotificationRecipientDb


class NotificationRecipientRepository(CRUDBase[NotificationRecipientDb, Dict[str, Any], Dict[str, Any]]):
    def __init__(self):
        super().__init__(NotificationRecipientDb)

    def list_all(self, db: Session) -> List[NotificationRecipientDb]:
        stmt = select(NotificationRecipientDb).order_by(func.lower(NotificationRecipientDb.name))
        return list(db.execute(stmt).scalars().all())

    def get_by_name(self, db: Session, name: str, *, exclude_id: Optional[str] = None) -> Optional[NotificationRecipientDb]:
        """The recipient with this name, compared without case (names are unique that way)."""
        stmt = select(NotificationRecipientDb).where(
            func.lower(NotificationRecipientDb.name) == name.strip().lower()
        )
        if exclude_id is not None:
            stmt = stmt.where(NotificationRecipientDb.id != exclude_id)
        return db.execute(stmt).scalars().first()


def json_list(value: Optional[str]) -> List[str]:
    """A JSON list column as a list of strings (empty for missing or invalid values)."""
    try:
        parsed = json.loads(value) if value else []
    except (TypeError, ValueError):
        return []
    return [str(item) for item in parsed if item] if isinstance(parsed, list) else []


notification_recipient_repo = NotificationRecipientRepository()
