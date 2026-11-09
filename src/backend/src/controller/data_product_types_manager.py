"""Business rules for admin-configurable data product types.

- `key` is set on create and never changes; it's the value used in ODPS.
- Label, description, icon, colour, order and active flag can be changed.
- At most one type is the default; making a type the default unsets the old one.
- The default type can't be deactivated, and an inactive type can't be the default.
- A type can't be deleted while products use it, and the seeded types can
  never be deleted (deactivate them instead).
"""

from uuid import UUID

from sqlalchemy.orm import Session

from src.common.api_errors import CodedValueError
from src.common.logging import get_logger
from src.db_models.data_product_types import DataProductTypeDb
from src.models.data_product_types import (
    DataProductTypeCreate,
    DataProductTypeRead,
    DataProductTypeUpdate,
)
from src.repositories.data_product_types_repository import (
    SEEDED_TYPE_KEYS,
    DataProductTypesRepository,
    data_product_types_repo,
)

logger = get_logger(__name__)


class DataProductTypeNotFoundError(CodedValueError):
    """No type with the given id. Routes answer 404."""

    code = 'data_product_type_not_found'

    def __init__(self, type_id: UUID):
        super().__init__(f"Data product type {type_id} not found", typeId=str(type_id))


class DataProductTypeConflictError(CodedValueError):
    """A change the type rules don't allow. Routes answer 409."""


class DataProductTypeKeyExistsError(DataProductTypeConflictError):
    code = 'data_product_type_key_exists'

    def __init__(self, key: str):
        super().__init__(f"A data product type with key '{key}' already exists", key=key)


class DataProductTypeInUseError(DataProductTypeConflictError):
    code = 'data_product_type_in_use'

    def __init__(self, key: str, count: int):
        super().__init__(
            f"Data product type '{key}' is used by {count} data product(s); "
            "deactivate it instead of deleting it",
            key=key,
            count=count,
        )


class SeededDataProductTypeDeleteError(DataProductTypeConflictError):
    code = 'data_product_type_seeded'

    def __init__(self, key: str):
        super().__init__(
            f"Data product type '{key}' is a built-in type and can't be deleted; "
            "deactivate it instead",
            key=key,
        )


class DefaultDataProductTypeInactiveError(DataProductTypeConflictError):
    code = 'data_product_type_default_inactive'

    def __init__(self, key: str):
        super().__init__(
            f"Data product type '{key}' can't be both the default and inactive; "
            "make another type the default first",
            key=key,
        )


class DataProductTypesManager:
    """Stateless; every method takes the session. Callers commit."""

    def __init__(self, repo: DataProductTypesRepository = data_product_types_repo):
        self._repo = repo

    # --- Reads ---

    def list_types(self, db: Session, *, active_only: bool = False) -> list[DataProductTypeRead]:
        types = (
            self._repo.get_all_active_ordered(db) if active_only else self._repo.get_all_ordered(db)
        )
        counts = self._repo.usage_counts(db)
        return [self._to_read(t, counts.get(t.id, 0)) for t in types]

    def get_type(self, db: Session, type_id: UUID) -> DataProductTypeRead:
        db_obj = self._get_or_raise(db, type_id)
        return self._to_read(db_obj, self._repo.count_products_using(db, type_id))

    # --- Writes ---

    def create_type(self, db: Session, body: DataProductTypeCreate) -> DataProductTypeRead:
        if self._repo.get_by_key(db, body.key) is not None:
            raise DataProductTypeKeyExistsError(body.key)
        if body.is_default and not body.is_active:
            raise DefaultDataProductTypeInactiveError(body.key)

        sort_order = body.sort_order
        if sort_order is None:
            sort_order = self._repo.get_max_order(db) + 1

        if body.is_default:
            self._repo.clear_default(db)

        db_obj = self._repo.create(
            db,
            key=body.key,
            label=body.label,
            sort_order=sort_order,
            description=body.description,
            icon=body.icon,
            color=body.color,
            is_active=body.is_active,
            is_default=body.is_default,
        )
        return self._to_read(db_obj, 0)

    def update_type(
        self, db: Session, type_id: UUID, body: DataProductTypeUpdate
    ) -> DataProductTypeRead:
        db_obj = self._get_or_raise(db, type_id)
        update_data = body.model_dump(exclude_unset=True)
        # None means "not changing" for the non-nullable fields.
        for field in ("label", "sort_order", "is_active", "is_default"):
            if field in update_data and update_data[field] is None:
                del update_data[field]

        will_be_active = update_data.get("is_active", db_obj.is_active)
        will_be_default = update_data.get("is_default", db_obj.is_default)
        if will_be_default and not will_be_active:
            raise DefaultDataProductTypeInactiveError(db_obj.key)

        if update_data.get("is_default") and not db_obj.is_default:
            self._repo.clear_default(db, except_id=db_obj.id)

        if update_data:
            db_obj = self._repo.update(db, db_obj=db_obj, update_data=update_data)
        return self._to_read(db_obj, self._repo.count_products_using(db, type_id))

    def reorder_types(self, db: Session, order_map: dict[UUID, int]) -> list[DataProductTypeRead]:
        for type_id in order_map:
            self._get_or_raise(db, type_id)
        self._repo.reorder(db, order_map=order_map)
        return self.list_types(db)

    def delete_type(self, db: Session, type_id: UUID) -> None:
        db_obj = self._get_or_raise(db, type_id)
        if db_obj.key in SEEDED_TYPE_KEYS:
            raise SeededDataProductTypeDeleteError(db_obj.key)
        count = self._repo.count_products_using(db, type_id)
        if count:
            raise DataProductTypeInUseError(db_obj.key, count)
        self._repo.delete(db, db_obj=db_obj)

    # --- Helpers ---

    def _get_or_raise(self, db: Session, type_id: UUID) -> DataProductTypeDb:
        db_obj = self._repo.get_by_id(db, type_id)
        if db_obj is None:
            raise DataProductTypeNotFoundError(type_id)
        return db_obj

    @staticmethod
    def _to_read(db_obj: DataProductTypeDb, usage_count: int) -> DataProductTypeRead:
        read = DataProductTypeRead.model_validate(db_obj)
        read.is_seeded = db_obj.key in SEEDED_TYPE_KEYS
        read.usage_count = usage_count
        return read


data_product_types_manager = DataProductTypesManager()
