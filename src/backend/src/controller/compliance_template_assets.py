"""Compliance Templates for table and view assets (host side).

The compliance-templates feature itself stays entity-agnostic: it only knows an
``entity_type`` string and an ``entity_id``. This module is the asset host's
side of the integration: which assets a template bound to ``asset`` applies to,
and how a request for one is resolved. Routes add the asset read/write
permission checks on top.
"""
import uuid
from typing import Any, Dict

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.controller.compliance_templates_manager import compliance_templates_manager
from src.db_models.assets import AssetDb
from src.repositories.assets_repository import asset_repo

logger = get_logger(__name__)

# Entity type a template is bound to for assets (same polymorphic key as tags,
# semantic links, costs and quality items on assets).
ASSET_ENTITY_TYPE = "asset"

# Asset types the asset template applies to. Other asset types have no
# Compliance button and the template routes refuse them.
TEMPLATE_ASSET_TYPES = frozenset({"Table", "View"})


class ComplianceTemplateAssetError(ValueError):
    """An asset template request that can't be served. Sent as ``{code, message, params}``."""

    def __init__(self, code: str, message: str, status_code: int, **params: Any):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.params: Dict[str, Any] = params

    def to_detail(self) -> Dict[str, Any]:
        return {"code": self.code, "message": str(self), "params": self.params}


def location_key(value: str | None) -> str:
    """Match key of an asset location or a table name: no backticks or outer
    whitespace, lowercase (``` `Main`.`Sales`.orders ``` -> ``main.sales.orders``)."""
    return (value or "").replace("`", "").strip().lower()


def location_key_sql(column):
    """``location_key`` as a SQL expression on a column."""
    return func.lower(func.trim(func.replace(column, "`", "")))


def is_template_asset_type(asset_type_name: str | None) -> bool:
    """True when assets of this type can carry compliance template values."""
    return asset_type_name in TEMPLATE_ASSET_TYPES


def resolve_template_asset(db: Session, asset_id: str) -> AssetDb:
    """Return the asset a template request is about.

    Raises ``ComplianceTemplateAssetError`` when the id is not an asset id, the
    asset doesn't exist, or its type is not a table or view.
    """
    try:
        asset_uuid = uuid.UUID(str(asset_id))
    except ValueError:
        raise ComplianceTemplateAssetError(
            "compliance_template_asset_not_found",
            "Asset not found.",
            404,
            assetId=str(asset_id),
        )
    asset = asset_repo.get(db, asset_uuid)
    if asset is None:
        raise ComplianceTemplateAssetError(
            "compliance_template_asset_not_found",
            "Asset not found.",
            404,
            assetId=str(asset_id),
        )
    asset_type = asset.asset_type.name if asset.asset_type else None
    if not is_template_asset_type(asset_type):
        raise ComplianceTemplateAssetError(
            "compliance_template_asset_type_unsupported",
            "Compliance templates apply to table and view assets only.",
            422,
            assetType=asset_type,
        )
    return asset


def reconcile_asset(
    db: Session, *, asset_id: str, asset_type_name: str | None, user_email: str | None
) -> None:
    """Materialize template defaults for a table or view asset after an edit.

    Same call as the data product update path: the rows are flushed and the
    request's session commits them with the edit. No-op for other asset types
    or when no template is active; never raises (the asset edit must not fail).
    """
    if not is_template_asset_type(asset_type_name):
        return
    try:
        compliance_templates_manager.reconcile_entity(
            db,
            entity_type=ASSET_ENTITY_TYPE,
            entity_id=str(asset_id),
            user_email=user_email,
        )
    except Exception:
        logger.warning("Compliance reconcile failed for asset %s", asset_id, exc_info=True)
