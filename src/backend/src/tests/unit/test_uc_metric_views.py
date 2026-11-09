"""Unity Catalog metric views are a type of their own (#912).

The Tables API returns a metric view with table_type METRIC_VIEW and its YAML
spec in view_definition. It was listed and typed as a table, and its
dimensions and measures were not shown anywhere.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.service.catalog import TableType

from src.common.metric_views import MAX_DEFINITION_LENGTH, parse_metric_view_definition
from src.connectors.base import ListAssetsOptions
from src.connectors.databricks import DatabricksConnector
from src.controller.catalog_commander_manager import CatalogCommanderManager
from src.controller.data_asset_reviews_manager import DataAssetReviewManager
from src.models.assets import UnifiedAssetType
from src.models.data_asset_reviews import AssetType

SPEC = """\
version: 1.1
source: main.sales.orders
filter: status = 'closed'
joins:
  - name: customers
    source: main.sales.customers
    on: source.customer_id = customers.id
dimensions:
  - name: Order Month
    expr: DATE_TRUNC('MONTH', order_date)
    comment: Month of the order
  - name: Region
    expr: customers.region
measures:
  - name: Total Revenue
    expr: SUM(amount)
    display_name: Revenue
  - expr: COUNT(*)
"""


def _table(name, table_type, view_definition=None):
    return SimpleNamespace(
        name=name, full_name=f"main.sales.{name}", table_type=table_type,
        comment=None, columns=[], table_constraints=[], owner="owner@example.com",
        properties={}, storage_location=None, catalog_name="main", schema_name="sales",
        view_definition=view_definition,
    )


TABLES = [
    _table("orders", TableType.MANAGED),
    _table("v_orders", TableType.VIEW),
    _table("mv_orders", TableType.MATERIALIZED_VIEW),
    _table("revenue_metrics", TableType.METRIC_VIEW, SPEC),
]


# --- Definition --------------------------------------------------------------


def test_the_definition_gives_source_dimensions_and_measures():
    spec = parse_metric_view_definition(SPEC)

    assert spec['version'] == '1.1'
    assert spec['source'] == 'main.sales.orders'
    assert spec['filter'] == "status = 'closed'"
    assert spec['joins'] == [{
        'name': 'customers', 'source': 'main.sales.customers',
        'on': 'source.customer_id = customers.id', 'using': None,
    }]
    assert spec['materialization'] is None
    assert spec['dimensions'] == [
        {'name': 'Order Month', 'expr': "DATE_TRUNC('MONTH', order_date)", 'comment': 'Month of the order'},
        {'name': 'Region', 'expr': 'customers.region'},
    ]
    # A measure without a name is skipped
    assert spec['measures'] == [
        {'name': 'Total Revenue', 'expr': 'SUM(amount)', 'display_name': 'Revenue'},
    ]


# As Unity Catalog stores them (seen on a workspace): a `using` join, and a
# materialized metric view whose block lists dimensions and measures by name
USING_AND_MATERIALIZED = """\
version: 1.1
source: main.sales.orders
joins:
  - name: store
    source: main.sales.stores
    using:
      - store_id
    joins:
      - name: region
        source: main.sales.regions
        "on": store.region_id = region.id
fields:
  - name: Status
    expr: status
measures:
  - name: Revenue
    expr: SUM(amount)
materialization:
  schedule: EVERY 6 HOURS
  mode: relaxed
  materialized_views:
    - name: by_status
      type: aggregated
      dimensions:
        - Status
      measures:
        - Revenue
