"""File model for Data Products YAML serialization."""

from typing import Any, Dict

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
        name = entity.name or "product"
        safe_name = name.lower().replace(' ', '-').replace('/', '-')
        version = entity.version or "draft"
        safe_version = version.replace('.', '-')
        return f"{safe_name}-v{safe_version}.yaml"
    
    @classmethod
    def to_yaml_dict(cls, entity: DataProductDb) -> Dict[str, Any]:
        """The product's ODPS export (``GET /data-products/{id}/odps/export``): every
        field the import stores, in a document the ODPS import reads back."""
        session = object_session(entity)
        if session is None:
            raise ValueError("A data product is serialized in the session it was read in")
        return _odps_document(session, str(entity.id))

    @classmethod
    def wrap_as_resource(cls, entity: DataProductDb, data: Dict[str, Any]) -> Dict[str, Any]:
        """Not wrapped: the ODPS document has its own ``apiVersion``, ``kind`` and ``id``,
        so the file stays one an ODPS import accepts."""
        return data


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
