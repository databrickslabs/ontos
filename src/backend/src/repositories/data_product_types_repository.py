"""Repository for data_product_types operations."""

from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.db_models.data_product_types import DataProductTypeDb

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

    def get_by_key(self, db: Session, key: str) -> DataProductTypeDb | None:
        return db.query(DataProductTypeDb).filter(DataProductTypeDb.key == key).first()

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
