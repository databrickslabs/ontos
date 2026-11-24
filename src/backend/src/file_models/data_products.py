"""File model for Data Products YAML serialization."""

from contextlib import contextmanager
from typing import Any, Dict, Iterator, Tuple

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session, object_session

from .base import FileModel, register_file_model
from src.db_models.data_products import DataProductDb


@register_file_model
class DataProductFileModel(FileModel[DataProductDb]):
    """File model for Data Products.
    
    Each product is stored in its own YAML file.
    Filename format: {name}-{version}.yaml
    """
    
    ENTITY_TYPE = "DataProduct"
    SUBDIRECTORY = "products"
    ONE_FILE_PER_RECORD = True
    
    @classmethod
    def get_filename(cls, entity: DataProductDb) -> str:
        """Generate filename for a data product."""
        with _readable(entity) as (_session, product):
            return cls._filename(product)

    @staticmethod
    def _filename(entity: DataProductDb) -> str:
        name = entity.name or "product"
        safe_name = name.lower().replace(' ', '-').replace('/', '-')
        version = entity.version or "draft"
        safe_version = version.replace('.', '-')
        return f"{safe_name}-v{safe_version}.yaml"
    
    @classmethod
    def to_yaml_dict(cls, entity: DataProductDb) -> Dict[str, Any]:
        """The product's ODPS export (``GET /data-products/{id}/odps/export``): every
        field the import stores, in a document the ODPS import reads back."""
        with _readable(entity) as (session, product):
            return _odps_document(session, str(product.id))

    @classmethod
    def wrap_as_resource(cls, entity: DataProductDb, data: Dict[str, Any]) -> Dict[str, Any]:
        """Not wrapped: the ODPS document has its own ``apiVersion``, ``kind`` and ``id``,
        so the file stays one an ODPS import accepts."""
        return data


@contextmanager
def _readable(entity: DataProductDb) -> Iterator[Tuple[Session, DataProductDb]]:
    """The product with a session to read it in: its own, or for a detached product
    (its session closed, e.g. a delivery that runs after the request's session) a
    short-lived one of the app's database, where it is read again by its id."""
    session = object_session(entity)
    if session is not None:
        yield session, entity
        return
    state = sa_inspect(entity, raiseerr=False)
    identity = state.identity if state is not None else None
    if not identity:
        raise ValueError("A data product that isn't stored can't be serialized")
    from src.common.database import get_session_factory

    own = get_session_factory()()
    try:
        product = own.get(DataProductDb, identity[0])
        if product is None:
            raise ValueError(f"Data product {identity[0]} not found")
        yield own, product
    finally:
        own.close()


def _odps_document(session: Session, product_id: str) -> Dict[str, Any]:
    """The ODPS export of a stored product, read in ``session``."""
    from src.common.app_state import get_app_state_manager
    from src.controller.data_products_manager import DataProductsManager
    from src.controller.tags_manager import TagsManager

    manager = DataProductsManager(
        db=session, notifications_manager=get_app_state_manager('notifications_manager'),
        tags_manager=TagsManager(),
    )
    return manager.build_odps_export(product_id, db=session)
