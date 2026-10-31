"""Concept links on a metric view and on its dimensions and measures (#1124).

A metric view is linked as ``uc_table`` (``catalog.schema.view``), a dimension
or measure as ``uc_column`` (``catalog.schema.view.field``), in the shared
``entity_semantic_links`` table.
"""
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.errors import NotFound, PermissionDenied
from databricks.sdk.service.catalog import TableType

from src.common.metric_views import parse_metric_view_definition
from src.controller.metric_views_manager import MetricViewNotFoundError, MetricViewsManager
from src.controller.semantic_links_manager import SemanticLinksManager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.models.semantic_links import EntitySemanticLinkCreate

VIEW = 'main.sales.orders_mv'
NET_REVENUE = 'http://example.com/glossary#NetRevenue'
ORDER_MONTH = 'http://example.com/glossary#OrderMonth'
SALES = 'http://example.com/glossary#Sales'

SPEC_YAML = """\
version: 1.1
source: main.sales.orders
dimensions:
  - name: Order Month
    expr: DATE_TRUNC('MONTH', order_date)
measures:
  - name: Total Revenue
    expr: SUM(amount)
  - name: Orders
    expr: COUNT(*)
"""
SPEC = parse_metric_view_definition(SPEC_YAML)


@pytest.fixture
def links(db_session):
    # The knowledge graph is updated on add/remove; a mock stands in for it
    return SemanticLinksManager(db_session, semantic_models_manager=MagicMock())


def _link(links, entity_type, entity_id, iri):
    return links.add(
        EntitySemanticLinkCreate(entity_type=entity_type, entity_id=entity_id, iri=iri),
        created_by='steward@example.com',
    )


def _field(result, name):
    return next(f for f in result.fields if f.name == name)


class TestListForMetricView:
    def test_link_and_unlink_a_measure_as_uc_column(self, links):
        created = _link(links, 'uc_column', f'{VIEW}.Total Revenue', NET_REVENUE)

        result = links.list_for_metric_view(VIEW, SPEC)
        measure = _field(result, 'Total Revenue')
        assert measure.kind == 'measure'
        assert measure.entity_id == f'{VIEW}.Total Revenue'
        assert [link.iri for link in measure.links] == [NET_REVENUE]
        assert [link.entity_type for link in measure.links] == ['uc_column']

        assert links.remove(created.id) is True
        assert _field(links.list_for_metric_view(VIEW, SPEC), 'Total Revenue').links == []

    def test_links_are_listed_per_field_and_for_the_view(self, links):
        _link(links, 'uc_table', VIEW, SALES)
        _link(links, 'uc_column', f'{VIEW}.Order Month', ORDER_MONTH)
        _link(links, 'uc_column', f'{VIEW}.Total Revenue', NET_REVENUE)

        result = links.list_for_metric_view(VIEW, SPEC)

        assert result.view_entity_id == VIEW
        assert [link.iri for link in result.view_links] == [SALES]
        # Dimensions first, then measures, in the definition's order
        assert [(f.kind, f.name) for f in result.fields] == [
            ('dimension', 'Order Month'), ('measure', 'Total Revenue'), ('measure', 'Orders'),
        ]
        assert [link.iri for link in _field(result, 'Order Month').links] == [ORDER_MONTH]
        assert [link.iri for link in _field(result, 'Total Revenue').links] == [NET_REVENUE]
        assert _field(result, 'Orders').links == []
        assert result.removed_fields == []

    def test_a_removed_field_keeps_its_links_and_is_flagged(self, links):
        _link(links, 'uc_column', f'{VIEW}.Gross Revenue', NET_REVENUE)

        result = links.list_for_metric_view(VIEW, SPEC)

        assert [f.name for f in result.fields] == ['Order Month', 'Total Revenue', 'Orders']
        assert len(result.removed_fields) == 1
        removed = result.removed_fields[0]
        assert removed.name == 'Gross Revenue'
        assert removed.kind is None
        assert removed.entity_id == f'{VIEW}.Gross Revenue'
        assert [link.iri for link in removed.links] == [NET_REVENUE]

    def test_links_of_other_views_and_columns_are_not_listed(self, links):
        # Same prefix without the dot, and a LIKE wildcard in place of the underscore
        _link(links, 'uc_column', 'main.sales.orders_mv2.Total Revenue', NET_REVENUE)
        _link(links, 'uc_column', 'main.sales.ordersXmv.Orders', NET_REVENUE)
        # A table link on the view's column FQN is not a field link
        _link(links, 'uc_table', f'{VIEW}.Orders', NET_REVENUE)

        result = links.list_for_metric_view(VIEW, SPEC)

        assert all(f.links == [] for f in result.fields)
        assert result.removed_fields == []
        assert result.view_links == []

    def test_the_view_name_is_matched_lower_case(self, links):
        _link(links, 'uc_column', f'{VIEW}.Orders', NET_REVENUE)

        result = links.list_for_metric_view('Main.Sales.Orders_MV', SPEC)

        assert result.view_entity_id == VIEW
        assert [link.iri for link in _field(result, 'Orders').links] == [NET_REVENUE]

    def test_unparsed_definition_returns_only_the_view_links(self, links):
        _link(links, 'uc_table', VIEW, SALES)
        _link(links, 'uc_column', f'{VIEW}.Orders', NET_REVENUE)

        result = links.list_for_metric_view(VIEW, None)

        assert [link.iri for link in result.view_links] == [SALES]
        assert result.fields == []
        assert result.removed_fields == []