"""


def test_using_joins_nested_joins_fields_and_materialization_are_read():
    spec = parse_metric_view_definition(USING_AND_MATERIALIZED)

    assert spec['joins'] == [
        {'name': 'store', 'source': 'main.sales.stores', 'on': None, 'using': ['store_id']},
        {'name': 'region', 'source': 'main.sales.regions',
         'on': 'store.region_id = region.id', 'using': None},
    ]
    # `fields` is the current docs' name for dimensions
    assert [d['name'] for d in spec['dimensions']] == ['Status']
    assert spec['materialization'] == {
        'schedule': 'EVERY 6 HOURS', 'mode': 'relaxed',
        'materialized_views': [{'name': 'by_status', 'type': 'aggregated'}],
    }


@pytest.mark.parametrize('definition', [None, '', '   ', 'not: [valid', '- a list'])
def test_a_missing_or_unreadable_definition_gives_none(definition):
    assert parse_metric_view_definition(definition) is None


def _nested_joins(depth):
    lines, indent = ["source: main.sales.orders", "joins:"], "  "
    for i in range(depth):
        lines += [f"{indent}- name: j{i}", f"{indent}  source: main.sales.t{i}",
                  f"{indent}  joins:"]
        indent += "    "
    return "\n".join(lines + [f"{indent}[]"]) + "\n"


def test_a_definition_nested_too_deeply_for_the_yaml_parser_gives_none():
    # yaml.safe_load raises RecursionError (not a YAMLError) from about 600 levels
    deep = "source: main.sales.orders\nfilter: " + "[" * 5000 + "]" * 5000 + "\n"

    assert parse_metric_view_definition(deep) is None
    assert parse_metric_view_definition(_nested_joins(1000)) is None


def test_deeply_nested_joins_are_flattened_in_order():
    joins = parse_metric_view_definition(_nested_joins(100))['joins']

    assert [j['name'] for j in joins] == [f"j{i}" for i in range(100)]


def test_joins_repeated_through_yaml_aliases_are_listed_once():
    spec = parse_metric_view_definition(
        "source: main.sales.orders\n"
        "joins: &all\n"
        "  - name: customers\n"
        "    source: main.sales.customers\n"
        "    joins: *all\n"
    )

    assert [j['name'] for j in spec['joins']] == ['customers']


def test_a_definition_over_the_size_limit_gives_none():
    padding = "# " + "x" * MAX_DEFINITION_LENGTH + "\n"

    assert parse_metric_view_definition(SPEC + padding) is None
    assert parse_metric_view_definition(SPEC)['source'] == 'main.sales.orders'


# --- Connector ---------------------------------------------------------------


def _connector():
    ws = MagicMock()
    ws.tables.list.return_value = TABLES
    ws.tables.get.side_effect = lambda full_name: next(t for t in TABLES if t.full_name == full_name)
    for api in (ws.functions, ws.registered_models, ws.volumes):
        api.list.return_value = []
    return DatabricksConnector(workspace_client=ws), ws


def test_a_metric_view_lists_as_uc_metric_and_the_other_types_are_unchanged():
    connector, _ = _connector()

    assets = connector.list_assets(ListAssetsOptions(path='main.sales'))

    assert {a.name: a.asset_type for a in assets} == {
        'orders': UnifiedAssetType.UC_TABLE,
        'v_orders': UnifiedAssetType.UC_VIEW,
        'mv_orders': UnifiedAssetType.UC_MATERIALIZED_VIEW,
        'revenue_metrics': UnifiedAssetType.UC_METRIC,
    }


def test_filtering_on_uc_metric_lists_the_metric_views():
    connector, _ = _connector()

    assets = connector.list_assets(ListAssetsOptions(
        path='main.sales', asset_types=[UnifiedAssetType.UC_METRIC],
    ))

    assert [a.name for a in assets] == ['revenue_metrics']


def test_a_metric_views_metadata_carries_its_definition():
    connector, ws = _connector()

    metadata = connector.get_asset_metadata('main.sales.revenue_metrics')

    assert metadata.asset_type == UnifiedAssetType.UC_METRIC
    spec = metadata.properties['metric_view']
    assert [d['name'] for d in spec['dimensions']] == ['Order Month', 'Region']
    assert [m['name'] for m in spec['measures']] == ['Total Revenue']


def test_a_tables_metadata_has_no_metric_view():
    connector, _ = _connector()

    assert 'metric_view' not in connector.get_asset_metadata('main.sales.orders').properties


# --- Catalog tree ------------------------------------------------------------


def _catalog_manager():
    client = MagicMock()
    client.tables.list.return_value = TABLES
    for api in (client.functions, client.registered_models, client.volumes):
        api.list.return_value = []
    return CatalogCommanderManager(sp_client=client, obo_client=client)


def test_the_catalog_tree_types_objects_from_the_sdk_enum():
    # str(TableType.VIEW) is 'TableType.VIEW': every view used to come out as 'table'
    objects = _catalog_manager().list_objects('main', 'sales')

    assert {o['name']: o['type'] for o in objects} == {
        'orders': 'table',
        'v_orders': 'view',
        'mv_orders': 'materialized_view',
        'revenue_metrics': 'metric',
    }


def test_the_catalog_tree_lists_only_metric_views_when_asked():
    objects = _catalog_manager().list_objects('main', 'sales', asset_types=['metric'])

    assert [o['name'] for o in objects] == ['revenue_metrics']


def test_the_table_listing_tells_tables_views_and_metric_views_apart():
    tables = _catalog_manager().list_tables('main', 'sales')

    assert {t['name']: t['type'] for t in tables} == {
        'orders': 'table',
        'v_orders': 'view',
        'mv_orders': 'table',  # this listing has no materialized view type
        'revenue_metrics': 'metric',
    }


def test_the_view_listing_finds_views():
    # It compared the TableType enum with 'VIEW' and returned nothing
    assert [v['name'] for v in _catalog_manager().list_views('main', 'sales')] == ['v_orders']


# --- Asset reviews -----------------------------------------------------------


def _review_manager():
    ws = MagicMock()
    ws.tables.get.side_effect = lambda full_name: next(t for t in TABLES if t.full_name == full_name)
    return DataAssetReviewManager(db=MagicMock(), ws_client=ws, notifications_manager=MagicMock())


def test_a_metric_view_is_reviewed_as_a_metric():
    manager = _review_manager()

    assert manager._determine_asset_type('main.sales.revenue_metrics') == AssetType.METRIC
    assert manager._determine_asset_type('main.sales.v_orders') == AssetType.VIEW


def test_a_reviewed_metric_view_shows_its_dimensions_and_measures():
    result = asyncio.run(_review_manager().get_metric_view_definition('main.sales.revenue_metrics'))

    assert result['definition'] == SPEC
    assert [d['name'] for d in result['metric_view']['dimensions']] == ['Order Month', 'Region']
    assert [m['name'] for m in result['metric_view']['measures']] == ['Total Revenue']


def test_a_reviewed_metric_view_nested_too_deeply_still_returns_its_yaml():
    deep = "source: main.sales.orders\nfilter: " + "[" * 5000 + "]" * 5000 + "\n"
    manager = _review_manager()
    manager._ws_client.tables.get.side_effect = lambda full_name: _table(
        "deep_metrics", TableType.METRIC_VIEW, deep)

    result = asyncio.run(manager.get_metric_view_definition('main.sales.deep_metrics'))

    assert result == {'definition': deep, 'metric_view': None}


# --- Schema import -----------------------------------------------------------


def test_a_metric_view_imports_as_a_view_with_its_columns():
    from src.controller import schema_import_manager as sim

    assert sim._TYPE_MAP[UnifiedAssetType.UC_METRIC.value] == ("View", "hasView")
    assert sim._display_type(UnifiedAssetType.UC_METRIC) == 'metric'
    assert UnifiedAssetType.UC_METRIC.value in sim._LEAF_ASSET_TYPES
