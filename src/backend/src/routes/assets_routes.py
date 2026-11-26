from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Query, Request

from src.models.assets import (
    AssetTypeCreate, AssetTypeUpdate, AssetTypeRead, AssetTypeSummary,
    AssetCreate, AssetUpdate, AssetRead, AssetSummary, AssetUpdateResult,
    without_internal_properties,
    AssetRelationshipCreate, AssetRelationshipRead,
    PaginatedAssetSummary,
    DeletePreviewItem, CascadeDeleteRequest, CascadeDeleteResult,
)
from src.common import manager_dependencies
from src.controller.assets_manager import (
    AssetsManager, BelowFirstLevelNeedsOwnerError, assets_manager,
)
from src.controller.metric_views_manager import (
    MetricViewNotFoundError, MetricViewsManager, UserClientUnavailableError, UserTokenRequiredError,
)
from src.common.workspace_client import get_obo_workspace_client
from src.common.run_identity import RunIdentity
from src.controller.semantic_links_manager import SemanticLinksManager
from src.controller.uc_description_reset_manager import (
    NOT_SENT as _RESET_NOT_SENT, ResetError, UcDescriptionResetManager,
)
from src.controller.uc_description_sync_manager import (
    SyncOutcome, UcDescriptionSyncManager, write_failed_warning,
)
from src.controller.asset_description_history import (
    HistoryEntryNotFoundError, NoPreviousTextError, SOURCE_RESTORE, description_source,
    get_description_entry, list_description_history,
)
from src.controller.uc_description_drift_manager import UcDescriptionDriftManager
from src.models.asset_description import (
    DescriptionDrift, DescriptionHistory, DescriptionHistoryEntry, DescriptionResetRequest,
    DescriptionResetResult, DescriptionRestoreRequest, ResetSelectedRequest, ResetSelectedResult,
    UcCommentPreview,
)
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
from src.common.api_errors import CodedValueError
from src.common.errors import NotFoundError, ConflictError, ValidationError
from src.common.asset_access import (
    ensure_asset_readable, get_data_products_manager, user_has_assets_feature,
)
from src.common.logging import get_logger

logger = get_logger(__name__)

asset_types_router = APIRouter(prefix="/api/asset-types", tags=["Asset Types"])
assets_router = APIRouter(prefix="/api/assets", tags=["Assets"])
FEATURE_ID = "assets"


def get_assets_manager(request: Request = None) -> AssetsManager:
    """The AssetsManager wired at startup (``app.state.assets_manager``).

    That instance has the search manager and the ontology; the module-level
    singleton has neither, so using it would silently skip the search index
    update. With a request and no wired manager this raises 503 (same as every
    other manager dependency). The singleton is returned only without a request.
    """
    if request is None:
        return assets_manager
    return manager_dependencies.get_assets_manager(request)


# The read rule (issue #347) lives in a shared module, so the metadata and
# costs routes apply it too; the old names stay for the callers of this module.
_get_data_products_manager = get_data_products_manager
_user_has_assets_feature = user_has_assets_feature
_ensure_asset_readable = ensure_asset_readable