def _asset(db_session, *, platform='databricks', location=VIEW):
    asset_type = AssetTypeDb(name=f'View-{uuid.uuid4().hex[:6]}', category='data')
    db_session.add(asset_type)
    db_session.flush()
    asset = AssetDb(
        name='orders_mv', asset_type_id=asset_type.id, platform=platform, location=location,
    )
    db_session.add(asset)
    db_session.flush()
    return asset


def _ws(table=None, error=None):
    ws = MagicMock()
    if error is not None:
        ws.tables.get.side_effect = error
    else:
        ws.tables.get.return_value = table
    return ws


def _table(table_type, view_definition):
    return SimpleNamespace(table_type=table_type, view_definition=view_definition)


class TestMetricViewOfAsset:
    def test_reads_the_definition_and_the_links(self, db_session, links):
        asset = _asset(db_session)
        _link(links, 'uc_column', f'{VIEW}.Total Revenue', NET_REVENUE)
        ws = _ws(_table(TableType.METRIC_VIEW, SPEC_YAML))

        result = MetricViewsManager(db_session, links).get_for_asset(asset.id, ws)

        ws.tables.get.assert_called_once_with(full_name=VIEW)
        assert result.definition == SPEC_YAML
        assert [m['name'] for m in result.metric_view['measures']] == ['Total Revenue', 'Orders']
        assert [link.iri for link in _field(result.links, 'Total Revenue').links] == [NET_REVENUE]

    def test_unparseable_definition_is_returned_raw(self, db_session, links):
        asset = _asset(db_session)
        ws = _ws(_table(TableType.METRIC_VIEW, 'not: [valid'))

        result = MetricViewsManager(db_session, links).get_for_asset(asset.id, ws)

        assert result.definition == 'not: [valid'
        assert result.metric_view is None
        assert result.links.fields == []

    @pytest.mark.parametrize('table_type', [TableType.VIEW, TableType.MANAGED])
    def test_another_kind_of_table_is_not_a_metric_view(self, db_session, links, table_type):
        asset = _asset(db_session)
        ws = _ws(_table(table_type, 'SELECT 1'))

        with pytest.raises(MetricViewNotFoundError) as err:
            MetricViewsManager(db_session, links).get_for_asset(asset.id, ws)
        assert err.value.code == 'metric_view_not_found'
        assert err.value.params == {'assetId': str(asset.id)}

    @pytest.mark.parametrize('error', [NotFound('gone'), PermissionDenied('no access')])
    def test_not_found_or_denied_in_unity_catalog(self, db_session, links, error):
        asset = _asset(db_session)

        with pytest.raises(MetricViewNotFoundError):
            MetricViewsManager(db_session, links).get_for_asset(asset.id, _ws(error=error))

    @pytest.mark.parametrize('platform,location', [
        ('snowflake', VIEW),            # not a Databricks asset
        ('databricks', 'main.sales'),   # not catalog.schema.name
        ('databricks', None),
    ])
    def test_assets_without_a_uc_name_are_not_looked_up(
        self, db_session, links, platform, location
    ):
        asset = _asset(db_session, platform=platform, location=location)
        ws = _ws(_table(TableType.METRIC_VIEW, SPEC_YAML))

        with pytest.raises(MetricViewNotFoundError):
            MetricViewsManager(db_session, links).get_for_asset(asset.id, ws)
        ws.tables.get.assert_not_called()

    def test_unknown_asset(self, db_session, links):
        with pytest.raises(MetricViewNotFoundError):
            MetricViewsManager(db_session, links).get_for_asset(uuid.uuid4(), _ws())

    def test_platform_is_matched_case_insensitively(self, db_session, links):
        asset = _asset(db_session, platform='Databricks')
        ws = _ws(_table(TableType.METRIC_VIEW, SPEC_YAML))

        assert MetricViewsManager(db_session, links).get_for_asset(asset.id, ws).metric_view

    def test_no_workspace_client(self, db_session, links):
        asset = _asset(db_session)

        with pytest.raises(MetricViewNotFoundError):
            MetricViewsManager(db_session, links).get_for_asset(asset.id, None)
