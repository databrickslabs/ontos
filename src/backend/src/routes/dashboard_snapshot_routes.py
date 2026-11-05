"""Dashboard snapshot routes: read, refresh and opt out of a Dashboard asset's snapshot."""

from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.common.authorization import PermissionChecker
from src.common.config import get_settings
from src.common.dependencies import AuditCurrentUserDep, DBSessionDep
from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger
from src.common.workspace_client import get_obo_workspace_client
from src.controller.connections_manager import ConnectionsManager
from src.controller.dashboard_snapshot_manager import (
    OPT_OUT_PROPERTY,
    SNAPSHOT_PROPERTY,
    DashboardSnapshotManager,
)
from src.db_models.assets import AssetDb

logger = get_logger(__name__)

router = APIRouter(prefix="/api/assets", tags=["Dashboard Snapshots"])
FEATURE_ID = "assets"


class SnapshotSettings(BaseModel):
    opt_out: bool = Field(..., description="Never capture snapshots of this dashboard")


class SnapshotResponse(BaseModel):
    snapshot: Dict[str, Any] = Field(default_factory=dict)
    opt_out: bool = False
    supported: bool = Field(False, description="Whether the asset's connection can render snapshots")


def _get_snapshot_manager() -> DashboardSnapshotManager:
    return DashboardSnapshotManager()


def _asset(db, asset_id: UUID) -> AssetDb:
    asset = db.get(AssetDb, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


def _connection_id(asset: AssetDb) -> Optional[UUID]:
    raw = (asset.properties or {}).get("connection_id")
    try:
        return UUID(str(raw)) if raw else None
    except ValueError:
        return None


def _response(asset: AssetDb) -> SnapshotResponse:
    props = asset.properties or {}
    return SnapshotResponse(
        snapshot=dict(props.get(SNAPSHOT_PROPERTY) or {}),
        opt_out=bool(props.get(OPT_OUT_PROPERTY)),
        supported=_connection_id(asset) is not None,
    )


@router.get("/{asset_id}/snapshot", response_model=SnapshotResponse)
def get_snapshot(
    asset_id: UUID,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    return _response(_asset(db, asset_id))


@router.post("/{asset_id}/snapshot", response_model=SnapshotResponse)
def refresh_snapshot(
    asset_id: UUID,
    request: Request,
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
    manager: DashboardSnapshotManager = Depends(_get_snapshot_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Capture a new snapshot now, even when the dashboard has user-based filters (an explicit choice)."""
    asset = _asset(db, asset_id)
    connection_id = _connection_id(asset)
    if connection_id is None:
        raise HTTPException(status_code=400, detail="This asset was not imported from a connection that renders snapshots")

    ws = None
    try:
        ws = get_obo_workspace_client(request, get_settings())
    except Exception:
        pass
    connector = ConnectionsManager(db=db, workspace_client=ws).get_connector_for_connection(connection_id)
    if connector is None:
        raise HTTPException(status_code=404, detail="The asset's connection no longer exists")

    try:
        manager.capture(db, asset=asset, connector=connector, current_user=current_user.username if current_user else None, force=True)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error(f"Snapshot refresh for asset {asset_id} failed: {exc}", exc_info=True)
        raise HTTPException(status_code=502, detail="Could not capture a snapshot from the source system")
    db.refresh(asset)
    return _response(asset)


@router.put("/{asset_id}/snapshot/settings", response_model=SnapshotResponse)
def update_snapshot_settings(
    asset_id: UUID,
    payload: SnapshotSettings,
    db: DBSessionDep,
    manager: DashboardSnapshotManager = Depends(_get_snapshot_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    asset = _asset(db, asset_id)
    manager.set_opt_out(db, asset, payload.opt_out)
    db.commit()
    db.refresh(asset)
    return _response(asset)


def register_routes(app):
    app.include_router(router)
    logger.info("Dashboard snapshot routes registered")
