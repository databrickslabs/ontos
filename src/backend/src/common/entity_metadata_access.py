"""Who may read and change the notes, links, documents and cost items of an entity.

The metadata and costs routes are gated by the ``data-domains`` feature. For
an asset (``entity_type == "asset"``) the asset's own rules apply instead
(issue #1342):

- reading needs the asset to be readable (``assets`` READ_WRITE, or a link to
  a Data Product the user can access, see ``asset_access``);
- changing needs ``assets`` READ_WRITE (attaching a shared or another
  entity's row also needs ``data-domains`` READ, the right to read that row);
- attaching a row that belongs to an asset to any other entity needs that asset
  to be readable too, as its merged metadata goes to every ``data-domains`` reader;
- the asset must exist (404 ``asset_not_found``), except on the routes that
  address a row by its own id, so orphaned rows can still be cleaned up.

Every other entity type keeps the ``data-domains`` check, run exactly as the
``PermissionChecker`` dependency did before. Both checks are dependencies, so
they run before the request body and the query are validated, as before.
"""
from typing import Callable, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status

from src.common.asset_access import (
    ASSETS_FEATURE_ID, AssetNotFoundError, AssetReadDeniedError, AssetWriteDeniedError,
    ensure_asset_readable, user_has_assets_feature,
)
from src.common.authorization import PermissionChecker, get_user_details_from_sdk
from src.common.dependencies import get_db
from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger
from src.common.manager_dependencies import get_auth_manager, get_metadata_manager
from src.controller.assets_manager import assets_manager
from src.controller.costs_manager import CostsManager

logger = get_logger(__name__)

METADATA_FEATURE_ID = "data-domains"
ASSET_ENTITY_TYPE = "asset"
_ASSETS_WRITE_CHECKER = PermissionChecker(ASSETS_FEATURE_ID, FeatureAccessLevel.READ_WRITE)


def _asset_uuid(entity_id: Optional[str]) -> Optional[UUID]:
    try:
        return UUID(str(entity_id))
    except (TypeError, ValueError):
        return None


def _refuse(status_code: int, error) -> None:
    """Raise ``error`` as an HTTP error that carries its code (see ``api_errors``)."""
    raise HTTPException(status_code=status_code, detail=str(error)) from error


def _read_denied() -> None:
    _refuse(status.HTTP_403_FORBIDDEN, AssetReadDeniedError(
        "You don't have access to this asset. Viewing it needs read/write access to Assets, "
        "or access to a data product it belongs to."
    ))


async def _ensure_asset(
    request: Request, db, user_details, auth_manager, entity_id: Optional[str],
    level: FeatureAccessLevel, *, require_asset: bool,
) -> None:
    asset_id = _asset_uuid(entity_id)
    if level == FeatureAccessLevel.READ_ONLY:
        if asset_id is None:
            # No asset has this id: only a user who may read every asset learns that.
            if not user_has_assets_feature(request, user_details, FeatureAccessLevel.READ_WRITE):
                _read_denied()
        else:
            try:
                ensure_asset_readable(request, db, user_details, assets_manager, asset_id)
            except HTTPException as denied:
                if denied.status_code != status.HTTP_403_FORBIDDEN:
                    raise
                _read_denied()
    else:
        try:
            await _ASSETS_WRITE_CHECKER(request, user_details, auth_manager)
        except HTTPException as denied:
            if denied.status_code != status.HTTP_403_FORBIDDEN:
                raise
            _refuse(status.HTTP_403_FORBIDDEN, AssetWriteDeniedError(
                "Changing the notes, links, documents and costs of an asset needs "
                "read/write access to Assets."
            ))

    if require_asset and (asset_id is None or not assets_manager.asset_exists(db, asset_id)):
        _refuse(status.HTTP_404_NOT_FOUND, AssetNotFoundError(
            f"Asset '{entity_id}' not found.", assetId=str(entity_id),
        ))


async def _ensure_attached_row_readable(request: Request, db, user_details, auth_manager) -> None:
    """The row to attach belongs to an asset: its reader must be able to read that asset.

    The attach body isn't validated yet (dependencies run first), so a body or
    row that can't be read is left to the route to answer, as before.
    """
    try:
        body = await request.json()
        manager = get_metadata_manager(request)
        load_row = {
            'rich_text': manager.get_rich_text, 'link': manager.get_link,
            'document': manager.get_document,
        }.get(body.get('asset_type'))
        row = load_row(db, id=str(body.get('asset_id'))) if load_row else None
    except Exception:
        logger.warning("Could not load the row to attach on %s", request.url.path)
        return
    if row is not None and getattr(row, 'entity_type', None) == ASSET_ENTITY_TYPE:
        await _ensure_asset(
            request, db, user_details, auth_manager, row.entity_id, FeatureAccessLevel.READ_ONLY,
            require_asset=False,
        )