def _schedule_maturity_evaluation(
    db, background_tasks: BackgroundTasks, request: Request, asset_id, user_email,
) -> None:
    """Re-evaluate a table/view asset's maturity after the response is sent.

    Commits the request's changes first: the background task opens its own session
    and must see the asset as it is now, whatever the dependency teardown order.
    """
    from src.common.run_identity import RunIdentity
    from src.controller.maturity_evaluator import evaluate_asset_maturity_on_change
    db.commit()
    # The user's write: their own token reads the UC table, not the app's
    background_tasks.add_task(
        evaluate_asset_maturity_on_change, str(asset_id), evaluated_by=user_email,
        run_identity=RunIdentity.for_request(request),
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
    response_model=AssetUpdateResult,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def create_asset(
    request: Request,
    asset_in: AssetCreate,
    settings: SettingsDep,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    background_tasks: BackgroundTasks,
    manager=Depends(get_assets_manager),
):
    """Creates a new asset.

    With the Unity Catalog description setting on, a table, view or column
    description is written there too, as for an update (a new asset has no
    previous description, so an existing different comment is kept).
    """
    success = False
    details = {"params": {"name": asset_in.name, "type_id": str(asset_in.asset_type_id)}}
    created_id = None
    # Clients never set the internal keys (e.g. the Unity Catalog sync mark)
    asset_in = asset_in.model_copy(
        update={"properties": without_internal_properties(asset_in.properties)})
    try:
        result = manager.create_asset(db=db, asset_in=asset_in, current_user_id=current_user.email)
        db.commit()
        outcome = _write_back_description(
            db, settings, request, result.id,
            description_sent=True, previous_description=None, label=result.location,
        )
        result = AssetUpdateResult(**result.model_dump(), warnings=_warnings_of(outcome))
        result.description_sync = outcome.state
        if outcome.audit:
            details["uc_comment"] = outcome.audit
        # Commits: the audit says success only once the asset is stored
        _schedule_maturity_evaluation(db, background_tasks, request, result.id, current_user.email)
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
    except CodedValueError as e:
        # The lifecycle's refusal (a stage the group doesn't have, a move it
        # doesn't allow): its code reaches the UI
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
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
    owned_by_me: bool = Query(
        False, description="Only assets the current user owns (active business owner)",
    ),
    below_first_maturity_level: bool = Query(
        False,
        description=(
            "Only tables and views whose latest maturity evaluation reached no level; "
            "needs owned_by_me=true (400 below_first_maturity_level_needs_owned_by_me)"
        ),
    ),
):
    """Lists all assets with optional filters. Returns paginated results.

    ``owned_by_me`` narrows any of the branches below to the caller's owned assets, and
    ``below_first_maturity_level`` to the assets below the first maturity level.

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
    if below_first_maturity_level and not owned_by_me:
        # One UC read per candidate table: bounded only by the caller's own assets
        error = BelowFirstLevelNeedsOwnerError()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

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
        owner_email=(current_user.email or "") if owned_by_me else None,
        below_first_maturity_level=below_first_maturity_level,
        # A stored level is shown only to a caller who reads its UC table themselves
        uc_workspace_client=(
            RunIdentity.for_request(request).workspace_client
            if below_first_maturity_level else None
        ),
    )


@assets_router.get(
    "/{asset_id}",
    response_model=AssetRead,
)
def get_asset(
    asset_id: UUID,
    request: Request,
    settings: SettingsDep,
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
    if not UcDescriptionSyncManager(settings).enabled:
        # Writing to Unity Catalog is off, so an older "not in sync" mark means nothing
        result.description_sync = None
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
    settings: SettingsDep,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    background_tasks: BackgroundTasks,
    manager=Depends(get_assets_manager),
):
    """Updates an existing asset; a table or view is re-evaluated for maturity afterwards."""
    success = False
    details = {"params": {"asset_id": str(asset_id)}}
    if asset_in.properties is not None:
        # model_copy would mark an unsent field as set, so only a sent one is replaced
        asset_in = asset_in.model_copy(
            update={"properties": without_internal_properties(asset_in.properties)})
    try:
        result = _save_asset_edit(
            db, settings, request, manager, asset_id, asset_in, current_user.email,
            background_tasks, details)
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
    except CodedValueError as e:
        # The lifecycle's refusal (a stage the group doesn't have, a move it
        # doesn't allow): its code reaches the UI
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
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


def _save_asset_edit(
    db, settings, request: Request, manager, asset_id: UUID, asset_in: AssetUpdate,
    user_email: str, background_tasks: BackgroundTasks, details: dict,
) -> AssetUpdateResult:
    """Save an edit of an asset, write a changed description to Unity Catalog (when the setting
    is on) and schedule the maturity evaluation. Fills the audit ``details``.

    The edit of a PUT and a restored description go through here, so a restore follows the
    same write-back rules, snapshot, search index and maturity evaluation as any edit.
    """
    # Read under the row lock this save holds until its commit, so a concurrent save of
    # the asset can't change the description in between (that would look like a
    # comment someone else wrote in Unity Catalog)
    existing = (
        db.query(AssetDb).filter(AssetDb.id == asset_id)
        .with_for_update().populate_existing().one_or_none()
    )
    previous_description = existing.description if existing is not None else None
    if existing is not None and 'description' in asset_in.model_fields_set:
        UcDescriptionSyncManager(settings).keep_baseline(db, existing)
    result = manager.update_asset(
        db=db, asset_id=asset_id, asset_in=asset_in, current_user_id=user_email)
    # The save is committed before Unity Catalog is written, so Unity Catalog never
    # gets ahead of a save that failed to commit. With the setting on, a changed
    # table, view or column description is then written as the user. A failed
    # write doesn't fail the save: the response carries a coded warning and the
    # asset's description_sync state.
    db.commit()
    outcome = _write_back_description(
        db, settings, request, asset_id,
        description_sent='description' in asset_in.model_fields_set,
        previous_description=previous_description, label=result.location,
    )
    result = AssetUpdateResult(**result.model_dump(), warnings=_warnings_of(outcome))
    result.description_sync = outcome.state
    if outcome.warning:
        details["uc_description_warning"] = outcome.warning.code
    if outcome.audit:
        details["uc_comment"] = outcome.audit
    # Commits: the audit says success only once the change is stored
    _schedule_maturity_evaluation(db, background_tasks, request, asset_id, user_email)
    return result


@assets_router.get(
    "/{asset_id}/description/uc-comment",
    response_model=UcCommentPreview,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def get_asset_uc_comment(
    asset_id: UUID,
    request: Request,
    settings: SettingsDep,
    db: DBSessionDep,
    manager=Depends(get_assets_manager),
):
    """The asset's description next to its Unity Catalog comment (read as the user).

    The diff the "use the Unity Catalog comment" dialog shows. Coded errors: 403
    ``user_token_required`` / ``uc_reset_permission_denied``, 404 ``uc_reset_object_not_found``,
    409 ``uc_reset_metric_view``, 400 ``uc_reset_not_applicable``, 502 ``uc_reset_unavailable``,
    503 ``user_client_unavailable``.
    """
    reset_manager = UcDescriptionResetManager(manager, UcDescriptionSyncManager(settings))
    return _reset_call(
        asset_id, lambda: reset_manager.preview(
            db, asset_id, user_client=lambda: _user_workspace_client(request)))


@assets_router.post(
    "/{asset_id}/description/reset-to-uc",
    response_model=DescriptionResetResult,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def reset_asset_description_to_uc(
    asset_id: UUID,
    request: Request,
    settings: SettingsDep,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    background_tasks: BackgroundTasks,
    reset_in: Optional[DescriptionResetRequest] = None,
    manager=Depends(get_assets_manager),
):
    """Replaces the description of a table, view or column asset with its Unity Catalog comment.

    The comment is read as the user (on-behalf-of token, no fallback to the app), so Unity
    Catalog decides who may read it. Nothing is written to Unity Catalog, so it works with the
    write-back setting off. An empty comment changes nothing (warning ``uc_description_empty``).
    ``expected_uc_comment``: the comment the user saw; 409 ``uc_reset_uc_changed`` when Unity
    Catalog has another now. Errors are those of the preview endpoint.
    """
    success = False
    details = {"params": {"asset_id": str(asset_id)}}
    expected = (
        reset_in.expected_uc_comment
        if reset_in is not None and 'expected_uc_comment' in reset_in.model_fields_set
        else _RESET_NOT_SENT
    )
    reset_manager = UcDescriptionResetManager(manager, UcDescriptionSyncManager(settings))
    try:
        outcome = _reset_call(asset_id, lambda: reset_manager.reset(
            db, asset_id, user_client=lambda: _user_workspace_client(request),
            username=current_user.email, expected_uc_comment=expected))
        details["description_reset"] = outcome.audit
        if outcome.result.changed:
            # Commits: the audit says success only once the change is stored
            _schedule_maturity_evaluation(
                db, background_tasks, request, asset_id, current_user.email)
        else:
            db.commit()
        success = True
        return outcome.result
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status": e.status_code}
        raise
    except Exception as e:
        logger.exception("Failed to reset the description of asset %s", asset_id)
        details["exception"] = {"type": type(e).__name__}
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reset the description") from e
    finally:
        if success:
            details["updated_resource_id"] = str(asset_id)
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="RESET_ASSET_DESCRIPTION", success=success,
            details=details,
        )


@assets_router.get(
    "/{asset_id}/description/history",
    response_model=DescriptionHistory,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
def get_asset_description_history(
    asset_id: UUID,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    manager=Depends(get_assets_manager),
):
    """The changes of a table, view or column description, newest first: who, when, where the
    change came from (``source``), and the text before and after. Needs ``assets`` READ_ONLY
    (not ``audit``) and the same read access to the asset as ``GET /api/assets/{id}`` (an
    asset outside the data products the user can access is refused alike): past descriptions
    are as visible as the asset itself."""
    _ensure_asset_readable(request, db, current_user, manager, asset_id)
    if not manager.asset_exists(db, asset_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Asset '{asset_id}' not found")
    total, entries = list_description_history(db, asset_id, skip=skip, limit=limit)
    items = []
    for entry in entries:
        data = entry.details
        items.append(DescriptionHistoryEntry(
            id=entry.id, timestamp=entry.timestamp, username=entry.username,
            source=data.get('source'), object_type=data.get('object_type'),
            before=data.get('before'), after=data.get('after'),
            restored_from=data.get('restored_from'),
        ))
    return DescriptionHistory(asset_id=asset_id, total=total, items=items)


@assets_router.post(
    "/{asset_id}/description/restore",
    response_model=AssetUpdateResult,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def restore_asset_description(
    asset_id: UUID,
    request: Request,
    restore_in: DescriptionRestoreRequest,
    settings: SettingsDep,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    background_tasks: BackgroundTasks,
    manager=Depends(get_assets_manager),
):
    """Restores a description of the history: a normal edit whose history entry has the source
    ``restore``, so the Unity Catalog write-back rules, the column snapshot, the search index
    and the maturity evaluation apply as for any edit. ``version`` is the text the entry set
    (``after``) or the one it replaced (``before``). 404 ``description_history_entry_not_found``
    for an entry that isn't a description change of this asset."""
    success = False
    details = {"params": {"asset_id": str(asset_id), "entry_id": restore_in.entry_id,
                          "version": restore_in.version}}
    try:
        # The same read access as the history it restores from (and as GET /api/assets/{id})
        _ensure_asset_readable(request, db, current_user, manager, asset_id)
        entry = get_description_entry(db, asset_id, restore_in.entry_id)
        if entry is None:
            raise HistoryEntryNotFoundError(
                "No such description change on this asset.", entry_id=restore_in.entry_id)
        text = entry.details.get(restore_in.version)
        if restore_in.version == 'before' and not text:
            # A first description: going back would empty it (and the Unity Catalog comment)
            raise NoPreviousTextError(
                "This change has no previous text to restore.", entry_id=restore_in.entry_id)
        with description_source(
                SOURCE_RESTORE, restored_from=entry.id, restored_version=restore_in.version):
            result = _save_asset_edit(
                db, settings, request, manager, asset_id, AssetUpdate(description=text),
                current_user.email, background_tasks, details)
        success = True
        return result
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status": e.status_code}
        raise
    except NotFoundError as e:
        details["exception"] = {"type": "NotFoundError"}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except HistoryEntryNotFoundError as e:
        details["exception"] = {"type": "HistoryEntryNotFoundError"}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except CodedValueError as e:
        details["exception"] = {"type": type(e).__name__}
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to restore the description of asset %s", asset_id)
        details["exception"] = {"type": type(e).__name__}
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to restore the description") from e
    finally:
        if success:
            details["updated_resource_id"] = str(asset_id)
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="RESTORE_ASSET_DESCRIPTION", success=success,
            details=details,
        )


