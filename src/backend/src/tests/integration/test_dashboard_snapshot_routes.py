"""Dashboard snapshot routes: read state, opt out, refresh guard."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.db_models.assets import AssetDb, AssetTypeDb


@pytest.fixture
def dashboard(db_session):
    asset_type = db_session.query(AssetTypeDb).filter_by(name="Dashboard").first()
    if asset_type is None:
        asset_type = AssetTypeDb(id=uuid4(), name="Dashboard")
        db_session.add(asset_type)
        db_session.flush()
    asset = AssetDb(id=uuid4(), name="Orders Overview", asset_type_id=asset_type.id, platform="tableau",
                    location="p~p1.wb~wb1.v~v1", properties={"snapshot": {"status": "ok", "document_id": "d-1"}})
    db_session.add(asset)
    db_session.flush()
    return asset


def test_get_snapshot_state(client: TestClient, dashboard):
    response = client.get(f"/api/assets/{dashboard.id}/snapshot")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["snapshot"]["status"] == "ok"
    assert body["opt_out"] is False
    assert body["supported"] is False  # not imported through a connection


def test_opt_out_is_stored(client: TestClient, dashboard):
    response = client.put(f"/api/assets/{dashboard.id}/snapshot/settings", json={"opt_out": True})
    assert response.status_code == 200, response.text
    assert response.json()["opt_out"] is True
    assert client.get(f"/api/assets/{dashboard.id}/snapshot").json()["opt_out"] is True


def test_refresh_needs_a_source_connection(client: TestClient, dashboard):
    response = client.post(f"/api/assets/{dashboard.id}/snapshot")
    assert response.status_code == 400


def test_unknown_asset_is_404(client: TestClient):
    assert client.get(f"/api/assets/{uuid4()}/snapshot").status_code == 404


@pytest.fixture
def imported(dashboard, db_session):
    dashboard.properties = {**dashboard.properties, "connection_id": str(uuid4())}
    db_session.flush()
    return dashboard


def _refresh(client, asset, monkeypatch, connector, capture):
    from src.app import app
    from src.controller.connections_manager import ConnectionsManager
    from src.routes import dashboard_snapshot_routes as routes
    monkeypatch.setattr(ConnectionsManager, "get_connector_for_connection", lambda self, cid: connector)

    class Manager:
        def capture(self, db, *, asset, connector, current_user, force=False):
            return capture(asset)

    app.dependency_overrides[routes._get_snapshot_manager] = lambda: Manager()
    try:
        return client.post(f"/api/assets/{asset.id}/snapshot")
    finally:
        app.dependency_overrides.pop(routes._get_snapshot_manager, None)


def test_refresh_captures_through_the_connection(client: TestClient, imported, monkeypatch):
    def capture(asset):
        asset.properties = {**asset.properties, "snapshot": {"status": "auth_expired"}}
    response = _refresh(client, imported, monkeypatch, object(), capture)
    assert response.status_code == 200, response.text
    assert response.json()["snapshot"]["status"] == "auth_expired"


def test_refresh_with_a_deleted_connection_is_404(client: TestClient, imported, monkeypatch):
    assert _refresh(client, imported, monkeypatch, None, lambda a: None).status_code == 404


def test_refresh_failure_is_502(client: TestClient, imported, monkeypatch):
    def capture(asset):
        raise RuntimeError("boom")
    assert _refresh(client, imported, monkeypatch, object(), capture).status_code == 502
