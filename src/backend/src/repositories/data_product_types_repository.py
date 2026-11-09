"""Repository for data_product_types operations."""

from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.db_models.data_product_types import DataProductTypeDb
from src.db_models.data_products import DataProductDb

logger = get_logger(__name__)


# Seeded on new installs (and by the b8_data_product_types migration).
# Seeded types cannot be hard-deleted.
SEEDED_TYPES = [
    {
        "key": "source-aligned",
        "label": "Source-Aligned",
        "description": "Exposes data from a source system with minimal transformation",
        "icon": "database",
        "sort_order": 1,
        "is_default": True,
    },
    {
        "key": "aggregate",
        "label": "Aggregate",
        "description": "Combines several products into a new, reusable view",
        "icon": "layers",
        "sort_order": 2,
    },
    {
        "key": "consumer-aligned",
        "label": "Consumer-Aligned",
        "description": "Shaped for a specific consumer or use case",
        "icon": "users",
        "sort_order": 3,
    },
    {
        "key": "source",
        "label": "Source",
        "description": "Raw source of data entering the platform",
        "icon": "arrow-down-to-line",
        "sort_order": 4,
    },
    {
        "key": "sink",
        "label": "Sink",
        "description": "Final destination of data leaving the platform",
        "icon": "arrow-up-from-line",
        "sort_order": 5,
    },
]
SEEDED_TYPE_KEYS = frozenset(t["key"] for t in SEEDED_TYPES)


class DataProductTypesRepository:
    def get_all_ordered(self, db: Session) -> list[DataProductTypeDb]:
        return (
            db.query(DataProductTypeDb)
            .order_by(DataProductTypeDb.sort_order, DataProductTypeDb.key)
            .all()
        )

    def get_all_active_ordered(self, db: Session) -> list[DataProductTypeDb]:
        return (
            db.query(DataProductTypeDb)
            .filter(DataProductTypeDb.is_active.is_(True))
            .order_by(DataProductTypeDb.sort_order, DataProductTypeDb.key)
            .all()
        )

    def get_by_id(self, db: Session, type_id: UUID) -> DataProductTypeDb | None:
        return db.get(DataProductTypeDb, type_id)

    def get_by_key(self, db: Session, key: str) -> DataProductTypeDb | None:
        return db.query(DataProductTypeDb).filter(DataProductTypeDb.key == key).first()

    def get_default(self, db: Session) -> DataProductTypeDb | None:
        """The active type marked as default, if there is one."""
        return (
            db.query(DataProductTypeDb)
            .filter(DataProductTypeDb.is_default.is_(True), DataProductTypeDb.is_active.is_(True))
            .order_by(DataProductTypeDb.sort_order, DataProductTypeDb.key)
            .first()
        )

    def create(
        self,
        db: Session,
        *,
        key: str,
        label: str,
        sort_order: int,
        description: str | None = None,
        icon: str | None = None,
        color: str | None = None,
        is_active: bool = True,
        is_default: bool = False,
        is_imported: bool = False,
    ) -> DataProductTypeDb:
        obj = DataProductTypeDb(
            key=key,
            label=label,
            sort_order=sort_order,
            description=description,
            icon=icon,
            color=color,
            is_active=is_active,
            is_default=is_default,
            is_imported=is_imported,
        )
        db.add(obj)
        db.flush()
        db.refresh(obj)
        logger.info(f"Created data product type '{key}' at order {sort_order}")
        return obj

    def update(self, db: Session, *, db_obj: DataProductTypeDb, update_data: dict) -> DataProductTypeDb:
        for field, value in update_data.items():
            if field in ("id", "key"):
                continue
            setattr(db_obj, field, value)
        db.flush()
        db.refresh(db_obj)
        logger.info("Updated data product type '%s'", db_obj.key)
        return db_obj

    def delete(self, db: Session, *, db_obj: DataProductTypeDb) -> None:
        db.delete(db_obj)
        db.flush()
        logger.info("Deleted data product type '%s'", db_obj.key)

    def clear_default(self, db: Session, *, except_id: UUID | None = None) -> None:
        """Unset is_default on every type other than except_id."""
        query = db.query(DataProductTypeDb).filter(DataProductTypeDb.is_default.is_(True))
        if except_id is not None:
            query = query.filter(DataProductTypeDb.id != except_id)
        query.update({DataProductTypeDb.is_default: False}, synchronize_session="fetch")
        db.flush()

    def reorder(self, db: Session, *, order_map: dict[UUID, int]) -> list[DataProductTypeDb]:
        """Set sort_order from {type id: new order}; ids not in the map keep theirs."""
        for obj in self.get_all_ordered(db):
            new_order = order_map.get(obj.id)
            if new_order is not None:
                obj.sort_order = new_order
        db.flush()
        return self.get_all_ordered(db)

    def get_max_order(self, db: Session) -> int:
        return db.query(func.max(DataProductTypeDb.sort_order)).scalar() or 0

    def count_products_using(self, db: Session, type_id: UUID) -> int:
        return (
            db.query(func.count(DataProductDb.id))
            .filter(DataProductDb.product_type_id == type_id)
            .scalar()
            or 0
        )

    def usage_counts(self, db: Session) -> dict[UUID, int]:
        """Number of data products per type id (types with no products are left out)."""
        rows = (
            db.query(DataProductDb.product_type_id, func.count(DataProductDb.id))
            .filter(DataProductDb.product_type_id.isnot(None))
            .group_by(DataProductDb.product_type_id)
            .all()
        )
        return dict(rows)

    def is_empty(self, db: Session) -> bool:
        return db.query(DataProductTypeDb).count() == 0

    def seed_defaults(self, db: Session) -> list[DataProductTypeDb]:
        """Seed default data product types if table is empty."""
        if not self.is_empty(db):
            return self.get_all_ordered(db)

        created = [self.create(db, **t) for t in SEEDED_TYPES]
        logger.info(f"Seeded default data product types: {', '.join(sorted(SEEDED_TYPE_KEYS))}")
        return created


data_product_types_repo = DataProductTypesRepository()
