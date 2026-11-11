from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from src.repositories.delivery_methods_repository import delivery_method_repo
from src.models.delivery_methods import DeliveryMethodCreate, DeliveryMethodUpdate, DeliveryMethodRead
from src.db_models.delivery_methods import DeliveryMethodDb
from src.common.errors import ConflictError, NotFoundError
from src.common.logging import get_logger

logger = get_logger(__name__)


class DeliveryMethodsManager:
    def __init__(self):
        self._repo = delivery_method_repo
        logger.debug("DeliveryMethodsManager initialized.")

    def _to_read(self, db_obj: DeliveryMethodDb) -> DeliveryMethodRead:
        return DeliveryMethodRead.model_validate(db_obj)

    def create(self, db: Session, *, obj_in: DeliveryMethodCreate, current_user_id: str) -> DeliveryMethodRead:
        existing = self._repo.get_by_name(db, name=obj_in.name)
        if existing:
            raise ConflictError(f"Delivery method '{obj_in.name}' already exists.")

        data = obj_in.model_dump()
        data["created_by"] = current_user_id
        db_obj = DeliveryMethodDb(**data)

        try:
            db.add(db_obj)
            db.flush()
            db.refresh(db_obj)
            logger.info(f"Created delivery method '{db_obj.name}' (id: {db_obj.id})")
            return self._to_read(db_obj)
        except IntegrityError as e:
            db.rollback()
            if "unique constraint" in str(e).lower():
                raise ConflictError(f"Delivery method '{obj_in.name}' already exists.")
            raise

    def get(self, db: Session, obj_id: UUID) -> Optional[DeliveryMethodRead]:
        db_obj = self._repo.get(db, obj_id)
        if not db_obj:
            return None
        return self._to_read(db_obj)

    def get_all(
        self, db: Session, *, skip: int = 0, limit: Optional[int] = None,
        category: Optional[str] = None, status: Optional[str] = None
    ) -> List[DeliveryMethodRead]:
        db_objs = self._repo.get_multi_filtered(db, skip=skip, limit=limit, category=category, status=status)
        return [self._to_read(o) for o in db_objs]

    def update(self, db: Session, *, obj_id: UUID, obj_in: DeliveryMethodUpdate, current_user_id: str) -> DeliveryMethodRead:
        db_obj = self._repo.get(db, obj_id)
        if not db_obj:
            raise NotFoundError(f"Delivery method '{obj_id}' not found.")

        if obj_in.name and obj_in.name != db_obj.name:
            existing = self._repo.get_by_name(db, name=obj_in.name)
            if existing:
                raise ConflictError(f"Delivery method '{obj_in.name}' already exists.")

        update_data = obj_in.model_dump(exclude_unset=True)
        try:
            updated = self._repo.update(db=db, db_obj=db_obj, obj_in=update_data)
            db.flush()
            db.refresh(updated)
            logger.info(f"Updated delivery method '{updated.name}' (id: {obj_id})")
            return self._to_read(updated)
        except IntegrityError as e:
            db.rollback()
            if "unique constraint" in str(e).lower():
                raise ConflictError("Delivery method name conflict.")
            raise

    def delete(self, db: Session, *, obj_id: UUID) -> DeliveryMethodRead:
        db_obj = self._repo.get(db, obj_id)
        if not db_obj:
            raise NotFoundError(f"Delivery method '{obj_id}' not found.")

        read = self._to_read(db_obj)
        self._repo.remove(db=db, id=obj_id)
        logger.info(f"Deleted delivery method '{read.name}' (id: {obj_id})")
        return read


delivery_methods_manager = DeliveryMethodsManager()
