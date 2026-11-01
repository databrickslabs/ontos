"""Asset review content (definition, metric view, preview, analysis) is read as the user.

These routes read Unity Catalog with the review manager's client, the app's own,
for anyone with read access to asset reviews. They now take the user's
on-behalf-of client: without the user's token they answer 403
``user_token_required`` (outside ENV=LOCAL), and with it Unity Catalog is read
with the user's client, never the app's.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.common import config as config_module
from src.common import workspace_client as workspace_client_module
from src.common.workspace_client import (
    USER_TOKEN_REQUIRED_MESSAGE,
    get_obo_workspace_client as REAL_GET_OBO_WORKSPACE_CLIENT,
)
from src.models.data_asset_reviews import AssetType
from src.routes import data_asset_reviews_routes

BASE = '/api/data-asset-reviews/request-1/assets/asset-1'
CONTENT_ROUTES = [
    ('get', f'{BASE}/definition'),
    ('get', f'{BASE}/metric-view'),
    ('get', f'{BASE}/preview'),
    ('post', f'{BASE}/analyze'),
]
METRIC_VIEW_YAML = 'version: 0.1\nsource: main.sales.orders\n'


@pytest.fixture
def review_manager(client, monkeypatch, test_settings):
    """ENV=PROD, the real on-behalf-of helper, and the review manager's own client as a spy."""
    monkeypatch.setattr(test_settings, 'ENV', 'PROD')
    monkeypatch.setattr(config_module, '_settings', test_settings)
    for module in (workspace_client_module, data_asset_reviews_routes):
        monkeypatch.setattr(module, 'get_obo_workspace_client', REAL_GET_OBO_WORKSPACE_CLIENT)
    manager = client.app.state.data_asset_review_manager
    monkeypatch.setattr(manager, '_ws_client', _uc_client('app client'))
    return manager


def _uc_client(name: str) -> MagicMock:
    """A workspace client whose Unity Catalog reads answer like a small view."""
    uc = MagicMock(name=name)
    uc.tables.get.return_value = SimpleNamespace(
        view_definition=METRIC_VIEW_YAML, columns=[], properties={}
    )
    uc.sql.execute.return_value = SimpleNamespace(rows=[])
    return uc


@pytest.fixture
def user_client(monkeypatch):
    """The client built from the user's token, without the SDK or the network."""
    user = _uc_client('user client')
    monkeypatch.setattr(workspace_client_module, '_CLIENT_CACHE', {})
    monkeypatch.setattr(workspace_client_module, 'WorkspaceClient', MagicMock(return_value=user))
    monkeypatch.setattr(workspace_client_module, '_verify_workspace_client', lambda c, **k: c)
    monkeypatch.setattr(workspace_client_module, 'CachingWorkspaceClient', lambda c, timeout=30: c)
    return user


def _reviewed(monkeypatch, manager, asset_type: AssetType):
    asset = SimpleNamespace(asset_fqn='main.sales.revenue', asset_type=asset_type)
    monkeypatch.setattr(manager, 'get_reviewed_asset', lambda **kwargs: asset)


@pytest.mark.parametrize('method,path', CONTENT_ROUTES)
def test_without_the_user_token_review_content_is_refused(
    client, review_manager, monkeypatch, method, path
):
    asset_type = AssetType.METRIC if path.endswith('/metric-view') else (
        AssetType.TABLE if path.endswith('/preview') else AssetType.VIEW
    )
    _reviewed(monkeypatch, review_manager, asset_type)
    monkeypatch.setattr(review_manager, 'analyze_asset_content', lambda **kwargs: None)

    response = getattr(client, method)(path)

    assert response.status_code == 403, response.text
    assert response.json() == {'detail': {
        'code': 'user_token_required', 'message': USER_TOKEN_REQUIRED_MESSAGE, 'params': {},
    }}
    assert review_manager._ws_client.mock_calls == []


@pytest.mark.parametrize('path,asset_type', [
    (f'{BASE}/definition', AssetType.VIEW),
    (f'{BASE}/metric-view', AssetType.METRIC),
    (f'{BASE}/preview', AssetType.TABLE),
])
def test_with_the_user_token_unity_catalog_is_read_as_the_user(
    client, review_manager, user_client, monkeypatch, path, asset_type
):
    _reviewed(monkeypatch, review_manager, asset_type)

    response = client.get(path, headers={'x-forwarded-access-token': 'user-token-1234'})

    assert response.status_code == 200, response.text
    user_client.tables.get.assert_called_once_with(full_name='main.sales.revenue')
    assert review_manager._ws_client.mock_calls == []


def test_the_analysis_reads_the_definition_as_the_user(
    client, review_manager, user_client, monkeypatch
):
    _reviewed(monkeypatch, review_manager, AssetType.VIEW)
    monkeypatch.setattr(review_manager, 'analyze_asset_content', lambda **kwargs: None)

    response = client.post(f'{BASE}/analyze', headers={'x-forwarded-access-token': 'tok-1234'})

    # The analysis itself is stubbed out (no result), so the route answers 500.
    assert response.status_code == 500, response.text
    user_client.tables.get.assert_called_once_with(full_name='main.sales.revenue')
    assert review_manager._ws_client.mock_calls == []


def test_a_refused_analysis_is_audited(client, review_manager, monkeypatch, verify_audit_log):
    _reviewed(monkeypatch, review_manager, AssetType.VIEW)

    response = client.post(f'{BASE}/analyze')

    assert response.status_code == 403, response.text
    audit = verify_audit_log(feature='data-asset-reviews', action='ANALYZE_ASSET', success=False)
    assert audit.details['exception']['status_code'] == 403
