"""Who may read an asset (issue #347), shared by the routes that serve asset data.

Moved out of ``routes/assets_routes.py`` so the metadata and costs routes can
use the same rule without importing the assets routes.
"""
from uuid import UUID

from fastapi import HTTPException, Request, status

from src.common.api_errors import CodedValueError
from src.common.authorization import user_passes_permission_check
from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger

logger = get_logger(__name__)

ASSETS_FEATURE_ID = "assets"


class AssetReadDeniedError(CodedValueError):
    """The user may not read the asset (no ``assets`` READ_WRITE, no linked product)."""

    code = 'asset_read_denied'


class AssetWriteDeniedError(CodedValueError):
    """The user may not change the asset's data (no ``assets`` READ_WRITE)."""

    code = 'asset_write_denied'


class AssetNotFoundError(CodedValueError):
    """No asset has the given id."""

    code = 'asset_not_found'


def get_data_products_manager(request: Request):
    """Pull the DataProductsManager singleton from app.state.

    Returns None when not configured (e.g. early in tests); callers must
    handle that defensively rather than raising — scoping should fail closed
    (i.e. return empty for non-admins) rather than 500.
    """
    return getattr(request.app.state, "data_products_manager", None)


def user_has_assets_feature(request: Request, current_user, level: FeatureAccessLevel) -> bool:
    """Check whether the current user has the ``assets`` feature at ``level``.

    Used for branching: when a Data Consumer lacks the feature, we still
    allow DP-scoped reads of linked assets (issue #347), but block writes.
    Resolved as ``PermissionChecker`` does (role switcher, groups, roles
    assigned by email, team role override), so reads and writes agree.
    """
    try:
        return user_passes_permission_check(request, current_user, ASSETS_FEATURE_ID, level)
    except Exception:
        logger.exception("Failed to check assets feature for user")
        return False


def ensure_asset_readable(request: Request, db, current_user, manager, asset_id: UUID) -> None:
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

    is_unscoped = user_has_assets_feature(request, current_user, FeatureAccessLevel.READ_WRITE)

    if not is_unscoped:
        dpm = get_data_products_manager(request)
        if dpm is None or not manager.is_asset_accessible(
            db, asset_id=asset_id, data_products_manager=dpm, is_admin=False,
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Asset is not linked to a Data Product accessible to this user.",
            )
