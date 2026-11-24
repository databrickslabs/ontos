from __future__ import annotations
from datetime import date
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, cast, Date

from src.common.repository import CRUDBase
from src.db_models.costs import CostItemDb
from src.models.costs import CostItemCreate, CostItemUpdate


class CostItemsRepository(CRUDBase[CostItemDb, CostItemCreate, CostItemUpdate]):
    def remove_all_for_entity(self, db: Session, *, entity_type: str, entity_id: str) -> int:
        """Delete every cost item of an entity (used when the entity is deleted)."""
        return (
            db.query(CostItemDb)
            .filter(CostItemDb.entity_type == entity_type, CostItemDb.entity_id == entity_id)
            .delete(synchronize_session=False)
        )

    def list_for_entity(
        self,
        db: Session,
        *,
        entity_type: str,
        entity_id: str,
        month: Optional[date] = None,
    ) -> List[CostItemDb]:
        q = (
            db.query(CostItemDb)
            .filter(CostItemDb.entity_type == entity_type, CostItemDb.entity_id == entity_id)
            .order_by(CostItemDb.start_month.asc())
        )
        if month is not None:
            month_start = date(month.year, month.month, 1)
            # month_end: next month first - 1 day not needed; inclusive check with month_start only
            q = q.filter(
                and_(
                    CostItemDb.start_month <= month_start,
                    or_(CostItemDb.end_month == None, CostItemDb.end_month >= month_start),
                )
            )
        return q.all()

    def summarize_for_entity(
        self,
        db: Session,
        *,
        entity_type: str,
        entity_id: str,
        month: date,
    ) -> Tuple[str, int, Dict[str, int], int]:
        month_start = date(month.year, month.month, 1)
        rows = (
            db.query(CostItemDb.cost_center, func.sum(CostItemDb.amount_cents).label("sum_cents"), func.count(CostItemDb.id))
            .filter(
                CostItemDb.entity_type == entity_type,
                CostItemDb.entity_id == entity_id,
                CostItemDb.start_month <= month_start,
                or_(CostItemDb.end_month == None, CostItemDb.end_month >= month_start),
            )
            .group_by(CostItemDb.cost_center)
            .all()
        )
        by_center: Dict[str, int] = {center: int(sum_cents or 0) for center, sum_cents, _ in rows}
        total = sum(by_center.values())
        # Currency: pick first item's currency for summary
        currency_row = (
            db.query(CostItemDb.currency)
            .filter(
                CostItemDb.entity_type == entity_type,
                CostItemDb.entity_id == entity_id,
                CostItemDb.start_month <= month_start,
                or_(CostItemDb.end_month == None, CostItemDb.end_month >= month_start),
            )
            .limit(1)
            .first()
        )
        currency = currency_row[0] if currency_row else "USD"
        count_row = (
            db.query(func.count(CostItemDb.id))
            .filter(
                CostItemDb.entity_type == entity_type,
                CostItemDb.entity_id == entity_id,
                CostItemDb.start_month <= month_start,
                or_(CostItemDb.end_month == None, CostItemDb.end_month >= month_start),
            )
            .scalar()
        )
        return currency, int(total), by_center, int(count_row or 0)


cost_items_repo = CostItemsRepository(CostItemDb)


