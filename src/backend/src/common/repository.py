from typing import Any, Dict, Generic, List, Optional, Type, TypeVar, Union

from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select, func, String as SAString
from uuid import UUID

from src.common.database import Base
from .logging import get_logger

logger = get_logger(__name__)

# Define TypeVars for generic repository
ModelType = TypeVar("ModelType", bound=Base)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)

class CRUDBase(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    """Generic CRUD base class for SQLAlchemy models."""
    def __init__(self, model: Type[ModelType]):
        """
        CRUD object with default methods to Create, Read, Update, Delete (CRUD).

        **Parameters**

        * `model`: A SQLAlchemy model class
        * `schema`: A Pydantic model (schema) class
        """
        self.model = model

    def get(self, db: Session, id: Any) -> Optional[ModelType]:
        logger.debug(f"Fetching {self.model.__name__} with id: {id}")
        try:
            # Normalize UUID to string if model primary key is String
            normalized_id = id
            try:
                model_id_column = getattr(self.model, 'id').property.columns[0]
                if isinstance(model_id_column.type, SAString) and isinstance(id, UUID):
                    normalized_id = str(id)
            except Exception:
                # If any introspection fails, fall back to original id
                normalized_id = id

            return db.query(self.model).filter(self.model.id == normalized_id).first()
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching {self.model.__name__} by id {id}: {e}", exc_info=True)
            db.rollback() # Ensure rollback on read error if transaction started
            raise

    def get_multi(
        self, db: Session, *, skip: int = 0, limit: int = 100
    ) -> List[ModelType]:
        logger.debug(f"Fetching multiple {self.model.__name__} with skip: {skip}, limit: {limit}")
        try:
            return db.query(self.model).offset(skip).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching multiple {self.model.__name__}: {e}", exc_info=True)
            db.rollback()
            raise

    def create(self, db: Session, *, obj_in: Union[CreateSchemaType, Dict[str, Any]]) -> ModelType:
        logger.debug(f"Creating new {self.model.__name__}")
        if isinstance(obj_in, dict):
            obj_in_data = obj_in
        else:
            obj_in_data = obj_in.dict()
        db_obj = self.model(**obj_in_data)  # type: ignore
        try:
            db.add(db_obj)
            # We commit in the get_db dependency function
            # db.commit()
            db.flush() # Flush to get generated values like ID, defaults
            db.refresh(db_obj)
            logger.info(f"Successfully created {self.model.__name__} with id: {db_obj.id}")
            return db_obj
        except SQLAlchemyError as e:
            logger.error(f"Database error creating {self.model.__name__}: {e}", exc_info=True)
            db.rollback()
            raise

    def update(
        self, db: Session, *, db_obj: ModelType, obj_in: Union[UpdateSchemaType, Dict[str, Any]]
    ) -> ModelType:
        logger.debug(f"Updating {self.model.__name__} with id: {db_obj.id}")
        if isinstance(obj_in, dict):
            update_data = obj_in
        else:
            update_data = obj_in.dict(exclude_unset=True)

        # Never allow primary key changes via generic update
        if 'id' in update_data:
            update_data.pop('id', None)

        try:
            for field, value in update_data.items():
                if hasattr(db_obj, field):
                    setattr(db_obj, field, value)
                else:
                    logger.warning(f"Attempted to update non-existent field '{field}' on {self.model.__name__}")
            
            db.add(db_obj) # Add the updated object to the session
            # db.commit()
            db.flush()
            db.refresh(db_obj)
            logger.info(f"Successfully updated {self.model.__name__} with id: {db_obj.id}")
            return db_obj
        except SQLAlchemyError as e:
            logger.error(f"Database error updating {self.model.__name__} (id: {db_obj.id}): {e}", exc_info=True)
            db.rollback()
            raise

    def remove(self, db: Session, *, id: Any) -> Optional[ModelType]:
        logger.debug(f"Deleting {self.model.__name__} with id: {id}")
        try:
            # Normalize UUID to string if model primary key is String
            normalized_id = id
            try:
                model_id_column = getattr(self.model, 'id').property.columns[0]
                if isinstance(model_id_column.type, SAString) and isinstance(id, UUID):
                    normalized_id = str(id)
            except Exception:
                normalized_id = id

            obj = db.query(self.model).get(normalized_id)
            if obj:
                db.delete(obj)
                # db.commit()
                db.flush()
                logger.info(f"Successfully deleted {self.model.__name__} with id: {id}")
                return obj
            else:
                logger.warning(f"Attempted to delete non-existent {self.model.__name__} with id: {id}")
                return None
        except SQLAlchemyError as e:
            logger.error(f"Database error deleting {self.model.__name__} (id: {id}): {e}", exc_info=True)
            db.rollback()
            raise

    def count(self, db: Session) -> int:
        """Returns the total number of items in the table."""
        logger.debug(f"Counting {self.model.__name__} entries")
        try:
            # Use func.count() for efficient counting
            count_query = select(func.count()).select_from(self.model)
            total = db.execute(count_query).scalar_one()
            logger.debug(f"Found {total} {self.model.__name__} entries")
            return total
        except SQLAlchemyError as e:
            logger.error(f"Database error counting {self.model.__name__}: {e}", exc_info=True)
            db.rollback()
            raise

    def is_empty(self, db: Session) -> bool:
        """Checks if the table associated with the model is empty."""
        return self.count(db) == 0 