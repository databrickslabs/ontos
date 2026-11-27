"""API routes for managing data product types (Settings → Reference Data)."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.common.authorization import PermissionChecker
from src.common.dependencies import DBSessionDep
from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger
from src.controller.data_product_types_manager import (
    DataProductTypeConflictError,
    DataProductTypeNotFoundError,
    data_product_types_manager,
)
from src.models.data_product_types import (
    DataProductTypeCreate,
    DataProductTypeRead,
    DataProductTypeReorder,
    DataProductTypeUpdate,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["Data Product Types"])

SETTINGS_FEATURE_ID = "settings-data-product-types"

_write_access = Depends(PermissionChecker(SETTINGS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))


def _raise_for(e: Exception) -> None:
    """Turn a manager error into the matching HTTP error (the message is safe to show)."""
    if isinstance(e, DataProductTypeNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    if isinstance(e, DataProductTypeConflictError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    raise e


@router.get("/data-product-types", response_model=list[DataProductTypeRead])
async def list_data_product_types(
    db: DBSessionDep,
    active_only: bool = Query(False, description="Only return active types (for pickers)"),
):
    """List data product types ordered by sort_order."""
    return data_product_types_manager.list_types(db, active_only=active_only)


@router.post(
    "/data-product-types",
    response_model=DataProductTypeRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_data_product_type(
    body: DataProductTypeCreate,
    db: DBSessionDep,
    _: bool = _write_access,
):
    """Create a data product type."""
    try:
        created = data_product_types_manager.create_type(db, body)
        db.commit()
        return created
    except (DataProductTypeNotFoundError, DataProductTypeConflictError) as e:
        db.rollback()
        _raise_for(e)
    except Exception:
        db.rollback()
        logger.exception("Error creating data product type %s", body.key)
        raise HTTPException(status_code=500, detail="Failed to create data product type")


# Declared before /{type_id} so "reorder" isn't read as an id.
@router.put("/data-product-types/reorder", response_model=list[DataProductTypeRead])
async def reorder_data_product_types(
    body: DataProductTypeReorder,
    db: DBSessionDep,
    _: bool = _write_access,
):
    """Set the order of several types at once."""
    order_map = {item.id: item.sort_order for item in body.types}
    try:
        result = data_product_types_manager.reorder_types(db, order_map)
        db.commit()
        return result
    except (DataProductTypeNotFoundError, DataProductTypeConflictError) as e:
        db.rollback()
        _raise_for(e)
    except Exception:
        db.rollback()
        logger.exception("Error reordering data product types")
        raise HTTPException(status_code=500, detail="Failed to reorder data product types")


@router.get("/data-product-types/{type_id}", response_model=DataProductTypeRead)
async def get_data_product_type(type_id: UUID, db: DBSessionDep):
    """Get one data product type."""
    try:
        return data_product_types_manager.get_type(db, type_id)
    except DataProductTypeNotFoundError as e:
        _raise_for(e)


@router.put("/data-product-types/{type_id}", response_model=DataProductTypeRead)
async def update_data_product_type(
    type_id: UUID,
    body: DataProductTypeUpdate,
    db: DBSessionDep,
    _: bool = _write_access,
):
    """Rename, reorder, (de)activate or change the default. The key can't be changed."""
    try:
        updated = data_product_types_manager.update_type(db, type_id, body)
        db.commit()
        return updated
    except (DataProductTypeNotFoundError, DataProductTypeConflictError) as e:
        db.rollback()
        _raise_for(e)
    except Exception:
        db.rollback()
        logger.exception("Error updating data product type %s", type_id)
        raise HTTPException(status_code=500, detail="Failed to update data product type")


@router.delete("/data-product-types/{type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_data_product_type(
    type_id: UUID,
    db: DBSessionDep,
    _: bool = _write_access,
):
    """Delete a type. Refused for built-in types and for types still in use."""
    try:
        data_product_types_manager.delete_type(db, type_id)
        db.commit()
    except (DataProductTypeNotFoundError, DataProductTypeConflictError) as e:
        db.rollback()
        _raise_for(e)
    except Exception:
        db.rollback()
        logger.exception("Error deleting data product type %s", type_id)
        raise HTTPException(status_code=500, detail="Failed to delete data product type")


def register_routes(app):
    app.include_router(router)
    logger.info("Data product types routes registered")
