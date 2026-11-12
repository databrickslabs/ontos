from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request

from src.models.assets import (
    AssetTypeCreate, AssetTypeUpdate, AssetTypeRead, AssetTypeSummary,
    AssetCreate, AssetUpdate, AssetRead, AssetSummary, AssetUpdateResult,
    AssetRelationshipCreate, AssetRelationshipRead,
    PaginatedAssetSummary,
    DeletePreviewItem, CascadeDeleteRequest, CascadeDeleteResult,
)
from src.controller.assets_manager import assets_manager
from src.controller.metric_views_manager import (
    MetricViewNotFoundError, MetricViewsManager, UserClientUnavailableError, UserTokenRequiredError,
)
from src.common.workspace_client import get_obo_workspace_client
from src.controller.semantic_links_manager import SemanticLinksManager
from src.controller.uc_description_sync_manager import UcDescriptionSyncManager
from src.db_models.assets import AssetDb
from src.models.metric_views import MetricViewRead
from src.controller.metric_view_change_requests_manager import (
    ChangeRequestError, MetricViewChangeRequestsManager,
)
from src.models.metric_view_change_requests import (
    MetricViewChangeRequestCreate, MetricViewChangeRequestDetail, MetricViewChangeRequestRead,
)
from src.common.authorization import PermissionChecker
from src.common.features import FeatureAccessLevel
from src.common.dependencies import (
    DBSessionDep,
    CurrentUserDep,
    AuditManagerDep,
    AuditCurrentUserDep,
    SettingsDep,
)
from src.common.errors import NotFoundError, ConflictError, ValidationError
from src.common.logging import get_logger

logger = get_logger(__name__)

asset_types_router = APIRouter(prefix="/api/asset-types", tags=["Asset Types"])
assets_router = APIRouter(prefix="/api/assets", tags=["Assets"])
FEATURE_ID = "assets"


def get_assets_manager():
    return assets_manager


def _get_data_products_manager(request: Request):
    """Pull the DataProductsManager singleton from app.state.

    Returns None when not configured (e.g. early in tests); callers must
    handle that defensively rather than raising — scoping should fail closed
    (i.e. return empty for non-admins) rather than 500.
    """
    return getattr(request.app.state, "data_products_manager", None)


def _user_has_assets_feature(request: Request, current_user, level: FeatureAccessLevel) -> bool:
    """Check whether the current user has the ``assets`` feature at ``level``.

    Used for branching: when a Data Consumer lacks the feature, we still
    allow DP-scoped reads of linked assets (issue #347), but block writes.
    """
    try:
        auth_manager = getattr(request.app.state, "authorization_manager", None)
        settings_manager = getattr(request.app.state, "settings_manager", None)
        if not auth_manager or not current_user:
            return False
        applied_role_id = None
        if settings_manager:
            try:
                applied_role_id = settings_manager.get_applied_role_override_for_user(
                    current_user.email
                )
            except Exception:
                applied_role_id = None
        if applied_role_id and settings_manager:
            effective = settings_manager.get_feature_permissions_for_role_id(applied_role_id)
        else:
            effective = auth_manager.get_user_effective_permissions(
                current_user.groups or [], None
            )
        return auth_manager.has_permission(effective, FEATURE_ID, level)
    except Exception:
        logger.exception("Failed to check assets feature for user")
        return False


