"""The metric view routes return the concept links of the view and of each field (#1124)."""
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.errors import PermissionDenied
from databricks.sdk.service.catalog import TableType

from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.data_asset_reviews import DataAssetReviewRequestDb, ReviewedAssetDb
from src.db_models.semantic_links import EntitySemanticLinkDb

VIEW = 'main.sales.orders_mv'
NET_REVENUE = 'http://example.com/glossary#NetRevenue'
SPEC = """\
version: 1.1
source: main.sales.orders
dimensions:
  - name: Order Month
    expr: DATE_TRUNC('MONTH', order_date)
measures:
  - name: Total Revenue
    expr: SUM(amount)
"""


@pytest.fixture
def metric_view(mock_workspace_client):
    mock_workspace_client.tables.get.return_value = SimpleNamespace(
        table_type=TableType.METRIC_VIEW, view_definition=SPEC,
    )
    return mock_workspace_client


@pytest.fixture
def links(db_session):
    db_session.add_all([
        EntitySemanticLinkDb(entity_type='uc_column', entity_id=f'{VIEW}.Total Revenue',
                             iri=NET_REVENUE),
        EntitySemanticLinkDb(entity_type='uc_column', entity_id=f'{VIEW}.Gross Revenue',
                             iri=NET_REVENUE),
    ])
    db_session.flush()


@pytest.fixture
def asset(db_session):
    asset_type = AssetTypeDb(name=f'View-{uuid.uuid4().hex[:6]}', category='data')
    db_session.add(asset_type)
    db_session.flush()
    row = AssetDb(name='orders_mv', asset_type_id=asset_type.id, platform='databricks',
                  location=VIEW)
    db_session.add(row)
    db_session.flush()
    return row


def _assert_links(links):
    assert links['view_entity_id'] == VIEW
    measure = next(f for f in links['fields'] if f['name'] == 'Total Revenue')
    assert measure['kind'] == 'measure'
    assert measure['entity_id'] == f'{VIEW}.Total Revenue'
    assert [link['iri'] for link in measure['links']] == [NET_REVENUE]
    assert [f['name'] for f in links['removed_fields']] == ['Gross Revenue']


TOKEN = {'x-forwarded-access-token': 'user-token', 'X-Forwarded-Email': 'user@example.com'}


def _table(table_type, view_definition):
    return SimpleNamespace(table_type=table_type, view_definition=view_definition)


@pytest.fixture
def user_ws(monkeypatch):
    """The user's (OBO) workspace client, distinct from the app's mock_workspace_client."""
    from src.routes import assets_routes

    ws = MagicMock()
    ws.tables.get.return_value = _table(TableType.METRIC_VIEW, SPEC)
    calls = []

    def _obo(request, *args, **kwargs):
        calls.append(request.headers.get('x-forwarded-access-token'))
        return ws

    monkeypatch.setattr(assets_routes, 'get_obo_workspace_client', _obo, raising=False)
    ws.obo_calls = calls
    return ws


class TestAssetMetricViewRoute:
    def test_reads_unity_catalog_as_the_user(
        self, client, asset, user_ws, mock_workspace_client, links
    ):
        # The app's client could read it too: it must not be the one asked
        mock_workspace_client.tables.get.return_value = _table(TableType.METRIC_VIEW, SPEC)

        response = client.get(f'/api/assets/{asset.id}/metric-view', headers=TOKEN)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body['definition'] == SPEC
        assert [d['name'] for d in body['metric_view']['dimensions']] == ['Order Month']
        _assert_links(body['links'])
        assert user_ws.obo_calls == ['user-token']
        user_ws.tables.get.assert_called_once_with(full_name=VIEW)
        mock_workspace_client.tables.get.assert_not_called()

    def test_without_the_user_token_it_refuses_and_reads_nothing(
        self, client, asset, user_ws, mock_workspace_client
    ):
        mock_workspace_client.tables.get.return_value = _table(TableType.METRIC_VIEW, SPEC)

        response = client.get(f'/api/assets/{asset.id}/metric-view')

        assert response.status_code == 403
        assert response.json()['detail']['code'] == 'user_token_required'
        assert user_ws.obo_calls == []
        mock_workspace_client.tables.get.assert_not_called()

    def test_a_user_client_that_fails_to_build_is_refused_without_its_text(
        self, client, asset, monkeypatch, mock_workspace_client
    ):
        from src.routes import assets_routes

        def _broken(request, *args, **kwargs):
            raise RuntimeError('secret host https://adb-1.example.com token dapi123')

        monkeypatch.setattr(assets_routes, 'get_obo_workspace_client', _broken, raising=False)
        mock_workspace_client.tables.get.return_value = _table(TableType.METRIC_VIEW, SPEC)

        response = client.get(f'/api/assets/{asset.id}/metric-view', headers=TOKEN)

        assert response.status_code == 503
        assert response.json()['detail']['code'] == 'user_client_unavailable'
        assert 'dapi123' not in response.text and 'adb-1' not in response.text
        mock_workspace_client.tables.get.assert_not_called()

    def test_a_view_the_user_cannot_read_is_not_found(
        self, client, asset, user_ws, mock_workspace_client
    ):
        user_ws.tables.get.side_effect = PermissionDenied('no SELECT on the view')
        mock_workspace_client.tables.get.return_value = _table(TableType.METRIC_VIEW, SPEC)

        response = client.get(f'/api/assets/{asset.id}/metric-view', headers=TOKEN)

        assert response.status_code == 404
        assert response.json()['detail']['code'] == 'metric_view_not_found'
        assert 'no SELECT' not in response.text
        mock_workspace_client.tables.get.assert_not_called()

    def test_a_plain_view_answers_a_coded_404(self, client, asset, user_ws):
        user_ws.tables.get.return_value = _table(TableType.VIEW, 'SELECT 1')

        response = client.get(f'/api/assets/{asset.id}/metric-view', headers=TOKEN)

        assert response.status_code == 404
        detail = response.json()['detail']
        assert detail['code'] == 'metric_view_not_found'
        assert detail['params'] == {'assetId': str(asset.id)}

    def test_unknown_asset_answers_a_coded_404(self, client, user_ws):
        response = client.get(f'/api/assets/{uuid.uuid4()}/metric-view', headers=TOKEN)

        assert response.status_code == 404
        assert response.json()['detail']['code'] == 'metric_view_not_found'


class TestReviewMetricViewRoute:
    def test_the_review_definition_carries_the_links(
        self, client, db_session, metric_view, links
    ):
        request_id, asset_id = str(uuid.uuid4()), str(uuid.uuid4())
        db_session.add(DataAssetReviewRequestDb(
            id=request_id, requester_email='a@example.com', reviewer_email='b@example.com',
        ))
        db_session.flush()
        db_session.add(ReviewedAssetDb(
            id=asset_id, review_request_id=request_id, asset_fqn=VIEW, asset_type='metric',
        ))
        db_session.flush()

        response = client.get(f'/api/data-asset-reviews/{request_id}/assets/{asset_id}/metric-view')

        assert response.status_code == 200, response.text
        body = response.json()
        assert [m['name'] for m in body['metric_view']['measures']] == ['Total Revenue']
        _assert_links(body['links'])
