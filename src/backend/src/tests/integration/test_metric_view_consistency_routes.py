"""The KPI consistency routes (#1263, phase 1): by concept, by asset, and the link check.

Unity Catalog is asked, as the user, whether each view in a response is
readable; only those views' definitions are returned. Without the user's token
no definition is, and the measures, assets, concepts and verdicts still are.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.errors import PermissionDenied
from databricks.sdk.service.catalog import TableType

from src.common.metric_views import parse_metric_view_definition
from src.controller.metric_view_consistency_manager import store_metric_view
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.semantic_links import EntitySemanticLinkDb
from src.models.assets import METRIC_VIEW_ASSET_TYPE

REVENUE = 'http://example.com/glossary#Revenue'
NET_SALES = 'http://example.com/glossary#NetSales'
GROSS_VIEW, NET_VIEW = 'main.sales.revenue_gross', 'main.sales.revenue_net'
TOKEN = {'x-forwarded-access-token': 'user-token', 'X-Forwarded-Email': 'user@example.com'}


def _yaml(expr):
    return ("version: 1.1\nsource: main.sales.orders\nmeasures:\n"
            f"  - name: Revenue\n    expr: {expr}\n")


@pytest.fixture
def views(db_session):
    asset_type = db_session.query(AssetTypeDb).filter_by(name=METRIC_VIEW_ASSET_TYPE).first()
    if asset_type is None:
        asset_type = AssetTypeDb(name=METRIC_VIEW_ASSET_TYPE, category='data')
        db_session.add(asset_type)
        db_session.flush()
    made = {}
    for fqn, expr in ((GROSS_VIEW, 'SUM(gross_amount)'), (NET_VIEW, 'SUM(amount - refunds)')):
        asset = AssetDb(name=fqn.rsplit('.', 1)[-1], asset_type_id=asset_type.id,
                        platform='databricks', location=fqn)
        db_session.add(asset)
        db_session.flush()
        store_metric_view(db_session, asset, parse_metric_view_definition(_yaml(expr)))
        made[fqn] = asset
    for fqn in (GROSS_VIEW, NET_VIEW):
        db_session.add(EntitySemanticLinkDb(
            entity_type='uc_column', entity_id=f'{fqn}.Revenue', iri=REVENUE))
    db_session.flush()
    return made


@pytest.fixture
def user_ws(monkeypatch):
    """The user's (OBO) client: reads the gross view, is refused the net one."""
    from src.routes import assets_routes

    ws = MagicMock()

    def _get(full_name=None, **kwargs):
        if full_name == NET_VIEW:
            raise PermissionDenied('no access')
        return SimpleNamespace(table_type=TableType.METRIC_VIEW, view_definition='')

    ws.tables.get.side_effect = _get
    monkeypatch.setattr(assets_routes, 'get_obo_workspace_client', lambda r, *a, **k: ws,
                        raising=False)
    return ws


class TestByConcept:
    def test_groups_and_shows_only_the_definitions_the_user_can_read(
            self, client, views, user_ws, mock_workspace_client):
        response = client.get('/api/metric-views/consistency',
                              params={'concept_iri': REVENUE}, headers=TOKEN)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body['verdict'] == 'conflict'
        by_view = {g['measures'][0]['view']: g for g in body['groups']}
        assert by_view[GROSS_VIEW]['definition']['expression'] == 'sum(gross_amount)'
        assert by_view[NET_VIEW]['definition'] is None
        assert by_view[NET_VIEW]['measures'][0]['readable'] is False
        assert by_view[NET_VIEW]['measures'][0]['asset_name'] == 'revenue_net'
        assert 'refunds' not in response.text
        # Asked as the user, never as the app
        mock_workspace_client.tables.get.assert_not_called()

    def test_without_the_user_token_no_definition_is_shown(self, client, views, user_ws):
        response = client.get('/api/metric-views/consistency', params={'concept_iri': REVENUE})

        assert response.status_code == 200, response.text
        body = response.json()
        assert body['verdict'] == 'conflict'
        assert [g['definition'] for g in body['groups']] == [None, None]
        assert 'gross_amount' not in response.text
        user_ws.tables.get.assert_not_called()

    def test_needs_semantic_models_read_access(self, client, views, user_ws, mock_test_user):
        mock_test_user.groups = []

        response = client.get('/api/metric-views/consistency',
                              params={'concept_iri': REVENUE}, headers=TOKEN)

        assert response.status_code == 403


class TestByAsset:
    def test_lists_the_conflicting_measures(self, client, views, user_ws):
        asset = views[GROSS_VIEW]

        response = client.get('/api/metric-views/consistency',
                              params={'asset_id': str(asset.id)}, headers=TOKEN)

        assert response.status_code == 200, response.text
        [measure] = response.json()['measures']
        assert measure['measure']['entity_id'] == f'{GROSS_VIEW}.Revenue'
        [match] = measure['matches']
        assert match['measure']['view'] == NET_VIEW
        assert match['verdict'] == 'conflict' and match['first_level'] == 'expression'
        assert match['differences'] is None  # the net view isn't readable by the user

    def test_an_unknown_asset_is_404(self, client, views, user_ws):
        response = client.get('/api/metric-views/consistency',
                              params={'asset_id': '00000000-0000-0000-0000-000000000000'},
                              headers=TOKEN)

        assert response.status_code == 404
        assert response.json()['detail']['code'] == 'metric_view_asset_not_found'

    def test_the_asset_must_be_readable_by_the_user(
            self, client, views, user_ws, mock_test_user):
        mock_test_user.groups = []

        response = client.get('/api/metric-views/consistency',
                              params={'asset_id': str(views[GROSS_VIEW].id)}, headers=TOKEN)

        assert response.status_code == 403


@pytest.mark.parametrize('params', [{}, {'concept_iri': REVENUE, 'asset_id': 'x'}])
def test_exactly_one_of_concept_and_asset_is_needed(client, views, params):
    if 'asset_id' in params:
        params = dict(params, asset_id='00000000-0000-0000-0000-000000000000')

    response = client.get('/api/metric-views/consistency', params=params)

    assert response.status_code == 400
    assert response.json()['detail']['code'] == 'consistency_query_invalid'


class TestLinkCheck:
    def test_warns_when_the_concept_has_other_definitions(self, client, views):
        response = client.get('/api/metric-views/consistency/link-check', params={
            'entity_id': f'{GROSS_VIEW}.Revenue', 'iri': REVENUE})

        assert response.status_code == 200, response.text
        [warning] = response.json()['warnings']
        assert warning['code'] == 'concept_has_other_definitions'
        assert warning['params'] == {'count': 1, 'measures': [f'{NET_VIEW}.Revenue']}

    def test_no_warning_for_a_new_concept(self, client, views):
        response = client.get('/api/metric-views/consistency/link-check', params={
            'entity_id': f'{GROSS_VIEW}.Revenue', 'iri': NET_SALES})

        assert response.status_code == 200
        assert response.json()['warnings'] == []

    def test_needs_semantic_models_read_access(self, client, views, mock_test_user):
        mock_test_user.groups = []

        response = client.get('/api/metric-views/consistency/link-check', params={
            'entity_id': f'{GROSS_VIEW}.Revenue', 'iri': REVENUE})

        assert response.status_code == 403
