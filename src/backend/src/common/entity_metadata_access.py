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

The ``{entity_type}`` in the path must be one of ``ENTITY_TYPES``, as stored
(422 ``entity_type_not_supported``): rows are filtered under the exact type, so
``Asset`` would otherwise be a namespace outside the asset rules. A stored row
whose type is another casing of ``asset`` gets the asset rules.

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
from src.common.api_errors import CodedValueError
from src.common.authorization import PermissionChecker, get_user_details_from_sdk
from src.common.dependencies import get_db
from src.common.features import FeatureAccessLevel
from src.common.manager_dependencies import (
    get_assets_manager, get_auth_manager, get_metadata_manager,
)
from src.controller.costs_manager import CostsManager

METADATA_FEATURE_ID = "data-domains"
ASSET_ENTITY_TYPE = "asset"
_ASSETS_WRITE_CHECKER = PermissionChecker(ASSETS_FEATURE_ID, FeatureAccessLevel.READ_WRITE)
# The entity types the notes, links, documents and costs routes serve: the request
# models' types and the entity pages that show the metadata panel.
ENTITY_TYPES = frozenset({
    'data_domain', 'data_product', 'data_contract', 'dataset', ASSET_ENTITY_TYPE,
    'compliance_policy', 'concept', 'collection',
})


class EntityTypeNotSupportedError(CodedValueError):
    """The path names an entity type the routes don't serve, or not in its stored form."""

    code = 'entity_type_not_supported'


def _is_asset(entity_type: Optional[str]) -> bool:
    """Whether a stored entity type means an asset, whatever its case."""
    return str(entity_type or '').strip().lower() == ASSET_ENTITY_TYPE


def _ensure_supported_entity_type(entity_type: Optional[str]) -> None:
    """Refuse (422) a type outside ``ENTITY_TYPES``, including another casing of one.

    Rows are stored and filtered under the exact type, so ``Asset`` would be a
    separate namespace that the asset rules don't cover.
    """
    if entity_type not in ENTITY_TYPES:
        _refuse(status.HTTP_422_UNPROCESSABLE_ENTITY, EntityTypeNotSupportedError(
            f"Unsupported entity type '{entity_type}'.", entityType=str(entity_type),
        ))


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
                ensure_asset_readable(
                    request, db, user_details, get_assets_manager(request), asset_id,
                )
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

    if require_asset and (
        asset_id is None or not get_assets_manager(request).asset_exists(db, asset_id)
    ):
        _refuse(status.HTTP_404_NOT_FOUND, AssetNotFoundError(
            f"Asset '{entity_id}' not found.", assetId=str(entity_id),
        ))


async def _ensure_attached_row_readable(request: Request, db, user_details, auth_manager) -> None:
    """The row to attach belongs to an asset: its reader must be able to read that asset.

    The attach body isn't validated yet (dependencies run first): a body that
    isn't a JSON object, or doesn't name a row, is left to the route's 422. A
    row that fails to load fails the request (500), never lets it through.
    """
    try:
        body = await request.json()
        asset_type, row_id = body.get('asset_type'), body.get('asset_id')
    except (ValueError, AttributeError):
        return
    if asset_type not in ('rich_text', 'link', 'document') or row_id is None:
        return
    owner = get_metadata_manager(request).get_row_owner(db, kind=asset_type, id=str(row_id))
    if owner is not None and _is_asset(owner[0]):
        await _ensure_asset(
            request, db, user_details, auth_manager, owner[1], FeatureAccessLevel.READ_ONLY,
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
        _ensure_supported_entity_type(entity_type)
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
            await _ensure_attached_row_readable(request, db, user_details, auth_manager)


def _rich_text_owner(request: Request, db):
    return get_metadata_manager(request).get_row_owner(
        db, kind='rich_text', id=request.path_params['id'],
    )


def _link_owner(request: Request, db):
    return get_metadata_manager(request).get_row_owner(
        db, kind='link', id=request.path_params['id'],
    )


def _document_owner(request: Request, db):
    return get_metadata_manager(request).get_row_owner(
        db, kind='document', id=request.path_params['id'],
    )


def _cost_item_owner(request: Request, db):
    return CostsManager().get_owner(db, id=request.path_params['id'])


class RowMetadataPermission:
    """Dependency for the routes that address a row by its id (``/rich-texts/{id}``, ...).

    The stored row is read to learn its entity (``load_owner`` returns
    ``(entity_type, entity_id)``, or ``None`` when no row has the id). An unknown
    row gets the ``data-domains`` check, and the route answers 404 as before. A
    failing lookup fails the request (500), never falls back to that check.

    A row of an asset the user can't read answers as an unknown row (the
    ``data-domains`` check, then 404 with the route's ``not_found`` text), so a
    row id doesn't tell whether it belongs to such an asset. A reader of the
    asset gets the asset rules, ``asset_write_denied`` included.
    """

    def __init__(self, load_owner: Callable, level: FeatureAccessLevel, not_found: str):
        self.load_owner = load_owner
        self.level = level
        self.not_found = not_found
        self._domain_checker = PermissionChecker(METADATA_FEATURE_ID, level)

    async def __call__(
        self,
        request: Request,
        db=Depends(get_db),
        user_details=Depends(get_user_details_from_sdk),
        auth_manager=Depends(get_auth_manager),
    ) -> None:
        owner = self.load_owner(request, db)
        if owner is None or not _is_asset(owner[0]):
            await self._domain_checker(request, user_details, auth_manager)
            return
        try:
            await _ensure_asset(
                request, db, user_details, auth_manager, owner[1], FeatureAccessLevel.READ_ONLY,
                require_asset=False,
            )
        except HTTPException as denied:
            if denied.status_code != status.HTTP_403_FORBIDDEN:
                raise
            await self._domain_checker(request, user_details, auth_manager)
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=self.not_found)
        if self.level != FeatureAccessLevel.READ_ONLY:
            await _ensure_asset(
                request, db, user_details, auth_manager, owner[1], self.level,
                require_asset=False,
            )


def rich_text_permission(level: FeatureAccessLevel) -> RowMetadataPermission:
    return RowMetadataPermission(_rich_text_owner, level, "Rich text not found")


def link_permission(level: FeatureAccessLevel) -> RowMetadataPermission:
    return RowMetadataPermission(_link_owner, level, "Link not found")


def document_permission(level: FeatureAccessLevel) -> RowMetadataPermission:
    return RowMetadataPermission(_document_owner, level, "Document not found")


def cost_item_permission(level: FeatureAccessLevel) -> RowMetadataPermission:
    return RowMetadataPermission(_cost_item_owner, level, "Cost item not found")
