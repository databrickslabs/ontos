"""The asset's metric view route returns its baseline and drift state (#1124 phase 2)."""
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.service.catalog import TableType

from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.metric_view_baselines import MetricViewBaselineDb

VIEW = 'main.sales.orders_mv'
SPEC = """\
version: 1.1
source: main.sales.orders
fields:
  - name: Order Month
    expr: DATE_TRUNC('MONTH', order_date)
measures:
  - name: Total Revenue
    expr: SUM(amount)
    display_name: Revenue
"""
# The same definition as Unity Catalog stores it
STORED = SPEC.replace('fields:', 'dimensions:').replace('    display_name: Revenue\n', '')
TOKEN = {'x-forwarded-access-token': 'user-token', 'X-Forwarded-Email': 'user@example.com'}


@pytest.fixture
def asset(db_session):
    asset_type = AssetTypeDb(name=f'Metric View-{uuid.uuid4().hex[:6]}', category='semantic')
    db_session.add(asset_type)
    db_session.flush()
    row = AssetDb(name='orders_mv', asset_type_id=asset_type.id, platform='databricks',
                  location=VIEW)
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def user_ws(monkeypatch):
    """The user's (OBO) workspace client; its view_definition is set per test."""
    from src.routes import assets_routes

    ws = MagicMock()
    ws.tables.get.return_value = SimpleNamespace(
        table_type=TableType.METRIC_VIEW, view_definition=SPEC, pipeline_id=None,
    )
    monkeypatch.setattr(assets_routes, 'get_obo_workspace_client', lambda request: ws,
                        raising=False)
    return ws


def _read(client, asset, user_ws, definition):
    user_ws.tables.get.return_value.view_definition = definition
    response = client.get(f'/api/assets/{asset.id}/metric-view', headers=TOKEN)
    assert response.status_code == 200, response.text
    return response.json()


class TestMetricViewDriftRoute:
    def test_the_first_read_records_the_baseline_in_sync(self, client, asset, user_ws, db_session):
        body = _read(client, asset, user_ws, SPEC)

        assert body['drift']['state'] == 'in_sync'
        baseline = body['baseline']
        assert baseline['digest'] == body['drift']['current_digest']
        assert len(baseline['digest']) == 64
        assert baseline['approved_at'] is None and baseline['request_id'] is None
        assert baseline['recorded_at']
        assert db_session.query(MetricViewBaselineDb).one().metric_view_fqn == VIEW

    def test_the_stored_rewrite_is_in_sync_and_an_edit_is_drift(self, client, asset, user_ws):
        first = _read(client, asset, user_ws, SPEC)

        assert _read(client, asset, user_ws, STORED)['drift']['state'] == 'in_sync'
        drifted = _read(client, asset, user_ws, SPEC.replace('SUM(amount)', 'SUM(net)'))
        assert drifted['drift']['state'] == 'drifted'
        assert drifted['baseline']['digest'] == first['baseline']['digest']
        assert drifted['drift']['current_digest'] != first['baseline']['digest']

    def test_an_unparseable_definition_is_unknown_not_an_error(self, client, asset, user_ws):
        _read(client, asset, user_ws, SPEC)

        body = _read(client, asset, user_ws, 'not: [valid')

        assert body['metric_view'] is None
        assert body['drift']['state'] == 'unknown'
        assert body['drift']['current_digest'] is None
        assert body['baseline'] is not None

    def test_a_failing_drift_check_still_returns_the_metric_view(
        self, client, asset, user_ws, monkeypatch
    ):
        from src.repositories.metric_view_baselines_repository import metric_view_baselines_repo

        def _fail(*args, **kwargs):
            raise RuntimeError('relation "metric_view_baselines" does not exist')

        monkeypatch.setattr(metric_view_baselines_repo, 'get_by_fqn', _fail)

        body = _read(client, asset, user_ws, SPEC)

        assert body['drift'] == {'state': 'unknown', 'current_digest': None,
                                 'last_checked_at': None}
        assert body['baseline'] is None
        assert [m['name'] for m in body['metric_view']['measures']] == ['Total Revenue']
        assert 'metric_view_baselines' not in str(body)

    def test_a_user_without_the_token_gets_no_drift_check(
        self, client, asset, user_ws, db_session
    ):
        response = client.get(f'/api/assets/{asset.id}/metric-view')

        assert response.status_code == 403
        assert db_session.query(MetricViewBaselineDb).count() == 0
