"""The data product linked-assets route uses the wired AssetsManager."""
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Request

from src.controller.assets_manager import AssetsManager, assets_manager as singleton


def _request(app: FastAPI) -> Request:
    return Request({"type": "http", "app": app, "headers": []})


def test_dp_linked_assets_route_uses_the_wired_manager():
    import asyncio
    from types import SimpleNamespace
    from src.routes import data_product_routes as dpr

    app = FastAPI()
    wired = MagicMock(spec=AssetsManager)
    wired.get_all_assets.return_value = ["wired"]
    app.state.assets_manager = wired
    auth = MagicMock()
    auth.has_permission.return_value = True
    app.state.authorization_manager = auth
    dpm = MagicMock()
    dpm.list_linked_asset_ids_for_products.return_value = ["a1"]
    app.state.data_products_manager = dpm
    user = SimpleNamespace(email="u@x.com", groups=[])

    with patch.object(singleton, "get_all_assets", return_value=["singleton"]):
        result = asyncio.run(dpr.get_product_linked_assets(
            "p1", _request(app), MagicMock(), user, skip=0, limit=10, _=True,
        ))

    assert result == ["wired"]
    wired.get_all_assets.assert_called_once()