def _ensure_asset_readable(request: Request, db, current_user, manager, asset_id: UUID) -> None:
    """Raise 403 unless the user may read the asset (issue #347).

    Users with ``assets:READ_WRITE`` or higher read every asset; others only
    assets linked (directly or via an OutputPort) to a Data Product they can
    access.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authentication required.",
        )

    is_unscoped = _user_has_assets_feature(request, current_user, FeatureAccessLevel.READ_WRITE)

    if not is_unscoped:
        dpm = _get_data_products_manager(request)
        if dpm is None or not manager.is_asset_accessible(
            db, asset_id=asset_id, data_products_manager=dpm, is_admin=False,
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Asset is not linked to a Data Product accessible to this user.",
            )


# ===================== Asset Types =====================

@asset_types_router.post(
    "",
    response_model=AssetTypeRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def create_asset_type(
    request: Request,
    type_in: AssetTypeCreate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager=Depends(get_assets_manager),
):
    """Creates a new asset type."""
    success = False
    details = {"params": {"name": type_in.name}}
    created_id = None
    try:
        result = manager.create_asset_type(db=db, type_in=type_in, current_user_id=current_user.email)
        success = True
        created_id = str(result.id)
        return result
    except ConflictError as e:
        details["exception"] = {"type": "ConflictError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create asset type '%s'", type_in.name)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create asset type")
    finally:
        if created_id:
            details["created_resource_id"] = created_id
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="CREATE_ASSET_TYPE", success=success, details=details,
        )


@asset_types_router.get(
    "",
    response_model=List[AssetTypeRead],
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
def get_all_asset_types(
    db: DBSessionDep,
    manager=Depends(get_assets_manager),
    skip: int = 0,
    limit: Optional[int] = None,
    category: Optional[str] = Query(None),
    type_status: Optional[str] = Query(None, alias="status"),
):
    """Lists all asset types."""
    return manager.get_all_asset_types(db=db, skip=skip, limit=limit, category=category, status=type_status)


@asset_types_router.get(
    "/summary",
    response_model=List[AssetTypeSummary],
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
def get_asset_types_summary(
    db: DBSessionDep,
    manager=Depends(get_assets_manager),
):
    """Gets a summary list of asset types for dropdowns."""
    return manager.get_asset_types_summary(db=db)


@asset_types_router.get(
    "/{type_id}",
    response_model=AssetTypeRead,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
def get_asset_type(
    type_id: UUID,
    db: DBSessionDep,
    manager=Depends(get_assets_manager),
):
    """Gets a specific asset type by ID."""
    result = manager.get_asset_type(db=db, type_id=type_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Asset type '{type_id}' not found")
    return result


@asset_types_router.put(
    "/{type_id}",
    response_model=AssetTypeRead,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def update_asset_type(
    type_id: UUID,
    request: Request,
    type_in: AssetTypeUpdate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager=Depends(get_assets_manager),
):
    """Updates an existing asset type."""
    success = False
    details = {"params": {"type_id": str(type_id)}}
    try:
        result = manager.update_asset_type(db=db, type_id=type_id, type_in=type_in, current_user_id=current_user.email)
        success = True
        return result
    except NotFoundError as e:
        details["exception"] = {"type": "NotFoundError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ConflictError as e:
        details["exception"] = {"type": "ConflictError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update asset type %s", type_id)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update asset type")
    finally:
        if success:
            details["updated_resource_id"] = str(type_id)
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="UPDATE_ASSET_TYPE", success=success, details=details,
        )


@asset_types_router.delete(
    "/{type_id}",
    response_model=AssetTypeRead,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.ADMIN))],
)
def delete_asset_type(
    type_id: UUID,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager=Depends(get_assets_manager),
):
    """Deletes an asset type. Requires Admin. Fails if assets still reference it."""
    success = False
    details = {"params": {"type_id": str(type_id)}}
    try:
        result = manager.delete_asset_type(db=db, type_id=type_id)
        success = True
        return result
    except NotFoundError as e:
        details["exception"] = {"type": "NotFoundError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ConflictError as e:
        details["exception"] = {"type": "ConflictError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        logger.exception("Failed to delete asset type %s", type_id)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete asset type")
    finally:
        if success:
            details["deleted_resource_id"] = str(type_id)
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="DELETE_ASSET_TYPE", success=success, details=details,
        )


# ===================== Assets =====================

@assets_router.post(
    "",
    response_model=AssetRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def create_asset(
    request: Request,
    asset_in: AssetCreate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager=Depends(get_assets_manager),
):
    """Creates a new asset."""
    success = False
    details = {"params": {"name": asset_in.name, "type_id": str(asset_in.asset_type_id)}}
    created_id = None
    try:
        result = manager.create_asset(db=db, asset_in=asset_in, current_user_id=current_user.email)
        success = True
        created_id = str(result.id)
        return result
    except NotFoundError as e:
        details["exception"] = {"type": "NotFoundError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValidationError as e:
        details["exception"] = {"type": "ValidationError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except ConflictError as e:
        details["exception"] = {"type": "ConflictError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create asset '%s'", asset_in.name)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create asset")
    finally:
        if created_id:
            details["created_resource_id"] = created_id
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="CREATE_ASSET", success=success, details=details,
        )


@assets_router.get(
    "",
    response_model=PaginatedAssetSummary,
)
def get_all_assets(
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    manager=Depends(get_assets_manager),
    skip: int = 0,
    limit: int = 100,
    asset_type_id: Optional[UUID] = Query(None),
    asset_type_names: Optional[str] = Query(None, description="Comma-separated asset type names"),
    platform: Optional[str] = Query(None),
    domain_id: Optional[str] = Query(None, description="Filter by a single domain ID (any-of)"),
    domain_ids: Optional[str] = Query(None, description="Filter by multiple domain IDs, comma-separated (any-of)"),
    asset_status: Optional[str] = Query(None, alias="status"),
    name: Optional[str] = Query(None),
):
    """Lists all assets with optional filters. Returns paginated results.

    Authorization (issue #347):
    - Users with ``assets:READ_WRITE`` or higher (Producers, Admins): see
      all assets, unscoped — preserves existing behaviour.
    - Users below ``READ_WRITE`` (typically Data Consumers): scoped to
      assets linked to Data Products they can access (least-privilege).
      This branch also handles users with no ``assets`` feature at all —
      they still see DP-linked assets so the DP detail view's Linked
      Assets surface keeps working without granting the broader feature.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authentication required.",
        )

    # Producers + Admins (READ_WRITE+) keep full visibility.
    is_unscoped = _user_has_assets_feature(request, current_user, FeatureAccessLevel.READ_WRITE)

    if not is_unscoped:
        dpm = _get_data_products_manager(request)
        if dpm is None:
            # Fail closed: no DP context available, scoped users see nothing.
            logger.warning("DataProductsManager unavailable; returning empty asset list for scoped user")
            return PaginatedAssetSummary(items=[], total=0, skip=skip, limit=limit)
        # Pass is_admin=False to force scoping logic; the manager itself doesn't
        # check group membership — it only branches on the boolean we pass in.
        restrict_ids = manager.resolve_accessible_asset_ids(
            db, data_products_manager=dpm, is_admin=False,
        )
    else:
        restrict_ids = None  # unrestricted

    type_names_list = [t.strip() for t in asset_type_names.split(",")] if asset_type_names else None
    domain_ids_list = [d.strip() for d in domain_ids.split(",") if d.strip()] if domain_ids else None
    return manager.get_all_assets(
        db=db, skip=skip, limit=limit,
        asset_type_id=asset_type_id, asset_type_names=type_names_list,
        platform=platform, domain_id=domain_id, domain_ids=domain_ids_list, status=asset_status, name=name,
        restrict_to_ids=restrict_ids,
    )


