"""The metric view parser keeps windows, parameters and join cardinality (#1263 phase 0).

The KPI fingerprint compares measures at the level of their window and the
view's parameters, and resolves joins with their cardinality, so the parser
keeps them. It does so additively: a definition without them parses to the
same keys and shapes as before.
"""
from src.common.metric_views import parse_metric_view_definition

WINDOWED = """\
version: 1.1
source: main.sales.orders
parameters:
  - name: min_amount
    data_type: double
    default: 0
  - name: as_of
    data_type: date
    default: 2024-01-31
  - name: region
    data_type: string
  - data_type: int
joins:
  - name: returns
    source: main.sales.returns
    on: source.order_id = returns.order_id
    cardinality: one_to_many
  - name: customers
    source: main.sales.customers
    on: source.customer_id = customers.id
fields:
  - name: Order Date
    expr: order_date
measures:
  - name: Rolling Orders
    expr: COUNT(1)
    window:
      - order: Order Date
        range: trailing 3 month
        semiadditive: first
        offset: -1 month
  - name: Prior Orders
    expr: COUNT(1)
    window:
      order: Order Date
      range: cumulative
  - name: Orders
    expr: COUNT(1)
"""


def test_a_measure_keeps_its_window_entries():
    measures = {m['name']: m for m in parse_metric_view_definition(WINDOWED)['measures']}

    assert measures['Rolling Orders']['window'] == [{
        'order': 'Order Date', 'range': 'trailing 3 month',
        'semiadditive': 'first', 'offset': '-1 month',
    }]
    # A single mapping is read as a window of one entry; unset keys are None
    assert measures['Prior Orders']['window'] == [{
        'order': 'Order Date', 'range': 'cumulative', 'semiadditive': None, 'offset': None,
    }]
    # A measure without a window has no window key: its shape is unchanged
    assert measures['Orders'] == {'name': 'Orders', 'expr': 'COUNT(1)'}


def test_the_top_level_parameters_are_kept_with_their_defaults():
    parameters = parse_metric_view_definition(WINDOWED)['parameters']

    assert parameters == [
        {'name': 'min_amount', 'data_type': 'double', 'default': 0},
        # YAML reads the date as a date: kept as its ISO text, so the spec stays JSON
        {'name': 'as_of', 'data_type': 'date', 'default': '2024-01-31'},
        {'name': 'region', 'data_type': 'string', 'default': None},
    ]


def test_a_join_keeps_its_cardinality_only_when_set():
    joins = parse_metric_view_definition(WINDOWED)['joins']

    assert joins[0]['cardinality'] == 'one_to_many'
    assert joins[1] == {
        'name': 'customers', 'source': 'main.sales.customers',
        'on': 'source.customer_id = customers.id', 'using': None,
    }


def test_a_definition_without_them_keeps_the_previous_keys():
    spec = parse_metric_view_definition(
        "version: 0.1\nsource: main.sales.orders\n"
        "dimensions:\n  - name: Region\n    expr: region\n"
        "measures:\n  - name: Revenue\n    expr: SUM(amount)\n"
    )

    assert set(spec) == {
        'version', 'source', 'filter', 'joins', 'dimensions', 'measures',
        'materialization', 'parameters',
    }
    assert spec['parameters'] == []
    assert spec['measures'] == [{'name': 'Revenue', 'expr': 'SUM(amount)'}]


def test_malformed_windows_and_parameters_are_skipped():
    spec = parse_metric_view_definition(
        "source: main.sales.orders\n"
        "parameters: not a list\n"
        "measures:\n"
        "  - name: Odd\n    expr: COUNT(1)\n    window: [trailing, {range: all}]\n"
    )

    assert spec['parameters'] == []
    assert spec['measures'][0]['window'] == [
        {'order': None, 'range': 'all', 'semiadditive': None, 'offset': None},
    ]
