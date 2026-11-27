from src.common.repository import CRUDBase
from src.db_models.data_domains import DataDomain
from src.models.data_domains import DataDomainCreate, DataDomainUpdate
from src.common.logging import get_logger
from sqlalchemy import text
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy.exc import SQLAlchemyError
from typing import Any, List, Optional
from uuid import UUID

logger = get_logger(__name__)

# Key of the Postgres advisory lock that serializes changes to the domain parent links
# (held until the transaction ends). A fixed value so every writer takes the same lock.
HIERARCHY_LOCK_KEY = 7_340_001_017

class DataDomainRepository(CRUDBase[DataDomain, DataDomainCreate, DataDomainUpdate]):
    def __init__(self):
        super().__init__(DataDomain)
        logger.info("DataDomainRepository initialized.")

    def create(self, db: Session, *, obj_in: DataDomainCreate) -> DataDomain:
        """Create domain, excluding tags field (tags handled by TagsManager)."""
        from uuid import UUID
        # Exclude tags since they're handled separately by TagsManager
        obj_in_data = obj_in.model_dump(exclude={"tags"})
        # Ensure created_by is set (for test scenarios where it might be missing)
        if "created_by" not in obj_in_data or obj_in_data["created_by"] is None:
            obj_in_data["created_by"] = "system"
        # Convert UUID objects to strings (SQLite needs strings, not UUID objects)
        if "parent_id" in obj_in_data and isinstance(obj_in_data["parent_id"], UUID):
            obj_in_data["parent_id"] = str(obj_in_data["parent_id"])
        db_obj = self.model(**obj_in_data)
        db.add(db_obj)
        db.flush()
        db.refresh(db_obj)
        return db_obj

    def update(self, db: Session, *, db_obj: DataDomain, obj_in: DataDomainUpdate | dict) -> DataDomain:
        """Update domain, excluding tags field (tags handled by TagsManager)."""
        from uuid import UUID
        if isinstance(obj_in, dict):
            update_data = {k: v for k, v in obj_in.items() if k != 'tags'}
        else:
            update_data = obj_in.model_dump(exclude_unset=True, exclude={"tags"})
        
        # Convert UUID objects to strings (SQLite needs strings, not UUID objects)
        if "parent_id" in update_data and isinstance(update_data["parent_id"], UUID):
            update_data["parent_id"] = str(update_data["parent_id"])
        
        for field, value in update_data.items():
            setattr(db_obj, field, value)
        
        db.add(db_obj)
        db.flush()
        db.refresh(db_obj)
        return db_obj

    def get_with_details(self, db: Session, id: UUID) -> Optional[DataDomain]:
        """Gets a single domain by ID, eager loading parent and children for count/details."""
        logger.debug(f"Fetching {self.model.__name__} with details for id: {id}")
        try:
            return (
                db.query(self.model)
                .options(
                    joinedload(self.model.parent),
                    selectinload(self.model.children)
                )
                .filter(self.model.id == str(id))
                .first()
            )
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching {self.model.__name__} with details by id {id}: {e}", exc_info=True)
            db.rollback()
            raise

    def get_multi_with_details(
        self, db: Session, *, skip: int = 0, limit: Optional[int] = None
    ) -> List[DataDomain]:
        """Gets multiple domains, eager loading parent and children for count/details."""
        logger.debug(f"Fetching multiple {self.model.__name__} with details, skip={skip}, limit={limit}")
        try:
            return (
                db.query(self.model)
                .options(
                    joinedload(self.model.parent),
                    selectinload(self.model.children)
                )
                .order_by(self.model.name)
                .offset(skip)
                .limit(limit)
                .all()
            )
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching multiple {self.model.__name__} with details: {e}", exc_info=True)
            db.rollback()
            raise

    # Add domain-specific methods here if needed later
    def get_by_name(self, db: Session, *, name: str) -> Optional[DataDomain]:
        logger.debug(f"Fetching {self.model.__name__} with name: {name}")
        try:
            return db.query(self.model).filter(self.model.name == name).first()
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching {self.model.__name__} by name {name}: {e}", exc_info=True)
            db.rollback()
            raise

    def get_by_name_normalized(self, db: Session, *, name: str) -> Optional[DataDomain]:
        """Case-insensitive, whitespace-trimmed name lookup.

        Used by import reconciliation so ``" finance "`` matches ``Finance`` rather
        than being left unassigned (or creating a near-duplicate under auto-create).
        """
        from sqlalchemy import func
        norm = (name or "").strip().lower()
        if not norm:
            return None
        try:
            return db.query(self.model).filter(func.lower(self.model.name) == norm).first()
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching {self.model.__name__} by normalized name {name!r}: {e}", exc_info=True)
            db.rollback()
            raise

    def lock_hierarchy(self, db: Session) -> None:
        """Serialize parent changes until this transaction commits or rolls back.

        A parent check reads the ancestor chain and the write comes after it: two
        reciprocal moves (A under B, B under A) would both pass the check. The
        advisory lock makes the second one wait and read the first one's committed
        link. Postgres only; on SQLite this is a no-op (one writer at a time).
        """
        if db.get_bind().dialect.name != 'postgresql':
            return
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {'key': HIERARCHY_LOCK_KEY})

    def get_parent_id(self, db: Session, id: Any) -> Optional[str]:
        """The stored parent id of a domain, read from the table (not the session cache)."""
        row = db.query(self.model.parent_id).filter(self.model.id == str(id)).first()
        return row[0] if row else None

# Singleton instance
data_domain_repo = DataDomainRepository() 