"""Directory layer API: status, search, test, and provider-agnostic settings.

Settings keys live in the existing ``app_settings`` key/value table so
no Alembic migration is required. v1 ships three providers:

- ``entra``    — Microsoft Entra ID via Microsoft Graph (UC HTTP Connection)
- ``lakebase`` — A Postgres table on the app's primary Lakebase database
- ``file``     — A local CSV file (tests / demos)

See plans/directory-lookup-and-principal-picker.md.
"""

from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from src.common.authorization import PermissionChecker
from src.common.database import get_db
from src.common.dependencies import DirectoryManagerDep
from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger
from src.common.uc_connections import list_http_connections
from src.controller.directory_providers import (
    DirectoryError,
    DirectoryProviderContext,
)
from src.models.directory import (
    DirectorySearchResponse,
    DirectorySettingsUpdate,
    DirectoryStatus,
    DirectoryTestResult,
    SETTING_KEY_CONNECTION_NAME,
    SETTING_KEY_FILE_PATH,
    SETTING_KEY_LAKEBASE_TABLE,
    SETTING_KEY_PROVIDER_TYPE,
)
from src.repositories.app_settings_repository import app_settings_repo

logger = get_logger(__name__)

router = APIRouter(prefix="/api/directory", tags=["Directory"])


def _build_context(request: Request, db: Session) -> DirectoryProviderContext:
    """Assemble the per-request provider context.

    Each provider reads only the transport handles it cares about:
    Entra needs ``ws_client``, Lakebase needs ``db_engine``, File
    needs neither.
    """

    ws_client: Any = None
    try:
        from src.common.workspace_client import get_obo_workspace_client

        ws_client = get_obo_workspace_client(request)
    except Exception:
        ws_client = None

    db_engine = db.get_bind() if db is not None else None
    return DirectoryProviderContext(ws_client=ws_client, db_engine=db_engine)


@router.get("/status", response_model=DirectoryStatus)
async def get_status(
    manager: DirectoryManagerDep,
    db: Session = Depends(get_db),
    _: bool = Depends(PermissionChecker("settings-directory", FeatureAccessLevel.READ_ONLY)),
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
    _: bool = Depends(PermissionChecker("settings-directory", FeatureAccessLevel.READ_ONLY)),
) -> DirectorySearchResponse:
    """Search the configured directory and return normalised principals.

    Returns an empty list when the directory is not configured -- the
    picker's unconfigured mode handles the UX from there.
    """

    parsed_types: List[str] = []
    if types:
        parsed_types = [t.strip() for t in types.split(",") if t.strip()]
    ctx = _build_context(request, db)
    try:
        results = manager.search(db, ctx, query=q, types=parsed_types, limit=limit)
    except DirectoryError as exc:
        logger.warning(f"Directory search failed: {exc}")
        return DirectorySearchResponse(results=[])
    return DirectorySearchResponse(results=results)


@router.post("/test", response_model=DirectoryTestResult)
async def test(
    request: Request,
    manager: DirectoryManagerDep,
    db: Session = Depends(get_db),
    _: bool = Depends(PermissionChecker("settings-directory", FeatureAccessLevel.READ_WRITE)),
) -> DirectoryTestResult:
    """Probe the configured provider; surfaces a typed success/error to the UI."""

    ctx = _build_context(request, db)
    try:
        manager.test(db, ctx)
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
    _: bool = Depends(PermissionChecker("settings-directory", FeatureAccessLevel.READ_WRITE)),
) -> DirectoryStatus:
    """Persist any directory settings supplied, then invalidate cache.

    The caller passes the full set on save; missing fields are left
    untouched. Pass an explicit empty string to clear a setting.
    """

    if body.provider_type is not None:
        app_settings_repo.set(db, SETTING_KEY_PROVIDER_TYPE, body.provider_type or None)
    if body.connection_name is not None:
        app_settings_repo.set(db, SETTING_KEY_CONNECTION_NAME, body.connection_name or None)
    if body.lakebase_table is not None:
        app_settings_repo.set(db, SETTING_KEY_LAKEBASE_TABLE, body.lakebase_table or None)
    if body.file_path is not None:
        app_settings_repo.set(db, SETTING_KEY_FILE_PATH, body.file_path or None)
    manager.invalidate_cache()
    return manager.get_status(db)


@router.get("/uc-http-connections")
async def list_uc_http_connections(
    request: Request,
    _: bool = Depends(PermissionChecker("settings-directory", FeatureAccessLevel.READ_WRITE)),
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