@assets_router.get(
    "/{asset_id}",
    response_model=AssetRead,
)
def get_asset(
    asset_id: UUID,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    manager=Depends(get_assets_manager),
):
    """Gets a specific asset by ID with relationships.

    Authorization (issue #347):
    - Users with ``assets:READ_WRITE`` or higher (Producers, Admins): always
      allowed — preserves existing behaviour.
    - Users below that (Consumers, no-``assets``-feature): allowed iff the
      asset is linked (directly or via an OutputPort) to a Data Product
      the user can access. This enables Linked Assets navigation from a
      DP detail view even without the broader ``assets`` feature granted.
    """
    _ensure_asset_readable(request, db, current_user, manager, asset_id)

    result = manager.get_asset(db=db, asset_id=asset_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Asset '{asset_id}' not found")
    return result


@assets_router.put(
    "/{asset_id}",
    response_model=AssetUpdateResult,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def update_asset(
    asset_id: UUID,
    request: Request,
    asset_in: AssetUpdate,
    db: DBSessionDep,
    settings: SettingsDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager=Depends(get_assets_manager),
):
    """Updates an existing asset.

    With the "write asset descriptions to Unity Catalog" setting on, a changed
    description of a Databricks table, view or column is also written to Unity
    Catalog as the user. A failed write doesn't fail the save: the response
    carries a coded warning and the asset's ``description_sync`` state.
    """
    success = False
    details = {"params": {"asset_id": str(asset_id)}}
    try:
        existing = db.get(AssetDb, asset_id)
        previous_description = existing.description if existing is not None else None
        result = manager.update_asset(db=db, asset_id=asset_id, asset_in=asset_in, current_user_id=current_user.email)
        warning, sync_state = UcDescriptionSyncManager(settings).sync_after_update(
            db, asset_id,
            description_sent='description' in asset_in.model_fields_set,
            previous_description=previous_description,
            user_client=lambda: _user_workspace_client(request),
        )
        result = AssetUpdateResult(
            **result.model_dump(), warnings=[warning] if warning else [],
        )
        result.description_sync = sync_state
        if warning:
            details["uc_description_warning"] = warning.code
        success = True
        return result
    except NotFoundError as e:
        details["exception"] = {"type": "NotFoundError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValidationError as e:
        details["exception"] = {"type": "ValidationError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except ConflictError as e:
        details["exception"] = {"type": "ConflictError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update asset %s", asset_id)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update asset")
    finally:
        if success:
            details["updated_resource_id"] = str(asset_id)
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="UPDATE_ASSET", success=success, details=details,
        )


@assets_router.get(
    "/{asset_id}/infer-schema",
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
def infer_schema_from_asset(
    asset_id: UUID,
    db: DBSessionDep,
    manager=Depends(get_assets_manager),
):
    """Extract ODCS-compatible schema objects from an asset and its children."""
    try:
        return manager.infer_schema_from_asset(db=db, asset_id=asset_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.exception("Failed to infer schema from asset %s", asset_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to infer schema from asset")


@assets_router.get(
    "/{asset_id}/delete-preview",
    response_model=DeletePreviewItem,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.ADMIN))],
)
def get_delete_preview(
    asset_id: UUID,
    db: DBSessionDep,
    manager=Depends(get_assets_manager),
):
    """Returns a tree of the asset and all hierarchical descendants that would be cascade-deleted."""
    try:
        return manager.get_delete_preview(db=db, asset_id=asset_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.exception("Failed to build delete preview for asset %s", asset_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to build delete preview")


@assets_router.post(
    "/cascade-delete",
    response_model=CascadeDeleteResult,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.ADMIN))],
)
def cascade_delete_assets(
    body: CascadeDeleteRequest,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager=Depends(get_assets_manager),
):
    """Deletes multiple assets in leaf-first order. Requires Admin."""
    details = {"params": {"asset_ids": [str(aid) for aid in body.asset_ids]}}
    try:
        result = manager.cascade_delete_assets(
            db=db, asset_ids=body.asset_ids, current_user_id=current_user.email,
        )
        details["deleted_count"] = len(result.deleted)
        details["failed_count"] = len(result.failed)
        return result
    except Exception as e:
        logger.exception("Failed to cascade-delete assets")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to cascade-delete assets")
    finally:
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="CASCADE_DELETE_ASSETS",
            success="exception" not in details, details=details,
        )


@assets_router.delete(
    "/{asset_id}",
    response_model=AssetRead,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.ADMIN))],
)
def delete_asset(
    asset_id: UUID,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager=Depends(get_assets_manager),
):
    """Deletes an asset. Requires Admin."""
    success = False
    details = {"params": {"asset_id": str(asset_id)}}
    try:
        result = manager.delete_asset(db=db, asset_id=asset_id, current_user_id=current_user.email)
        success = True
        return result
    except NotFoundError as e:
        details["exception"] = {"type": "NotFoundError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.exception("Failed to delete asset %s", asset_id)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete asset")
    finally:
        if success:
            details["deleted_resource_id"] = str(asset_id)
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="DELETE_ASSET", success=success, details=details,
        )


