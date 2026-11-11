from __future__ import annotations
from datetime import date
from typing import List, Optional

from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.repositories.costs_repository import cost_items_repo, CostItemsRepository
from src.models.costs import CostItem, CostItemCreate, CostItemUpdate, CostSummary
from src.repositories.change_log_repository import change_log_repo
from src.db_models.change_log import ChangeLogDb

logger = get_logger(__name__)


class CostsManager:
    def __init__(self, repository: CostItemsRepository = cost_items_repo):
        self._repo = repository

    def _log_change(self, db: Session, *, entity_type: str, entity_id: str, action: str, username: Optional[str]) -> None:
        entry = ChangeLogDb(
            entity_type=f"{entity_type}:cost_item",
            entity_id=entity_id,
            action=action,
            username=username,
        )
        db.add(entry)
        db.commit()

    # CRUD
    def create(self, db: Session, *, data: CostItemCreate, user_email: Optional[str]) -> CostItem:
        obj = self._repo.create(db, obj_in=data)
        db.commit()
        db.refresh(obj)
        self._log_change(db, entity_type=data.entity_type, entity_id=data.entity_id, action="CREATE", username=user_email)
        return CostItem.model_validate(obj, from_attributes=True)

    def list(self, db: Session, *, entity_type: str, entity_id: str, month: Optional[date] = None) -> List[CostItem]:
        rows = self._repo.list_for_entity(db, entity_type=entity_type, entity_id=entity_id, month=month)
        return [CostItem.model_validate(r, from_attributes=True) for r in rows]

    def get_entity_type(self, db: Session, *, id: str) -> Optional[str]:
        """Entity kind a cost item belongs to, or None if it doesn't exist."""
        db_obj = self._repo.get(db, id=id)
        return db_obj.entity_type if db_obj else None

    def update(self, db: Session, *, id: str, data: CostItemUpdate, user_email: Optional[str]) -> Optional[CostItem]:
        db_obj = self._repo.get(db, id=id)
        if not db_obj:
            return None
        updated = self._repo.update(db, db_obj=db_obj, obj_in=data)
        db.commit()
        db.refresh(updated)
        self._log_change(db, entity_type=updated.entity_type, entity_id=updated.entity_id, action="UPDATE", username=user_email)
        return CostItem.model_validate(updated, from_attributes=True)

    def delete(self, db: Session, *, id: str, user_email: Optional[str]) -> bool:
        db_obj = self._repo.get(db, id=id)
        if not db_obj:
            return False
        entity_type, entity_id = db_obj.entity_type, db_obj.entity_id
        removed = self._repo.remove(db, id=id)
        if removed:
            db.commit()
            self._log_change(db, entity_type=entity_type, entity_id=entity_id, action="DELETE", username=user_email)
            return True
        return False

    def summarize(self, db: Session, *, entity_type: str, entity_id: str, month: date) -> CostSummary:
        currency, total, by_center, count = self._repo.summarize_for_entity(db, entity_type=entity_type, entity_id=entity_id, month=month)
        ym = f"{month.year:04d}-{month.month:02d}"
        return CostSummary(month=ym, currency=currency, total_cents=total, items_count=count, by_center=by_center)


