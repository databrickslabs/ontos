"""Routes that read Databricks on behalf of the user require the user's token.

Without ``x-forwarded-access-token`` these routes used to read with the app's
own (service principal) client. Now ``get_obo_workspace_client`` refuses with
403 ``user_token_required`` (outside ENV=LOCAL), and the app's client is not
used for the read. One test per route family that takes the on-behalf-of client.

The integration conftest routes every workspace getter to a mock; these tests put
the real ``get_obo_workspace_client`` back and spy on the app's client getter.
"""
import uuid
from unittest.mock import MagicMock

import pytest

from src.common import config as config_module
from src.common import workspace_client as workspace_client_module
from src.common.workspace_client import (
    USER_TOKEN_REQUIRED_MESSAGE,
    get_obo_workspace_client as REAL_GET_OBO_WORKSPACE_CLIENT,
)
from src.routes import domain_sync_routes, llm_search_routes, ontology_generator_routes

CODED_403 = {'code': 'user_token_required', 'message': USER_TOKEN_REQUIRED_MESSAGE, 'params': {}}


@pytest.fixture
def app_client(monkeypatch, test_settings):
    """ENV=PROD, the real on-behalf-of helper, and a spy for the app's own client."""
    monkeypatch.setattr(test_settings, 'ENV', 'PROD')
    monkeypatch.setattr(config_module, '_settings', test_settings)
    for module in (workspace_client_module, domain_sync_routes, llm_search_routes,
                   ontology_generator_routes):
        monkeypatch.setattr(module, 'get_obo_workspace_client', REAL_GET_OBO_WORKSPACE_CLIENT)
    spy = MagicMock(name='get_workspace_client')
    monkeypatch.setattr(workspace_client_module, 'get_workspace_client', spy)
    return spy


def _assert_refused(response):
    assert response.status_code == 403, response.text
    assert response.json() == {'detail': CODED_403}


def test_data_catalog_is_refused_without_the_user_token(client, app_client):
    _assert_refused(client.get('/api/data-catalog/columns'))
    app_client.assert_not_called()


def test_catalog_commander_does_not_browse_as_the_app(client, app_client):
    """The commander takes the app's client explicitly too (admin operations), so
    that one is built; the catalog listing must not run on it."""
    response = client.get('/api/catalogs')

    _assert_refused(response)
    app_client.return_value.catalogs.list.assert_not_called()


def test_domain_sync_is_refused_without_the_user_token(client, app_client):
    _assert_refused(client.post('/api/domain-sync/import/preview', json={}))
    app_client.assert_not_called()


def test_llm_search_is_refused_without_the_user_token(client, app_client):
    _assert_refused(client.get('/api/llm-search/status'))
    app_client.assert_not_called()


def test_ontology_generation_from_a_connection_is_refused(client, app_client):
    response = client.post('/api/ontology/generate-from-connection', json={
        'connection_id': str(uuid.uuid4()),
        'selected_paths': ['main.sales.orders'],
    })

    _assert_refused(response)
    app_client.assert_not_called()


def test_workflow_http_connections_are_refused(client, app_client):
    _assert_refused(client.get('/api/workflows/http-connections'))
    app_client.assert_not_called()


def test_directory_http_connections_are_empty_not_read_as_the_app(client, app_client):
    """This route answers an unavailable client with an empty list (unchanged)."""
    response = client.get('/api/directory/uc-http-connections')

    assert response.status_code == 200, response.text
    assert response.json() == []
    app_client.assert_not_called()


def test_local_development_keeps_the_app_client(client, app_client, test_settings):
    test_settings.ENV = 'LOCAL'
    app_client.return_value.connections.list.return_value = []

    response = client.get('/api/workflows/http-connections')

    assert response.status_code == 200, response.text
    app_client.assert_called_once()


def test_the_users_token_selects_the_users_client(client, app_client, monkeypatch):
    user_client = MagicMock(name='user client')
    user_client.connections.list.return_value = []
    built = MagicMock(name='WorkspaceClient', return_value=user_client)
    monkeypatch.setattr(workspace_client_module, '_CLIENT_CACHE', {})
    monkeypatch.setattr(workspace_client_module, 'WorkspaceClient', built)
    monkeypatch.setattr(workspace_client_module, '_verify_workspace_client', lambda c, **k: c)
    monkeypatch.setattr(workspace_client_module, 'CachingWorkspaceClient', lambda c, timeout=30: c)

    response = client.get('/api/workflows/http-connections',
                          headers={'x-forwarded-access-token': 'user-token-1234'})

    assert response.status_code == 200, response.text
    assert built.call_args.kwargs['token'] == 'user-token-1234'
    user_client.connections.list.assert_called_once()
    app_client.assert_not_called()