def _user_workspace_client(request: Request):
    """The workspace client of the requesting user, built from their OBO token.

    Fails closed: ``get_obo_workspace_client`` falls back to the app's service
    principal when the request has no ``x-forwarded-access-token``, so the token
    is required here first, and a client that can't be built is an error rather
    than a fallback.
    """
    if not request.headers.get('x-forwarded-access-token'):
        raise UserTokenRequiredError(
            "Reading Unity Catalog needs the user's Databricks token, and the request has none."
        )
    try:
        return get_obo_workspace_client(request)
    except Exception:
        logger.warning("Could not build the user's workspace client", exc_info=True)
        raise UserClientUnavailableError(
            "The user's Databricks workspace client could not be created."
        )


@assets_router.get(
    "/{asset_id}/metric-view",
    response_model=MetricViewRead,
)
def get_asset_metric_view(
    asset_id: UUID,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    manager=Depends(get_assets_manager),
):
    """The Unity Catalog metric view behind an asset: its YAML, its dimensions and
    measures, the concept links of the view and of each field, and its baseline
    and drift state (an unparseable definition is drift ``unknown``, not an error).

    Unity Catalog is read as the user (on-behalf-of token), never as the app,
    so the definition is only returned to users Unity Catalog lets read it.
    403 ``user_token_required`` without the user's token (401 when Unity Catalog
    refuses it), 503 ``user_client_unavailable`` when the user's client can't be
    built, 404
    ``metric_view_not_found`` when the asset isn't a metric view the user can
    read. The asset itself must be readable by the user.
    """
    _ensure_asset_readable(request, db, current_user, manager, asset_id)
    try:
        ws_client = _user_workspace_client(request)
    except UserTokenRequiredError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except UserClientUnavailableError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e
    links_manager = SemanticLinksManager(
        db, semantic_models_manager=getattr(request.app.state, 'semantic_models_manager', None)
    )
    try:
        return MetricViewsManager(db, links_manager).get_for_asset(
            asset_id, ws_client, user_email=getattr(current_user, 'email', None),
        )
    except MetricViewNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except UserTokenRequiredError as e:
        # Unity Catalog refused the user's token (expired or revoked)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)) from e
    except Exception:
        logger.exception("Failed to read the metric view of asset %s", asset_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read the metric view",
        )


