from typing import List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

from src.common.repository import CRUDBase
from src.db_models.change_log import ChangeLogDb
from src.common.logging import get_logger

logger = get_logger(__name__)


class ChangeLogRepository(CRUDBase[ChangeLogDb, ChangeLogDb, ChangeLogDb]):
    def __init__(self):
        super().__init__(ChangeLogDb)

    def list_by_entity(self, db: Session, *, entity_type: Optional[str] = None, entity_id: Optional[str] = None, username: Optional[str] = None, action: Optional[str] = None, limit: int = 200) -> List[ChangeLogDb]:
        stmt = select(ChangeLogDb)
        if entity_type:
            stmt = stmt.where(ChangeLogDb.entity_type == entity_type)
        if entity_id:
            stmt = stmt.where(ChangeLogDb.entity_id == entity_id)
        if username:
            stmt = stmt.where(ChangeLogDb.username == username)
        if action:
            stmt = stmt.where(ChangeLogDb.action == action)
        stmt = stmt.order_by(ChangeLogDb.timestamp.desc()).limit(limit)
        return list(db.execute(stmt).scalars().all())

    def list_filtered(
        self,
        db: Session,
        *,
        skip: int = 0,
        limit: int = 100,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        username: Optional[str] = None,
        action: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> List[ChangeLogDb]:
        stmt = select(ChangeLogDb)
        if entity_type:
            stmt = stmt.where(ChangeLogDb.entity_type == entity_type)
        if entity_id:
            stmt = stmt.where(ChangeLogDb.entity_id == entity_id)
        if username:
            stmt = stmt.where(ChangeLogDb.username == username)
        if action:
            stmt = stmt.where(ChangeLogDb.action == action)
        if start_time:
            stmt = stmt.where(ChangeLogDb.timestamp >= start_time)
        if end_time:
            stmt = stmt.where(ChangeLogDb.timestamp <= end_time)
        stmt = stmt.order_by(ChangeLogDb.timestamp.desc()).offset(skip).limit(limit)
        return list(db.execute(stmt).scalars().all())


change_log_repo = ChangeLogRepository()


