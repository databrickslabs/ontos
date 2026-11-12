"""Bulk import uses the wired AssetsManager and indexes the assets it writes."""
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Request

from src.controller.asset_bulk_manager import AssetBulkManager
from src.controller.assets_manager import AssetsManager, assets_manager as singleton
from src.routes import asset_bulk_routes


def _request(app: FastAPI) -> Request:
    return Request({"type": "http", "app": app, "headers": []})


def test_bulk_manager_gets_the_startup_assets_manager():
    app = FastAPI()
    wired = AssetsManager()
    app.state.assets_manager = wired

    manager = asset_bulk_routes.get_bulk_manager(_request(app))

    assert manager._assets_manager is wired


def test_bulk_manager_without_request_falls_back_to_singleton():
    assert asset_bulk_routes.get_bulk_manager()._assets_manager is singleton


def test_bulk_import_updates_the_search_index_for_created_assets():
    wired = MagicMock(spec=AssetsManager)
    manager = AssetBulkManager(assets_manager=wired)
    db = MagicMock()
    created = MagicMock()
    created.id = "11111111-1111-1111-1111-111111111111"

    with patch.object(manager, "_resolve_asset_types", return_value={"table": created.id}), \
         patch.object(manager, "_set_asset_domains"), \
         patch.object(manager._asset_repo, "get_by_identity", return_value=None), \
         patch("src.controller.asset_bulk_manager.AssetDb", return_value=created):
        result = manager.execute_import(
            db,
            file_bytes=b"name,asset_type\nfoo,table\n",
            filename="a.csv",
            current_user_id="u@x.com",
        )

    assert result.created == 1, result.items
    wired._update_search_index.assert_called_once_with(created)


def _run_update(csv_bytes, get_return, identity_return):
    wired = MagicMock(spec=AssetsManager)
    manager = AssetBulkManager(assets_manager=wired)
    updated = MagicMock()
    updated.id = "11111111-1111-1111-1111-111111111111"

    with patch.object(manager, "_resolve_asset_types", return_value={"table": updated.id}), \
         patch.object(manager, "_set_asset_domains"), \
         patch.object(manager._asset_repo, "get", return_value=get_return), \
         patch.object(manager._asset_repo, "get_by_identity", return_value=identity_return), \
         patch.object(manager._asset_repo, "update", return_value=updated):
        result = manager.execute_import(
            MagicMock(), file_bytes=csv_bytes, filename="a.csv", current_user_id="u@x.com",
        )
    return wired, updated, result


def test_bulk_import_updates_the_search_index_for_updates_by_id():
    existing = MagicMock()
    wired, updated, result = _run_update(
        b"id,name,asset_type\n11111111-1111-1111-1111-111111111111,foo,table\n",
        get_return=existing, identity_return=None,
    )

    assert result.updated == 1, result.items
    wired._update_search_index.assert_called_once_with(updated)


def test_bulk_import_updates_the_search_index_for_updates_by_identity():
    wired, updated, result = _run_update(
        b"name,asset_type\nfoo,table\n", get_return=None, identity_return=MagicMock(),
    )

    assert result.updated == 1, result.items
    wired._update_search_index.assert_called_once_with(updated)


def test_bulk_import_keeps_going_when_indexing_fails():
    wired = MagicMock(spec=AssetsManager)
    wired._update_search_index.side_effect = RuntimeError("index down")
    manager = AssetBulkManager(assets_manager=wired)
    asset = MagicMock()
    asset.id = "11111111-1111-1111-1111-111111111111"

    manager._index_asset(asset)

    wired._update_search_index.assert_called_once_with(asset)


def test_bulk_manager_without_assets_manager_skips_indexing():
    AssetBulkManager()._index_asset(MagicMock())
