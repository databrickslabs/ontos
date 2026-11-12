from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session, selectinload
from sqlalchemy.exc import SQLAlchemyError

from src.common.repository import CRUDBase
from src.db_models.business_owners import BusinessOwnerDb
from src.models.business_owners import BusinessOwnerCreate, BusinessOwnerUpdate
from src.common.logging import get_logger

logger = get_logger(__name__)


class BusinessOwnerRepository(CRUDBase[BusinessOwnerDb, BusinessOwnerCreate, BusinessOwnerUpdate]):
    def __init__(self):
        super().__init__(BusinessOwnerDb)
        logger.info("BusinessOwnerRepository initialized.")

    def get_with_role(self, db: Session, id: UUID) -> Optional[BusinessOwnerDb]:
        """Gets a single owner by ID, eager loading the role."""
        try:
            return (
                db.query(self.model)
                .options(selectinload(self.model.role))
                .filter(self.model.id == id)
                .first()
            )
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching owner with role by id {id}: {e}", exc_info=True)
            db.rollback()
            raise

    def get_for_object(
        self, db: Session, *, object_type: str, object_id: str, active_only: bool = True
    ) -> List[BusinessOwnerDb]:
        """Gets all owners for a specific object."""
        try:
            query = (
                db.query(self.model)
                .options(selectinload(self.model.role))
                .filter(
                    self.model.object_type == object_type,
                    self.model.object_id == object_id,
                )
                .order_by(self.model.assigned_at.desc())
            )
            if active_only:
                query = query.filter(self.model.is_active.is_(True))
            return query.all()
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching owners for {object_type}:{object_id}: {e}", exc_info=True)
            db.rollback()
            raise

    def get_by_user(
        self, db: Session, *, user_email: str, active_only: bool = True
    ) -> List[BusinessOwnerDb]:
        """Gets all ownership assignments for a specific user."""
        try:
            query = (
                db.query(self.model)
                .options(selectinload(self.model.role))
                .filter(self.model.user_email == user_email)
                .order_by(self.model.object_type, self.model.assigned_at.desc())
            )
            if active_only:
                query = query.filter(self.model.is_active.is_(True))
            return query.all()
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching ownerships for user {user_email}: {e}", exc_info=True)
            db.rollback()
            raise

    def find_existing_active(
        self, db: Session, *, object_type: str, object_id: str, user_email: str, role_id: UUID
    ) -> Optional[BusinessOwnerDb]:
        """Checks if an active ownership assignment already exists."""
        try:
            return (
                db.query(self.model)
                .filter(
                    self.model.object_type == object_type,
                    self.model.object_id == object_id,
                    self.model.user_email == user_email,
                    self.model.role_id == role_id,
                    self.model.is_active.is_(True),
                )
                .first()
            )
        except SQLAlchemyError as e:
            logger.error(f"Database error checking existing ownership: {e}", exc_info=True)
            db.rollback()
            raise

    def get_multi_filtered(
        self, db: Session, *, skip: int = 0, limit: Optional[int] = None,
        object_type: Optional[str] = None, role_id: Optional[UUID] = None,
        active_only: bool = True
    ) -> List[BusinessOwnerDb]:
        """Gets multiple owner assignments with optional filters."""
        try:
            query = (
                db.query(self.model)
                .options(selectinload(self.model.role))
                .order_by(self.model.object_type, self.model.object_id, self.model.assigned_at.desc())
            )
            if object_type:
                query = query.filter(self.model.object_type == object_type)
            if role_id:
                query = query.filter(self.model.role_id == role_id)
            if active_only:
                query = query.filter(self.model.is_active.is_(True))
            return query.offset(skip).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching owner assignments: {e}", exc_info=True)
            db.rollback()
            raise


# Singleton instance
business_owner_repo = BusinessOwnerRepository()
