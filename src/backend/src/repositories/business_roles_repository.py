from typing import List, Optional

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from src.common.repository import CRUDBase
from src.db_models.business_roles import BusinessRoleDb
from src.models.business_roles import BusinessRoleCreate, BusinessRoleUpdate
from src.common.logging import get_logger

logger = get_logger(__name__)


class BusinessRoleRepository(CRUDBase[BusinessRoleDb, BusinessRoleCreate, BusinessRoleUpdate]):
    def __init__(self):
        super().__init__(BusinessRoleDb)
        logger.info("BusinessRoleRepository initialized.")

    def get_by_name(self, db: Session, *, name: str) -> Optional[BusinessRoleDb]:
        """Gets a business role by name."""
        try:
            return db.query(self.model).filter(self.model.name == name).first()
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching business role by name {name}: {e}", exc_info=True)
            db.rollback()
            raise

    def get_multi_filtered(
        self, db: Session, *, skip: int = 0, limit: Optional[int] = None,
        category: Optional[str] = None, status: Optional[str] = None
    ) -> List[BusinessRoleDb]:
        """Gets multiple business roles with optional filters."""
        try:
            query = db.query(self.model).order_by(self.model.name)
            if category:
                query = query.filter(self.model.category == category)
            if status:
                query = query.filter(self.model.status == status)
            return query.offset(skip).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching business roles: {e}", exc_info=True)
            db.rollback()
            raise


# Singleton instance
business_role_repo = BusinessRoleRepository()