def _drift_manager(manager, settings) -> UcDescriptionDriftManager:
    return UcDescriptionDriftManager(
        UcDescriptionResetManager(manager, UcDescriptionSyncManager(settings)))


@assets_router.get(
    "/{asset_id}/description/drift",
    response_model=DescriptionDrift,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def get_asset_description_drift(
    asset_id: UUID,
    request: Request,
    settings: SettingsDep,
    db: DBSessionDep,
    manager=Depends(get_assets_manager),
):
    """The descriptions of a table or view and its Column assets (or of one column) next to the
    Unity Catalog comments, from one read as the user, on demand. ``changed_in_uc``: the comment
    is not the one Ontos last saw (needs the baseline recorded at import, reset or write-back).
    Errors are those of the preview endpoint."""
    return _reset_call(asset_id, lambda: _drift_manager(manager, settings).compare(
        db, asset_id, user_client=lambda: _user_workspace_client(request)))


@assets_router.post(
    "/{asset_id}/description/reset-selected",
    response_model=ResetSelectedResult,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def reset_asset_descriptions_to_uc(
    asset_id: UUID,
    request: Request,
    reset_in: ResetSelectedRequest,
    settings: SettingsDep,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    background_tasks: BackgroundTasks,
    manager=Depends(get_assets_manager),
):
    """Resets the selected fields of a table (itself and its Column assets) to their Unity
    Catalog comments in one request, from one read as the user (``assets`` READ_WRITE). Each
    field answers on its own: one whose comment changed since it was shown
    (``expected_uc_comment``), or whose column is gone, reports a coded error and the others
    go on. Nothing is written to Unity Catalog."""
    success = False
    details = {"params": {"asset_id": str(asset_id), "fields": len(reset_in.fields)}}
    try:
        result = _reset_call(asset_id, lambda: _drift_manager(manager, settings).reset_many(
            db, asset_id, reset_in.fields, user_client=lambda: _user_workspace_client(request),
            username=current_user.email))
        details["results"] = [
            {"asset_id": str(r.asset_id), "changed": r.changed,
             "error": r.error.code if r.error else None} for r in result.results]
        if result.changed:
            # One commit and one maturity re-evaluation for the request (of the asset the user
            # reset from: a table's maturity follows its columns; a column has none)
            _schedule_maturity_evaluation(
                db, background_tasks, request, asset_id, current_user.email)
        else:
            db.commit()
        _reindex_after_commit(manager, db, [r.asset_id for r in result.results if r.changed])
        success = True
        return result
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status": e.status_code}
        raise
    except Exception as e:
        logger.exception("Failed to reset the descriptions under asset %s", asset_id)
        details["exception"] = {"type": type(e).__name__}
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reset the descriptions") from e
    finally:
        if success:
            details["updated_resource_id"] = str(asset_id)
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="RESET_ASSET_DESCRIPTIONS", success=success,
            details=details,
        )


def _reindex_after_commit(manager: AssetsManager, db, asset_ids) -> None:
    """Upsert the assets a committed request changed in the search index, with one call.

    Never raises: the change is stored, a stale index entry is rebuilt by the next reindex.
    """
    try:
        manager.upsert_search_index_for(db, asset_ids)
    except Exception:
        logger.warning("Could not update the search index after a reset", exc_info=True)


def _reset_call(asset_id: UUID, call):
    """``call()``, with the errors of a description reset as coded HTTP errors."""
    try:
        return call()
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ResetError as e:
        raise HTTPException(status_code=e.http_status, detail=str(e)) from e
    except UserTokenRequiredError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except UserClientUnavailableError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e


@assets_router.get(
    "/{asset_id}/infer-schema",
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
def infer_schema_from_asset(
    asset_id: UUID,
    db: DBSessionDep,
    manager=Depends(get_assets_manager),
    api_version: Optional[str] = Query(
        None,
        description="ODCS apiVersion of the target contract; below v3.1.0, timestamp "
        "columns are inferred as date and time columns as string. Default: v3.1.0.",
    ),
):
    """Extract ODCS-compatible schema objects from an asset and its children."""
    try:
        return manager.infer_schema_from_asset(db=db, asset_id=asset_id, api_version=api_version)
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


def _warnings_of(outcome: SyncOutcome) -> list:
    return [outcome.warning] if outcome.warning else []


def _write_back_description(
    db, settings, request: Request, asset_id, *, description_sent: bool,
    previous_description, label: str,
) -> SyncOutcome:
    """Write a committed save's description to Unity Catalog and commit the outcome.

    The column snapshot of a Column asset follows only a write that reached Unity
    Catalog. Never raises: the save is already committed, so an unexpected failure
    is a write-failed warning.
    """
    try:
        outcome = UcDescriptionSyncManager(settings).sync_after_update(
            db, asset_id,
            description_sent=description_sent,
            previous_description=previous_description,
            user_client=lambda: _user_workspace_client(request),
        )
        if outcome.in_sync:
            asset = db.get(AssetDb, asset_id)
            if asset is not None:
                AssetsManager.update_table_column_snapshot(db, asset)
        db.commit()
        return outcome
    except Exception as e:
        db.rollback()
        # The error's type only: its text and traceback can carry the SQL parameters,
        # i.e. the description
        logger.warning("Writing the description of asset %s to Unity Catalog failed: %s",
                       asset_id, type(e).__name__)
        return SyncOutcome(warning=write_failed_warning(label or str(asset_id)))


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