# ===================== Metric View Change Requests (#1124) =====================

def _change_requests(request: Request, db) -> MetricViewChangeRequestsManager:
    links_manager = SemanticLinksManager(
        db, semantic_models_manager=getattr(request.app.state, 'semantic_models_manager', None)
    )
    return MetricViewChangeRequestsManager(db, links_manager)


def _change_request_call(action: str, asset_id: UUID, call):
    """Run a change request action, answering its coded errors with their status.

    Unity Catalog is read as the user: 403 ``user_token_required`` without the
    user's token (401 when Unity Catalog refuses it), 503
    ``user_client_unavailable``, 404 ``metric_view_not_found`` when the user
    can't read the metric view.
    """
    try:
        return call()
    except ChangeRequestError as e:
        raise HTTPException(status_code=e.http_status, detail=str(e)) from e
    except MetricViewNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except UserTokenRequiredError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to %s a change request of the metric view of asset %s",
                         action, asset_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The change request action failed",
        )


def _user_client_or_raise(request: Request):
    try:
        return _user_workspace_client(request)
    except UserTokenRequiredError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except UserClientUnavailableError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e


@assets_router.get(
    "/{asset_id}/metric-view/change-requests",
    response_model=List[MetricViewChangeRequestRead],
)
def list_metric_view_change_requests(
    asset_id: UUID,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    manager=Depends(get_assets_manager),
):
    """The definition change requests of the metric view behind an asset, newest first.

    Only for users who can read the asset and, in Unity Catalog, the metric view
    (read as the user, as ``GET /{asset_id}/metric-view``).
    """
    _ensure_asset_readable(request, db, current_user, manager, asset_id)
    ws_client = _user_client_or_raise(request)
    requests = _change_requests(request, db)

    def call():
        requests.read_metric_view(asset_id, ws_client)
        return requests.list_for_asset(asset_id)
    return _change_request_call('list', asset_id, call)


