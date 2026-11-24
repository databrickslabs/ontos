from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from src.repositories.business_roles_repository import business_role_repo
from src.models.business_roles import BusinessRoleCreate, BusinessRoleUpdate, BusinessRoleRead
from src.db_models.business_roles import BusinessRoleDb
from src.common.errors import ConflictError, NotFoundError
from src.common.logging import get_logger

logger = get_logger(__name__)


class BusinessRolesManager:
    def __init__(self):
        self._repo = business_role_repo
        logger.debug("BusinessRolesManager initialized.")

    def _to_read(self, db_role: BusinessRoleDb) -> BusinessRoleRead:
        return BusinessRoleRead.model_validate(db_role)

    def create_role(self, db: Session, *, role_in: BusinessRoleCreate, current_user_id: str) -> BusinessRoleRead:
        """Creates a new business role."""
        existing = self._repo.get_by_name(db, name=role_in.name)
        if existing:
            raise ConflictError(f"Business role '{role_in.name}' already exists.")

        data = role_in.model_dump()
        data["created_by"] = current_user_id
        db_role = BusinessRoleDb(**data)

        try:
            db.add(db_role)
            db.flush()
            db.refresh(db_role)
            logger.info(f"Created business role '{db_role.name}' (id: {db_role.id})")
            return self._to_read(db_role)
        except IntegrityError as e:
            db.rollback()
            if "unique constraint" in str(e).lower():
                raise ConflictError(f"Business role '{role_in.name}' already exists.")
            raise

    def get_role(self, db: Session, role_id: UUID) -> Optional[BusinessRoleRead]:
        db_role = self._repo.get(db, role_id)
        if not db_role:
            return None
        return self._to_read(db_role)

    def get_all_roles(
        self, db: Session, *, skip: int = 0, limit: Optional[int] = None,
        category: Optional[str] = None, status: Optional[str] = None
    ) -> List[BusinessRoleRead]:
        db_roles = self._repo.get_multi_filtered(db, skip=skip, limit=limit, category=category, status=status)
        return [self._to_read(r) for r in db_roles]

    def update_role(self, db: Session, *, role_id: UUID, role_in: BusinessRoleUpdate, current_user_id: str) -> BusinessRoleRead:
        db_role = self._repo.get(db, role_id)
        if not db_role:
            raise NotFoundError(f"Business role '{role_id}' not found.")

        if role_in.name and role_in.name != db_role.name:
            existing = self._repo.get_by_name(db, name=role_in.name)
            if existing:
                raise ConflictError(f"Business role '{role_in.name}' already exists.")

        update_data = role_in.model_dump(exclude_unset=True)
        try:
            updated = self._repo.update(db=db, db_obj=db_role, obj_in=update_data)
            db.flush()
            db.refresh(updated)
            logger.info(f"Updated business role '{updated.name}' (id: {role_id})")
            return self._to_read(updated)
        except IntegrityError as e:
            db.rollback()
            if "unique constraint" in str(e).lower():
                raise ConflictError("Business role name conflict.")
            raise

    def delete_role(self, db: Session, *, role_id: UUID) -> BusinessRoleRead:
        db_role = self._repo.get(db, role_id)
        if not db_role:
            raise NotFoundError(f"Business role '{role_id}' not found.")

        read = self._to_read(db_role)
        self._repo.remove(db=db, id=role_id)
        logger.info(f"Deleted business role '{read.name}' (id: {role_id})")
        return read


# Singleton instance
business_roles_manager = BusinessRolesManager()
