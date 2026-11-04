"""Creating a review request types its Unity Catalog assets as the user.

The type was read with the review manager's client (the app's own), so the
response told a view from a table even for an object the requester can't see.
The route now takes the user's on-behalf-of client when some FQN names a Unity
Catalog object: without the user's token it answers 403 ``user_token_required``
(outside ENV=LOCAL), audited; app-entity FQNs need no token.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.errors import PermissionDenied
from databricks.sdk.service.catalog import TableType

from src.common import config as config_module
from src.common import workspace_client as workspace_client_module
from src.common.workspace_client import (
    USER_TOKEN_REQUIRED_MESSAGE,
    get_obo_workspace_client as REAL_GET_OBO_WORKSPACE_CLIENT,
)
from src.routes import data_asset_reviews_routes

URL = '/api/data-asset-reviews'
TOKEN = {'x-forwarded-access-token': 'user-token-1234'}


def _payload(*fqns: str) -> dict:
    return {
        'requester_email': 'requester@example.com',
        'reviewer_email': 'reviewer@example.com',
        'asset_fqns': list(fqns),
    }


@pytest.fixture
def review_manager(client, monkeypatch, test_settings):
    """ENV=PROD, the real on-behalf-of helper, and an app client that sees a view."""
    monkeypatch.setattr(test_settings, 'ENV', 'PROD')
    monkeypatch.setattr(config_module, '_settings', test_settings)
    for module in (workspace_client_module, data_asset_reviews_routes):
        monkeypatch.setattr(module, 'get_obo_workspace_client', REAL_GET_OBO_WORKSPACE_CLIENT)
    manager = client.app.state.data_asset_review_manager
    app = MagicMock(name='app client')
    app.tables.get.return_value = SimpleNamespace(table_type=TableType.VIEW)
    monkeypatch.setattr(manager, '_ws_client', app)
    return manager


@pytest.fixture
def user_client(monkeypatch):
    """The client built from the user's token, without the SDK or the network."""
    user = MagicMock(name='user client')
    monkeypatch.setattr(workspace_client_module, '_CLIENT_CACHE', {})
    monkeypatch.setattr(workspace_client_module, 'WorkspaceClient', MagicMock(return_value=user))
    monkeypatch.setattr(workspace_client_module, '_verify_workspace_client', lambda c, **k: c)
    monkeypatch.setattr(workspace_client_module, 'CachingWorkspaceClient', lambda c, timeout=30: c)
    return user


def test_without_the_user_token_a_catalog_asset_is_refused_and_audited(
    client, review_manager, verify_audit_log
):
    response = client.post(URL, json=_payload('main.hr.v_salaries'))

    assert response.status_code == 403, response.text
    assert response.json() == {'detail': {
        'code': 'user_token_required', 'message': USER_TOKEN_REQUIRED_MESSAGE, 'params': {},
    }}
    assert review_manager._ws_client.mock_calls == []
    audit = verify_audit_log(feature='data-asset-reviews', action='CREATE', success=False)
    assert audit.details['exception']['status_code'] == 403


def test_with_the_user_token_assets_are_typed_as_the_user(client, review_manager, user_client):
    user_client.tables.get.return_value = SimpleNamespace(table_type=TableType.METRIC_VIEW)

    response = client.post(URL, json=_payload('main.sales.revenue'), headers=TOKEN)

    assert response.status_code == 201, response.text
    assert [a['asset_type'] for a in response.json()['assets']] == ['metric']
    user_client.tables.get.assert_called_once_with(full_name='main.sales.revenue')
    assert review_manager._ws_client.mock_calls == []


def test_an_object_the_user_cant_see_is_typed_like_a_missing_one(
    client, review_manager, user_client
):
    user_client.tables.get.side_effect = PermissionDenied('User does not have USE SCHEMA')
    user_client.functions.get.side_effect = PermissionDenied('User does not have USE SCHEMA')

    response = client.post(URL, json=_payload('main.hr.v_salaries'), headers=TOKEN)

    # The app's client would have said "view"
    assert response.status_code == 201, response.text
    assert [a['asset_type'] for a in response.json()['assets']] == ['table']
    assert review_manager._ws_client.mock_calls == []


def test_app_entities_need_no_user_token(client, review_manager):
    response = client.post(URL, json=_payload('product:p-1', 'contract:c-1'))

    assert response.status_code == 201, response.text
    assert [a['asset_type'] for a in response.json()['assets']] == [
        'data_product', 'data_contract',
    ]
    assert review_manager._ws_client.mock_calls == []