@assets_router.post(
    "/{asset_id}/metric-view/change-requests",
    response_model=MetricViewChangeRequestDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def create_metric_view_change_request(
    asset_id: UUID,
    body: MetricViewChangeRequestCreate,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    manager=Depends(get_assets_manager),
):
    """A draft change of the metric view's definition, against the one Unity Catalog has now.

    422 with a coded error when the proposed YAML doesn't parse
    (``metric_view_definition_invalid_yaml`` with ``line`` and ``column``), has
    no source, contains ``$$``, repeats a field name or equals the current
    definition; 409 ``metric_view_base_unreadable`` when the current one can't
    be parsed.
    """
    _ensure_asset_readable(request, db, current_user, manager, asset_id)
    ws_client = _user_client_or_raise(request)
    return _change_request_call('create', asset_id, lambda: _change_requests(request, db)
                                .create_draft(asset_id, ws_client, body, current_user.email))


@assets_router.get(
    "/{asset_id}/metric-view/change-requests/{request_id}",
    response_model=MetricViewChangeRequestDetail,
)
def get_metric_view_change_request(
    asset_id: UUID,
    request_id: UUID,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    manager=Depends(get_assets_manager),
):
    """One change request with its base and proposed definitions, parsed, for the review."""
    _ensure_asset_readable(request, db, current_user, manager, asset_id)
    ws_client = _user_client_or_raise(request)
    requests = _change_requests(request, db)

    def call():
        requests.read_metric_view(asset_id, ws_client)
        return requests.get(asset_id, request_id)
    return _change_request_call('read', asset_id, call)


@assets_router.post(
    "/{asset_id}/metric-view/change-requests/{request_id}/submit",
    response_model=MetricViewChangeRequestRead,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def submit_metric_view_change_request(
    asset_id: UUID,
    request_id: UUID,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    manager=Depends(get_assets_manager),
):
    """Run the pre-checks as the requester and start the review workflow.

    409 ``metric_view_base_stale`` when the view changed in Unity Catalog since
    the draft, 409 or 422 for a materialization constraint, 409
    ``metric_view_change_no_approval`` when no workflow asks for an approval.
    """
    _ensure_asset_readable(request, db, current_user, manager, asset_id)
    ws_client = _user_client_or_raise(request)
    return _change_request_call('submit', asset_id, lambda: _change_requests(request, db)
                                .submit(asset_id, request_id, ws_client, current_user.email))


@assets_router.post(
    "/{asset_id}/metric-view/change-requests/{request_id}/cancel",
    response_model=MetricViewChangeRequestRead,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def cancel_metric_view_change_request(
    asset_id: UUID,
    request_id: UUID,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    manager=Depends(get_assets_manager),
):
    """Cancel a draft or a request in review (the requester, or an assets admin)."""
    _ensure_asset_readable(request, db, current_user, manager, asset_id)
    is_admin = _user_has_assets_feature(request, current_user, FeatureAccessLevel.ADMIN)
    return _change_request_call('cancel', asset_id, lambda: _change_requests(request, db)
                                .cancel(asset_id, request_id, current_user.email,
                                        is_admin=is_admin))


# ===================== Asset Relationships =====================

@assets_router.post(
    "/relationships",
    response_model=AssetRelationshipRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def add_asset_relationship(
    request: Request,
    rel_in: AssetRelationshipCreate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager=Depends(get_assets_manager),
):
    """Creates a relationship between two assets."""
    success = False
    details = {"params": {"source": str(rel_in.source_asset_id), "target": str(rel_in.target_asset_id), "type": rel_in.relationship_type}}
    try:
        result = manager.add_relationship(db=db, rel_in=rel_in, current_user_id=current_user.email)
        success = True
        return result
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        logger.exception("Failed to add asset relationship")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to add relationship")
    finally:
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="ADD_RELATIONSHIP", success=success, details=details,
        )


@assets_router.delete(
    "/relationships/{relationship_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def remove_asset_relationship(
    relationship_id: UUID,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager=Depends(get_assets_manager),
):
    """Removes a relationship between assets."""
    success = False
    details = {"params": {"relationship_id": str(relationship_id)}}
    try:
        manager.remove_relationship(db=db, relationship_id=relationship_id)
        success = True
        return None
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.exception("Failed to remove asset relationship")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to remove relationship")
    finally:
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="REMOVE_RELATIONSHIP", success=success, details=details,
        )


def register_routes(app):
    app.include_router(asset_types_router)
    app.include_router(assets_router)
    logger.info("Asset routes registered with prefix /api/asset-types, /api/assets")
