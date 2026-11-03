"""Callers that turn an unavailable on-behalf-of client into "no client".

Schema import and the directory picker catch the helper's error and go on with
no workspace client, so their connectors fail instead of reading as the app.
Before, a request without the user's token handed them the app's own client.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import src.common.workspace_client as wc
from src.routes import directory_routes, schema_import_routes


@pytest.fixture
def app_client(monkeypatch):
    spy = MagicMock(name='get_workspace_client')
    monkeypatch.setattr(wc, 'get_workspace_client', spy)
    monkeypatch.setattr(wc, 'get_settings', lambda: SimpleNamespace(ENV='PROD'))
    return spy


def test_schema_import_gets_no_client_without_the_user_token(monkeypatch, app_client):
    monkeypatch.setattr(schema_import_routes, 'get_settings', lambda: SimpleNamespace(ENV='PROD'))
    monkeypatch.setattr(
        'src.common.manager_dependencies.get_assets_manager', lambda request: MagicMock()
    )

    manager = schema_import_routes._get_manager(SimpleNamespace(headers={}), db=MagicMock())

    assert manager._connections._ws_client is None
    app_client.assert_not_called()


def test_the_directory_context_gets_no_client_without_the_user_token(app_client):
    context = directory_routes._build_context(SimpleNamespace(headers={}), db=None)

    assert context.ws_client is None
    app_client.assert_not_called()
