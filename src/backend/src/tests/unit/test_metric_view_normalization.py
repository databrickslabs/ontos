"""Metric view definitions are compared in a normalized form (#1124 drift, #1263).

Unity Catalog rewrites the YAML it stores (``fields`` becomes ``dimensions``,
the top-level ``comment`` becomes the view's comment, ``display_name`` and
``format`` are not kept), so those differences, key order and whitespace in
expressions must not change the digest; a changed expression or join must.
"""
import hashlib

import pytest

from src.common.metric_view_normalization import (
    canonical_json, definition_digest, normalize_definition,
)

BASE = """\
version: 1.1
source: main.sales.orders
filter: status = 'closed'
joins:
  - name: customers
    source: main.sales.customers
    on: source.customer_id = customers.id
dimensions:
  - name: Region
    expr: customers.region
measures:
  - name: Total Revenue
    expr: SUM(amount)
"""


def _digest(definition):
    return definition_digest(normalize_definition(definition))


def test_fields_and_dimensions_compare_equal():
    assert _digest(BASE.replace('dimensions:', 'fields:')) == _digest(BASE)


def test_key_order_does_not_count():
    reordered = """\
measures:
  - expr: SUM(amount)
    name: Total Revenue
dimensions:
  - expr: customers.region
    name: Region
joins:
  - on: source.customer_id = customers.id
    source: main.sales.customers
    name: customers
filter: status = 'closed'
source: main.sales.orders
version: 1.1
"""
    assert _digest(reordered) == _digest(BASE)


def test_whitespace_in_expressions_does_not_count():
    spaced = (
        BASE.replace("filter: status = 'closed'", "filter: \"status   =\\n 'closed'  \"")
        .replace('expr: SUM(amount)', 'expr: "  SUM(amount)\\t"')
        .replace('on: source.customer_id = customers.id',
                 'on: >\n      source.customer_id\n      = customers.id')
    )
    assert normalize_definition(spaced)['filter'] == "status = 'closed'"
    assert _digest(spaced) == _digest(BASE)


@pytest.mark.parametrize('extra', [
    '    display_name: Revenue\n',
    '    format:\n      type: currency\n      currency_code: USD\n',
])
def test_display_name_and_format_are_excluded(extra):
    with_extra = BASE.replace('    expr: SUM(amount)\n', '    expr: SUM(amount)\n' + extra)
    assert _digest(with_extra) == _digest(BASE)


def test_the_top_level_comment_is_excluded():
    assert _digest('comment: Order metrics\n' + BASE) == _digest(BASE)


def test_a_field_comment_counts():
    commented = BASE.replace('    expr: SUM(amount)\n',
                             '    expr: SUM(amount)\n    comment: Paid orders only\n')
    assert _digest(commented) != _digest(BASE)


def test_a_changed_expr_is_a_change():
    assert _digest(BASE.replace('SUM(amount)', 'SUM(net_amount)')) != _digest(BASE)


def test_a_changed_join_condition_is_a_change():
    changed = BASE.replace('customers.id', 'customers.customer_id')
    assert _digest(changed) != _digest(BASE)


def test_a_changed_window_parameter_or_cardinality_is_a_change():
    windowed = BASE.replace(
        '    expr: SUM(amount)\n',
        '    expr: SUM(amount)\n    window:\n'
        '      - order: Region\n        range: trailing 30 day\n',
    )
    assert _digest(windowed) != _digest(BASE)
    assert _digest(windowed.replace('trailing 30 day', 'trailing 90 day')) != _digest(windowed)
    assert _digest(BASE.replace(
        '    on: source.customer_id = customers.id\n',
        '    on: source.customer_id = customers.id\n    cardinality: one_to_many\n',
    )) != _digest(BASE)
    assert _digest(BASE + 'parameters:\n  - name: p\n    data_type: int\n') != _digest(BASE)


def test_reordering_measures_is_a_change():
    two = BASE + '  - name: Orders\n    expr: COUNT(1)\n'
    swapped = BASE.replace(
        '  - name: Total Revenue\n    expr: SUM(amount)\n',
        '  - name: Orders\n    expr: COUNT(1)\n  - name: Total Revenue\n    expr: SUM(amount)\n',
    )
    assert _digest(swapped) != _digest(two)


def test_the_digest_is_the_sha256_of_the_canonical_json():
    normalized = normalize_definition(BASE)
    text = canonical_json(normalized)

    assert definition_digest(normalized) == hashlib.sha256(text.encode('utf-8')).hexdigest()
    # Compact, sorted, no None values
    assert text.startswith('{"dimensions":[{"expr":"customers.region","name":"Region"}]')
    assert 'null' not in text and ': ' not in text


def test_an_unparseable_definition_normalizes_to_none():
    assert normalize_definition('not: [valid') is None
    assert normalize_definition(None) is None
