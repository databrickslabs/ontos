"""Navigation presets (#1325): preview, apply and undo menu and home settings of the default
roles. Admin-only, like the role create and update routes."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status

from src.common.authorization import PermissionChecker
from src.common.dependencies import AuditCurrentUserDep, AuditManagerDep
from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger
from src.common.manager_dependencies import get_navigation_presets_manager
from src.controller.navigation_presets_manager import (
    NavigationPresetNothingToUndoError,
    NavigationPresetsManager,
    NavigationPresetUnknownError,
)
from src.models.navigation_presets import (
    NavigationPresetApplyResult,
    NavigationPresetsResponse,
    NavigationPresetUndoResult,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["Navigation Presets"])

SETTINGS_FEATURE_ID = "settings"
ROLES_ADMIN = PermissionChecker('settings-roles', FeatureAccessLevel.ADMIN)


def _ref_ids(roles) -> list:
    return [r.role_id for r in roles]


async def _audit(
    audit_manager, background_tasks: BackgroundTasks, request: Request, current_user,
    action: str, success: bool, details: dict,
) -> None:
    """Log an apply or undo. A success is logged after the response, like the role routes.
    A failure answers with an HTTP error, and FastAPI drops the background tasks of an error
    response, so it is logged here before the error goes out."""
    fields = dict(
        username=current_user.username,
        ip_address=request.client.host if request.client else None,
        feature=SETTINGS_FEATURE_ID,
        action=action,
        success=success,
        details=details,
    )
    if success:
        background_tasks.add_task(audit_manager.log_action_background, **fields)
        return
    try:
        await audit_manager.log_action_background(**fields)
    except Exception:
        logger.warning("Could not audit failed %s", action, exc_info=True)


@router.get("/settings/navigation-presets", response_model=NavigationPresetsResponse)
async def list_navigation_presets(
    manager: NavigationPresetsManager = Depends(get_navigation_presets_manager),
    _: bool = Depends(ROLES_ADMIN),
):
    """Every preset with what it would do to each of its roles, and the last application."""
    try:
        return manager.get_presets()
    except Exception:
        logger.error("Error listing navigation presets", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list navigation presets")


@router.post(
    "/settings/navigation-presets/undo", response_model=NavigationPresetUndoResult,
)
async def undo_navigation_preset(
    request: Request,
    background_tasks: BackgroundTasks,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: NavigationPresetsManager = Depends(get_navigation_presets_manager),
    _: bool = Depends(ROLES_ADMIN),
):
    """Restore the menus and home sections the last preset application changed."""
    success = False
    details: dict = {}
    try:
        result = manager.undo(
            user=current_user.email if current_user else None,
            background_tasks=background_tasks,
        )
        success = True
        details.update(
            preset_id=result.preset_id,
            restored_role_ids=_ref_ids(result.restored_roles),
            missing_roles=result.missing_roles,
        )
        return result
    except NavigationPresetNothingToUndoError as e:
        details["exception"] = str(e)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except Exception as e:
        logger.error("Error undoing navigation preset", exc_info=True)
        details["exception"] = str(e)
        raise HTTPException(status_code=500, detail="Failed to undo navigation preset")
    finally:
        await _audit(
            audit_manager, background_tasks, request, current_user,
            "UNDO_NAVIGATION_PRESET", success, details,
        )


@router.post(
    "/settings/navigation-presets/{preset_id}/apply",
    response_model=NavigationPresetApplyResult,
)
async def apply_navigation_preset(
    preset_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: NavigationPresetsManager = Depends(get_navigation_presets_manager),
    _: bool = Depends(ROLES_ADMIN),
):
    """Apply a preset: set the menus and home sections of its roles (never their access)."""
    success = False
    details: dict = {"preset_id": preset_id}
    try:
        result = manager.apply(
            preset_id,
            user=current_user.email if current_user else None,
            background_tasks=background_tasks,
        )
        success = True
        details.update(
            changed_role_ids=_ref_ids(result.changed_roles),
            missing_roles=result.missing_roles,
        )
        return result
    except NavigationPresetUnknownError as e:
        details["exception"] = str(e)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except Exception as e:
        logger.error("Error applying navigation preset %s", preset_id, exc_info=True)
        details["exception"] = str(e)
        raise HTTPException(status_code=500, detail="Failed to apply navigation preset")
    finally:
        await _audit(
            audit_manager, background_tasks, request, current_user,
            "APPLY_NAVIGATION_PRESET", success, details,
        )


def register_routes(app):
    """Register routes with the app"""
    app.include_router(router)
    logger.info("Navigation presets routes registered")
