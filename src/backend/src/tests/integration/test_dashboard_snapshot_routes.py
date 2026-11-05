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
