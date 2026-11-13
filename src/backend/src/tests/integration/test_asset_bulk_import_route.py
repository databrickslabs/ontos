"""POST /api/assets/bulk/import indexes the assets it commits and nothing it rolls back."""
import uuid

from src.controller.asset_bulk_manager import AssetBulkManager


def _upload(name, type_name):
    body = f"name,asset_type\n{name},{type_name}\n".encode()
    return {"file": ("assets.csv", body, "text/csv")}


def _indexed_ids(client, query):
    # Test-only: the raw index entries behind search, without the permission filter.
    return [item.id for item in client.app.state.search_manager._backend.search_items(query)]


def _asset_type(client):
    name = f"Type {uuid.uuid4().hex[:8]}"
    resp = client.post("/api/asset-types", json={"name": name, "category": "data"})
    assert resp.status_code == 201, resp.text
    return name


def test_bulk_import_route_indexes_committed_assets(client):
    type_name = _asset_type(client)
    name = f"route-{uuid.uuid4().hex[:8]}"

    resp = client.post("/api/assets/bulk/import", files=_upload(name, type_name))

    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 1, resp.text
    assert any(hit.startswith("asset::") for hit in _indexed_ids(client, name))


def test_bulk_import_route_failure_leaves_no_index_entries(client, monkeypatch):
    type_name = _asset_type(client)
    name = f"rollback-{uuid.uuid4().hex[:8]}"

    def boom(self, *args, **kwargs):
        raise RuntimeError("parent wiring failed")

    monkeypatch.setattr(AssetBulkManager, "_wire_parent_relationships", boom)
    resp = client.post("/api/assets/bulk/import", files=_upload(name, type_name))

    assert resp.status_code == 500, resp.text
    assert _indexed_ids(client, name) == []
