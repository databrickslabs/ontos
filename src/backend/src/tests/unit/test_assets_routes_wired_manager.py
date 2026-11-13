"""The /api/assets routes must use the AssetsManager wired at startup.

Startup builds ``app.state.assets_manager`` and gives it the search manager and
the ontology. The module-level singleton has neither, so a route that uses it
never updates the search index.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from src.controller.assets_manager import AssetsManager, assets_manager as singleton
from src.routes import assets_routes


def _request(app: FastAPI) -> Request:
    return Request({"type": "http", "app": app, "headers": []})


def test_get_assets_manager_returns_startup_instance():
    app = FastAPI()
    wired = AssetsManager()
    app.state.assets_manager = wired

    assert assets_routes.get_assets_manager(_request(app)) is wired
    assert wired is not singleton


def test_get_assets_manager_without_request_is_the_singleton():
    assert assets_routes.get_assets_manager() is singleton


def test_get_assets_manager_with_request_but_no_wired_manager_is_503():
    """Never the singleton: it would skip the search index update silently."""
    with pytest.raises(HTTPException) as exc:
        assets_routes.get_assets_manager(_request(FastAPI()))
    assert exc.value.status_code == 503


def test_route_resolves_manager_with_search_manager_and_ontology():
    """Through the real dependency, the handler sees the wired manager."""
    app = FastAPI()
    wired = AssetsManager()
    wired.set_search_manager(MagicMock())
    wired._ontology = MagicMock()
    app.state.assets_manager = wired

    seen = {}

    @app.get("/probe")
    def probe(manager=assets_routes.Depends(assets_routes.get_assets_manager)):
        seen["manager"] = manager
        return {}

    assert TestClient(app).get("/probe").status_code == 200
    assert seen["manager"] is wired
    assert seen["manager"]._search_manager is not None
    assert seen["manager"]._ontology is not None