class EntityMetadataPermission:
    """Dependency for the routes with ``{entity_type}`` in the path.

    ``entity_id`` is read from the path (costs) or the query (metadata).

    ``contract_ids_need_domains`` (merged metadata): the route also returns
    the inheritable metadata of the contracts in ``contract_ids``, which the
    asset rules don't cover, so a request that names contracts still needs
    the ``data-domains`` check.

    ``attaching`` (attach route): the row to attach is picked by id from the
    shared library or another entity, which only ``data-domains`` READ may
    read, and merged metadata then returns it to every reader of the asset.
    Attaching to an asset also needs ``data-domains`` READ.
    """

    def __init__(
        self, level: FeatureAccessLevel, *,
        contract_ids_need_domains: bool = False, attaching: bool = False,
    ):
        self.level = level
        self.contract_ids_need_domains = contract_ids_need_domains
        self.attaching = attaching
        self._domain_checker = PermissionChecker(METADATA_FEATURE_ID, level)
        self._domain_read_checker = PermissionChecker(
            METADATA_FEATURE_ID, FeatureAccessLevel.READ_ONLY,
        )

    async def __call__(
        self,
        request: Request,
        db=Depends(get_db),
        user_details=Depends(get_user_details_from_sdk),
        auth_manager=Depends(get_auth_manager),
    ) -> None:
        entity_type = request.path_params.get('entity_type')
        if entity_type != ASSET_ENTITY_TYPE:
            await self._domain_checker(request, user_details, auth_manager)
            if self.attaching:
                await _ensure_attached_row_readable(request, db, user_details, auth_manager)
            return
        entity_id = request.path_params.get('entity_id') or request.query_params.get('entity_id')
        await _ensure_asset(
            request, db, user_details, auth_manager, entity_id, self.level, require_asset=True,
        )
        contract_ids = (request.query_params.get('contract_ids') or '').split(',')
        if self.contract_ids_need_domains and any(cid.strip() for cid in contract_ids):
            await self._domain_checker(request, user_details, auth_manager)
        if self.attaching:
            await self._domain_read_checker(request, user_details, auth_manager)


def _rich_text_owner(request: Request, db):
    return get_metadata_manager(request).get_rich_text(db, id=request.path_params['id'])


def _link_owner(request: Request, db):
    return get_metadata_manager(request).get_link(db, id=request.path_params['id'])


def _document_owner(request: Request, db):
    return get_metadata_manager(request).get_document(db, id=request.path_params['id'])


def _cost_item_owner(request: Request, db):
    return CostsManager().get(db, id=request.path_params['id'])


class RowMetadataPermission:
    """Dependency for the routes that address a row by its id (``/rich-texts/{id}``, ...).

    The row is loaded to learn its entity; a row that can't be loaded gets the
    ``data-domains`` check, and the route answers 404 as before.
    """

    def __init__(self, load_row: Callable, level: FeatureAccessLevel):
        self.load_row = load_row
        self.level = level
        self._domain_checker = PermissionChecker(METADATA_FEATURE_ID, level)

    async def __call__(
        self,
        request: Request,
        db=Depends(get_db),
        user_details=Depends(get_user_details_from_sdk),
        auth_manager=Depends(get_auth_manager),
    ) -> None:
        try:
            row = self.load_row(request, db)
        except Exception:
            logger.warning("Could not load the row of %s before the access check", request.url.path)
            row = None
        if row is None or getattr(row, 'entity_type', None) != ASSET_ENTITY_TYPE:
            await self._domain_checker(request, user_details, auth_manager)
            return
        await _ensure_asset(
            request, db, user_details, auth_manager, row.entity_id, self.level,
            require_asset=False,
        )


def rich_text_permission(level: FeatureAccessLevel) -> RowMetadataPermission:
    return RowMetadataPermission(_rich_text_owner, level)


def link_permission(level: FeatureAccessLevel) -> RowMetadataPermission:
    return RowMetadataPermission(_link_owner, level)


def document_permission(level: FeatureAccessLevel) -> RowMetadataPermission:
    return RowMetadataPermission(_document_owner, level)


def cost_item_permission(level: FeatureAccessLevel) -> RowMetadataPermission:
    return RowMetadataPermission(_cost_item_owner, level)
