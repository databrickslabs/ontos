from src.common.repository import CRUDBase
from src.db_models.data_domains import DataDomain
from src.models.data_domains import DataDomainCreate, DataDomainUpdate
from src.common.logging import get_logger
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Optional
from uuid import UUID

logger = get_logger(__name__)

class DataDomainRepository(CRUDBase[DataDomain, DataDomainCreate, DataDomainUpdate]):
    def __init__(self):
        super().__init__(DataDomain)
        logger.info("DataDomainRepository initialized.")

    def create(self, db: Session, *, obj_in: DataDomainCreate) -> DataDomain:
        """Create domain, excluding tags field (tags handled by TagsManager)."""
        from uuid import UUID
        # Exclude tags since they're handled separately by TagsManager
        obj_in_data = obj_in.model_dump(exclude={"tags"})
        # Optional caller-provided id (API only): drop a null id so the column
        # default generates one; stringify a provided UUID for the String PK.
        if obj_in_data.get("id") is None:
            obj_in_data.pop("id", None)
        elif isinstance(obj_in_data["id"], UUID):
            obj_in_data["id"] = str(obj_in_data["id"])
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
        self, db: Session, *, skip: int = 0, limit: int = 100
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

# Singleton instance
data_domain_repo = DataDomainRepository() 