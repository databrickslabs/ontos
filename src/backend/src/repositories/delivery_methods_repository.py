from typing import List, Optional

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from src.common.repository import CRUDBase
from src.db_models.delivery_methods import DeliveryMethodDb
from src.models.delivery_methods import DeliveryMethodCreate, DeliveryMethodUpdate
from src.common.logging import get_logger

logger = get_logger(__name__)


class DeliveryMethodRepository(CRUDBase[DeliveryMethodDb, DeliveryMethodCreate, DeliveryMethodUpdate]):
    def __init__(self):
        super().__init__(DeliveryMethodDb)
        logger.info("DeliveryMethodRepository initialized.")

    def get_by_name(self, db: Session, *, name: str) -> Optional[DeliveryMethodDb]:
        """Gets a delivery method by name."""
        try:
            return db.query(self.model).filter(self.model.name == name).first()
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching delivery method by name {name}: {e}", exc_info=True)
            db.rollback()
            raise

    def get_multi_filtered(
        self, db: Session, *, skip: int = 0, limit: Optional[int] = None,
        category: Optional[str] = None, status: Optional[str] = None
    ) -> List[DeliveryMethodDb]:
        """Gets multiple delivery methods with optional filters."""
        try:
            query = db.query(self.model).order_by(self.model.name)
            if category:
                query = query.filter(self.model.category == category)
            if status:
                query = query.filter(self.model.status == status)
            return query.offset(skip).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching delivery methods: {e}", exc_info=True)
            db.rollback()
            raise


delivery_method_repo = DeliveryMethodRepository()
