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
