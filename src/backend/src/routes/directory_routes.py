"""Directory layer API: status, search, test, and provider-agnostic settings.

Settings keys live in the existing ``app_settings`` key/value table so
no Alembic migration is required. All Graph traffic flows through a UC
HTTP Connection; the app never holds a client secret or token.

See plans/directory-lookup-and-principal-picker.md.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from src.common.authorization import PermissionChecker
from src.common.database import get_db
from src.common.dependencies import DirectoryManagerDep
from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger
from src.common.uc_connections import list_http_connections
from src.controller.directory_providers import DirectoryError
from src.models.directory import (
    DirectorySearchResponse,
    DirectorySettingsUpdate,
    DirectoryStatus,
    DirectoryTestResult,
    SETTING_KEY_CONNECTION_NAME,
    SETTING_KEY_PROVIDER_TYPE,
)
from src.repositories.app_settings_repository import app_settings_repo

logger = get_logger(__name__)

router = APIRouter(prefix="/api/directory", tags=["Directory"])


@router.get("/status", response_model=DirectoryStatus)
async def get_status(
    manager: DirectoryManagerDep,
    db: Session = Depends(get_db),
    _: bool = Depends(PermissionChecker("settings", FeatureAccessLevel.READ_ONLY)),
) -> DirectoryStatus:
    """Lightweight status check.

    Returned to every picker instance on first render so the UI knows
    whether to switch into configured mode.
    """

    return manager.get_status(db)


@router.get("/search", response_model=DirectorySearchResponse)
async def search(
    request: Request,
    manager: DirectoryManagerDep,
    q: str = Query(..., min_length=1, max_length=200),
    types: Optional[str] = Query(
        default=None,
        description="Comma-separated subset of 'user,group'. Defaults to both.",
    ),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
    _: bool = Depends(PermissionChecker("settings", FeatureAccessLevel.READ_ONLY)),
) -> DirectorySearchResponse:
    """Search the configured directory and return normalised principals.

    Returns an empty list when the directory is not configured -- the
    picker's unconfigured mode handles the UX from there.
    """

    from src.common.workspace_client import get_obo_workspace_client

    parsed_types: List[str] = []
    if types:
        parsed_types = [t.strip() for t in types.split(",") if t.strip()]
    try:
        ws = get_obo_workspace_client(request)
    except Exception:
        # The picker is expected to degrade gracefully; treat workspace
        # client failure the same as an empty result.
        return DirectorySearchResponse(results=[])

    try:
        results = manager.search(db, ws, query=q, types=parsed_types, limit=limit)
    except DirectoryError as exc:
        logger.warning(f"Directory search failed: {exc}")
        return DirectorySearchResponse(results=[])
    return DirectorySearchResponse(results=results)


@router.post("/test", response_model=DirectoryTestResult)
async def test(
    request: Request,
    manager: DirectoryManagerDep,
    db: Session = Depends(get_db),
    _: bool = Depends(PermissionChecker("settings", FeatureAccessLevel.READ_WRITE)),
) -> DirectoryTestResult:
    """Probe the configured provider; surfaces a typed success/error to the UI."""

    from src.common.workspace_client import get_obo_workspace_client

    try:
        ws = get_obo_workspace_client(request)
    except Exception as exc:
        return DirectoryTestResult(healthy=False, error=f"Workspace client error: {exc}")

    try:
        manager.test(db, ws)
    except DirectoryError as exc:
        return DirectoryTestResult(healthy=False, error=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error during directory test")
        return DirectoryTestResult(healthy=False, error=f"Unexpected error: {exc}")
    return DirectoryTestResult(healthy=True)


@router.put("/settings", response_model=DirectoryStatus)
async def update_settings(
    body: DirectorySettingsUpdate,
    manager: DirectoryManagerDep,
    db: Session = Depends(get_db),
    _: bool = Depends(PermissionChecker("settings", FeatureAccessLevel.READ_WRITE)),
) -> DirectoryStatus:
    """Persist provider type and/or connection name, then invalidate cache.

    Either field may be ``None`` (or empty string) to clear that
    setting. Caller passes both for full updates; passing just one is
    an "edit one field" shortcut.
    """

    if body.provider_type is not None:
        app_settings_repo.set(db, SETTING_KEY_PROVIDER_TYPE, body.provider_type or None)
    if body.connection_name is not None:
        app_settings_repo.set(db, SETTING_KEY_CONNECTION_NAME, body.connection_name or None)
    manager.invalidate_cache()
    return manager.get_status(db)


@router.get("/uc-http-connections")
async def list_uc_http_connections(
    request: Request,
    _: bool = Depends(PermissionChecker("settings", FeatureAccessLevel.READ_WRITE)),
) -> List[dict]:
    """List HTTP-type UC connections so the Settings tab can populate its dropdown.

    Same payload shape as ``/api/workflows/http-connections``; both
    routes delegate to ``src.common.uc_connections.list_http_connections``.
    """

    from src.common.workspace_client import get_obo_workspace_client

    try:
        ws = get_obo_workspace_client(request)
    except Exception as exc:
        logger.warning(f"Workspace client unavailable for UC connections listing: {exc}")
        return []
    return list_http_connections(ws)


def register_routes(app):
    """Register directory routes with the FastAPI app."""

    app.include_router(router)
    logger.info("Directory routes registered with prefix /api/directory")
