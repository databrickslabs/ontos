from typing import List, Optional
from uuid import UUID
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from src.repositories.business_owners_repository import business_owner_repo
from src.repositories.business_roles_repository import business_role_repo
from src.models.business_owners import (
    BusinessOwnerCreate, BusinessOwnerUpdate, BusinessOwnerRead,
    BusinessOwnerRemove, BusinessOwnerHistory,
)
from src.db_models.business_owners import BusinessOwnerDb
from src.common.errors import ConflictError, NotFoundError
from src.common.logging import get_logger

logger = get_logger(__name__)


class BusinessOwnersManager:
    def __init__(self):
        self._owner_repo = business_owner_repo
        self._role_repo = business_role_repo
        logger.debug("BusinessOwnersManager initialized.")

    def _to_read(self, db_owner: BusinessOwnerDb) -> BusinessOwnerRead:
        read = BusinessOwnerRead.model_validate(db_owner)
        if db_owner.role:
            read.role_name = db_owner.role.name
        return read

    # --- Owner CRUD ---

    def assign_owner(self, db: Session, *, owner_in: BusinessOwnerCreate, current_user_id: str) -> BusinessOwnerRead:
        """Assigns an owner to an object with a specific role."""
        # Validate role exists
        db_role = self._role_repo.get(db, owner_in.role_id)
        if not db_role:
            raise NotFoundError(f"Business role '{owner_in.role_id}' not found.")

        # Check for duplicate active assignment
        existing = self._owner_repo.find_existing_active(
            db,
            object_type=owner_in.object_type,
            object_id=owner_in.object_id,
            user_email=owner_in.user_email,
            role_id=owner_in.role_id,
        )
        if existing:
            raise ConflictError(
                f"User '{owner_in.user_email}' is already assigned as '{db_role.name}' "
                f"for {owner_in.object_type}:{owner_in.object_id}."
            )

        data = owner_in.model_dump()
        data["created_by"] = current_user_id
        db_owner = BusinessOwnerDb(**data)

        try:
            db.add(db_owner)
            db.flush()
            db.refresh(db_owner)
            # Reload with role
            db_owner = self._owner_repo.get_with_role(db, db_owner.id)
            logger.info(
                f"Assigned '{owner_in.user_email}' as '{db_role.name}' "
                f"for {owner_in.object_type}:{owner_in.object_id}"
            )
            return self._to_read(db_owner)
        except IntegrityError as e:
            db.rollback()
            logger.error(f"Integrity error assigning owner: {e}")
            raise

    def remove_owner(
        self, db: Session, *, owner_id: UUID, removal: BusinessOwnerRemove, current_user_id: str
    ) -> BusinessOwnerRead:
        """Deactivates an owner assignment (soft delete with history)."""
        db_owner = self._owner_repo.get_with_role(db, owner_id)
        if not db_owner:
            raise NotFoundError(f"Owner assignment '{owner_id}' not found.")

        if not db_owner.is_active:
            raise ConflictError(f"Owner assignment '{owner_id}' is already inactive.")

        db_owner.is_active = False
        db_owner.removed_at = datetime.now(timezone.utc)
        db_owner.removal_reason = removal.removal_reason

        db.flush()
        db.refresh(db_owner)
        logger.info(f"Deactivated owner assignment {owner_id}")
        return self._to_read(db_owner)

    def update_owner(
        self, db: Session, *, owner_id: UUID, owner_in: BusinessOwnerUpdate, current_user_id: str
    ) -> BusinessOwnerRead:
        """Updates an existing owner assignment."""
        db_owner = self._owner_repo.get_with_role(db, owner_id)
        if not db_owner:
            raise NotFoundError(f"Owner assignment '{owner_id}' not found.")

        if owner_in.role_id:
            db_role = self._role_repo.get(db, owner_in.role_id)
            if not db_role:
                raise NotFoundError(f"Business role '{owner_in.role_id}' not found.")

        update_data = owner_in.model_dump(exclude_unset=True)

        # If setting is_active to False, handle as removal
        if update_data.get("is_active") is False and db_owner.is_active:
            db_owner.removed_at = datetime.now(timezone.utc)
            if "removal_reason" in update_data:
                db_owner.removal_reason = update_data.pop("removal_reason")
            update_data.pop("removal_reason", None)

        for field, value in update_data.items():
            if hasattr(db_owner, field):
                setattr(db_owner, field, value)

        db.flush()
        db.refresh(db_owner)
        db_owner = self._owner_repo.get_with_role(db, db_owner.id)
        logger.info(f"Updated owner assignment {owner_id}")
        return self._to_read(db_owner)

    def get_owner(self, db: Session, owner_id: UUID) -> Optional[BusinessOwnerRead]:
        db_owner = self._owner_repo.get_with_role(db, owner_id)
        if not db_owner:
            return None
        return self._to_read(db_owner)

    def get_owners_for_object(
        self, db: Session, *, object_type: str, object_id: str, active_only: bool = True
    ) -> List[BusinessOwnerRead]:
        """Gets all owners for a specific object."""
        db_owners = self._owner_repo.get_for_object(
            db, object_type=object_type, object_id=object_id, active_only=active_only
        )
        return [self._to_read(o) for o in db_owners]

    def get_owner_history(self, db: Session, *, object_type: str, object_id: str) -> BusinessOwnerHistory:
        """Gets the full ownership history (current + previous) for an object."""
        all_owners = self._owner_repo.get_for_object(
            db, object_type=object_type, object_id=object_id, active_only=False
        )
        current = [self._to_read(o) for o in all_owners if o.is_active]
        previous = [self._to_read(o) for o in all_owners if not o.is_active]
        return BusinessOwnerHistory(
            object_type=object_type,
            object_id=object_id,
            current_owners=current,
            previous_owners=previous,
        )

    def get_ownerships_for_user(
        self, db: Session, *, user_email: str, active_only: bool = True
    ) -> List[BusinessOwnerRead]:
        """Gets all ownership assignments for a specific user."""
        db_owners = self._owner_repo.get_by_user(
            db, user_email=user_email, active_only=active_only
        )
        return [self._to_read(o) for o in db_owners]

    def get_all_owners(
        self, db: Session, *, skip: int = 0, limit: Optional[int] = None,
        object_type: Optional[str] = None, role_id: Optional[UUID] = None,
        active_only: bool = True
    ) -> List[BusinessOwnerRead]:
        """Gets all owner assignments with optional filters."""
        db_owners = self._owner_repo.get_multi_filtered(
            db, skip=skip, limit=limit,
            object_type=object_type, role_id=role_id, active_only=active_only,
        )
        return [self._to_read(o) for o in db_owners]


# Singleton instance
business_owners_manager = BusinessOwnersManager()
