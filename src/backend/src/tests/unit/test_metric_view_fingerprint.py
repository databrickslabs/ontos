"""Fingerprints, data footprint, similarity and classification of metric view measures (#1263).

The PRD's *Testing Decisions* for phase 1: case, whitespace and the
``source.`` prefix don't count; references are inlined and a cycle refused;
an equal expression on another source differs at scope level; a 30 vs 90-day
window differs at full level while ``trailing 30 day`` equals ``trailing 30
day exclusive``; the footprint resolves columns through the expression, a
source query, the filter and joins; similarity scores one extra filter
predicate high and a different base column low; and each verdict.
"""
import pytest

from src.common.metric_view_fingerprint import (
    DEFAULT_SIMILARITY_THRESHOLD, classify, fingerprint_metric_view, footprints_overlap,
    parse_window_range, similarity,
)
from src.common.metric_view_normalization import definition_digest, normalize_definition
from src.common.metric_views import parse_metric_view_definition


def _spec(measures, source='main.sales.orders', filter=None, joins='', dimensions='',
          parameters=''):
    text = f"version: 1.1\nsource: {source}\n"
    if filter:
        text += f"filter: {filter}\n"
    text += joins + dimensions + parameters + "measures:\n" + measures
    spec = parse_metric_view_definition(text)
    assert spec is not None, text
    return spec


def _measure(spec, name):
    return next(m for m in fingerprint_metric_view(spec) if m['name'] == name)


def _one(expr, **kwargs):
    return _measure(_spec(f"  - name: M\n    expr: {expr}\n", **kwargs), 'M')


def _digest(record, level):
    return record['digests'][level]


# --- Fingerprint ------------------------------------------------------------------


@pytest.mark.parametrize("variant", [
    "sum(amount)", "SUM( amount )", "Sum(  amount)", "SUM(source.amount)",
    "SUM(`amount`)", "SUM(SOURCE.AMOUNT)",
])
def test_case_whitespace_and_the_source_prefix_dont_count(variant):
    reference = _one("SUM(amount)")
    other = _one(variant)
    for level in ('expression', 'scope', 'full'):
        assert _digest(other, level) == _digest(reference, level)


def test_string_literals_keep_their_case():
    assert _digest(_one("SUM(amount) FILTER (WHERE status = 'Closed')"), 'expression') != \
        _digest(_one("SUM(amount) FILTER (WHERE status = 'closed')"), 'expression')


def test_references_to_measures_and_dimensions_are_inlined():
    spec = _spec(
        "  - name: Revenue\n    expr: SUM(amount)\n"
        "  - name: Orders\n    expr: COUNT(1)\n"
        "  - name: Average order\n    expr: MEASURE(Revenue) / MEASURE(Orders)\n"
        "  - name: Big orders\n    expr: COUNT(1) FILTER (WHERE `Order Size` > 100)\n",
        dimensions="dimensions:\n  - name: Order Size\n    expr: quantity * price\n",
    )
    inlined = _measure(spec, 'Average order')
    assert inlined['components']['expression'] == '(sum(amount))/(count(1))'
    written_out = _one("SUM(amount) / COUNT(1)")
    assert inlined['components']['expression'] != written_out['components']['expression']
    assert _measure(spec, 'Big orders')['components']['expression'] == \
        'count(1)filter(where(quantity*price)>100)'
    assert 'main.sales.orders.quantity' in _measure(spec, 'Big orders')['footprint']['columns']


def test_a_reference_cycle_is_refused():
    spec = _spec(
        "  - name: A\n    expr: MEASURE(B) + 1\n"
        "  - name: B\n    expr: MEASURE(A) * 2\n"
        "  - name: C\n    expr: SUM(amount)\n",
    )
    a, b, c = fingerprint_metric_view(spec)
    assert a['error'] == b['error'] == 'reference_cycle'
    assert a['digests'] is None and a['components'] is None
    assert c['error'] is None and c['digests'] is not None


def test_a_field_named_like_a_column_reads_the_column_in_its_own_expression():
    spec = _spec("  - name: amount\n    expr: SUM(amount)\n")
    assert _measure(spec, 'amount')['components']['expression'] == 'sum(amount)'


def test_a_measure_without_an_expression_has_no_fingerprint():
    spec = _spec("  - name: M\n")
    assert fingerprint_metric_view(spec)[0]['error'] == 'no_expression'


def test_an_equal_expression_on_another_source_differs_at_scope_level():
    orders = _one("SUM(amount)")
    refunds = _one("SUM(amount)", source='main.finance.refunds')
    assert _digest(orders, 'expression') == _digest(refunds, 'expression')
    assert _digest(orders, 'scope') != _digest(refunds, 'scope')


def test_the_filter_is_a_set_of_predicates():
    a = _one("SUM(amount)", filter="status = 'closed' AND region IS NOT NULL")
    b = _one("SUM(amount)", filter="(region is not null) and status='closed'")
    assert a['components']['filter'] == ["region is not null", "status='closed'"]
    assert _digest(a, 'scope') == _digest(b, 'scope')


def test_between_is_not_split():
    a = _one("SUM(amount)", filter="amount BETWEEN 1 AND 10 AND region = 'EU'")
    assert a['components']['filter'] == ["amount between 1 and 10", "region='EU'"]


_JOINS = (
    "joins:\n  - name: customers\n    source: main.crm.customers\n"
    "    on: source.customer_id = customers.id\n    cardinality: many_to_one\n"
)


def test_join_aliases_resolve_to_the_join_source_and_only_used_joins_count():
    used = _one("COUNT(DISTINCT customers.id)", joins=_JOINS)
    assert used['components']['expression'] == 'count(distinct main.crm.customers.id)'
    assert used['components']['joins'] == [{
        'source': 'main.crm.customers', 'on': 'customer_id=main.crm.customers.id',
        'using': None, 'cardinality': 'many_to_one',
    }]
    unused = _one("SUM(amount)", joins=_JOINS)
    assert unused['components']['joins'] == []
    assert _digest(unused, 'scope') == _digest(_one("SUM(amount)"), 'scope')
    renamed = _one("COUNT(DISTINCT c.id)", joins=_JOINS.replace('customers', 'c')
                   .replace('main.crm.c', 'main.crm.customers'))
    assert _digest(renamed, 'full') == _digest(used, 'full')


def test_the_join_cardinality_is_part_of_the_scope():
    many = _one("COUNT(DISTINCT customers.id)", joins=_JOINS)
    one = _one("COUNT(DISTINCT customers.id)",
               joins=_JOINS.replace('many_to_one', 'one_to_many'))
    assert _digest(many, 'expression') == _digest(one, 'expression')
    assert _digest(many, 'scope') != _digest(one, 'scope')


def _windowed(range_):
    return _measure(_spec(
        "  - name: Active customers\n    expr: COUNT(DISTINCT customer_id)\n"
        f"    window:\n      - order: Order Date\n        range: {range_}\n"
        "        semiadditive: last\n",
        dimensions="dimensions:\n  - name: Order Date\n    expr: order_date\n",
    ), 'Active customers')


def test_a_30_and_a_90_day_window_differ_at_full_level():
    d30, d90 = _windowed('trailing 30 day'), _windowed('trailing 90 day')
    assert _digest(d30, 'scope') == _digest(d90, 'scope')
    assert _digest(d30, 'full') != _digest(d90, 'full')


@pytest.mark.parametrize("same", [
    "trailing 30 day exclusive", "trailing 30 days", "TRAILING  30 DAY",
])
def test_trailing_30_day_equals_trailing_30_day_exclusive(same):
    assert _digest(_windowed(same), 'full') == _digest(_windowed('trailing 30 day'), 'full')


def test_an_inclusive_window_differs():
    assert _digest(_windowed('trailing 30 day inclusive'), 'full') != \
        _digest(_windowed('trailing 30 day'), 'full')


@pytest.mark.parametrize("text, parsed", [
    ("trailing 30 day", ('trailing', 30, 'day', False)),
    ("leading 3 months inclusive", ('leading', 3, 'month', True)),
    ("current", ('current', None, None, False)),
    ("cumulative", ('cumulative', None, None, False)),
    ("all", ('all', None, None, False)),
    ("between two dates", ('raw', 'between two dates', None, False)),
])
def test_window_ranges_are_parsed(text, parsed):
    r = parse_window_range(text)
    assert (r['kind'], r['value'], r['unit'], r['inclusive']) == parsed


_PARAMS = "parameters:\n  - name: min_amount\n    data_type: INT\n    default: 10\n"


def test_used_parameter_defaults_are_part_of_the_full_level():
    ten = _one("SUM(amount) FILTER (WHERE amount > :min_amount)", parameters=_PARAMS)
    twenty = _one("SUM(amount) FILTER (WHERE amount > :min_amount)",
                  parameters=_PARAMS.replace('10', '20'))
    assert ten['components']['parameters'] == [
        {'name': 'min_amount', 'data_type': 'int', 'default': 10}]
    assert _digest(ten, 'scope') == _digest(twenty, 'scope')
    assert _digest(ten, 'full') != _digest(twenty, 'full')
    unused = _one("SUM(amount)", parameters=_PARAMS)
    assert unused['components']['parameters'] == []


def test_display_name_format_and_comment_are_not_part_of_the_fingerprint():
    plain = _one("SUM(amount)")
    dressed = _measure(_spec(
        "  - name: M\n    expr: SUM(amount)\n    display_name: Revenue\n"
        "    format:\n      type: currency\n    comment: Gross revenue\n"), 'M')
    assert dressed['digests'] == plain['digests']
    assert dressed['display_name'] == 'Revenue'


def test_the_drift_digest_is_unchanged():
    # Fingerprints add functions; the digest stored for #1270's baselines stays as it was
    text = ("version: 1.1\nsource: main.sales.orders\n"
            "measures:\n  - name: M\n    expr: SUM(amount)\n")
    assert definition_digest(normalize_definition(text)) == (
        'c3ba30c0e44b35033921679d8d82709ce8b69fd43459dca3abe7e0c2d9855f19')


# --- Data footprint ------------------------------------------------------------------


def test_columns_resolve_through_expression_filter_and_joins():
    m = _one("COUNT(DISTINCT customers.id) FILTER (WHERE amount > 0)",
             filter="status = 'closed'", joins=_JOINS)
    assert m['footprint']['columns'] == [
        'main.crm.customers.id', 'main.sales.orders.amount',
        'main.sales.orders.customer_id', 'main.sales.orders.status',
    ]
    assert m['footprint']['base_columns'] == [
        'main.crm.customers.id', 'main.sales.orders.amount']
    assert m['footprint']['tables'] == ['main.crm.customers', 'main.sales.orders']
    assert m['footprint']['source_tables'] == ['main.sales.orders']


def test_columns_resolve_through_a_source_query():
    m = _one("SUM(amount)",
             source='"SELECT o.amount, o.id FROM main.sales.orders o WHERE o.ok"')
    assert m['footprint']['source_tables'] == ['main.sales.orders']
    assert m['footprint']['columns'] == ['main.sales.orders.amount']
    assert m['components']['source'].startswith('select ')


@pytest.mark.parametrize("expr, aggregations", [
    ("SUM(amount)", ['sum']),
    ("COUNT(DISTINCT customer_id)", ['count_distinct']),
    ("COUNT(customer_id)", ['count']),
    ("SUM(amount) / COUNT(*)", ['count', 'sum']),
    ("CAST(SUM(amount) AS DOUBLE)", ['sum']),
])
def test_aggregations_are_captured(expr, aggregations):
    m = _one(expr)
    assert m['footprint']['aggregations'] == aggregations
    assert 'main.sales.orders.double' not in m['footprint']['columns']


def test_unrelated_tables_are_never_paired():
    orders = _one("SUM(amount)")
    refunds = _one("SUM(amount)", source='main.finance.refunds')
    assert not footprints_overlap(orders, refunds)
    assert classify(orders, refunds, same_concept=False, same_name=False,
                    a_linked=False, b_linked=False) is None


def test_count_star_overlaps_on_the_table():
    assert footprints_overlap(_one("COUNT(*)"), _one("SUM(amount)"))
    assert not footprints_overlap(_one("COUNT(*)"), _one("COUNT(*)", source='main.x.y'))


# --- Similarity ----------------------------------------------------------------------


def test_one_extra_filter_predicate_scores_high():
    a = _one("SUM(amount)", filter="status = 'closed'")
    b = _one("SUM(amount)", filter="status = 'closed' AND region = 'EU'")
    sim = similarity(a, b)
    assert sim['score'] >= 0.9
    assert sim['differences'] == [
        {'component': 'filter', 'only_a': [], 'only_b': ["region='EU'"]}]


def test_a_different_base_column_scores_low():
    sim = similarity(_one("SUM(gross_amount)"), _one("SUM(net_amount)"))
    assert sim['score'] < DEFAULT_SIMILARITY_THRESHOLD
    assert sim['differences'] == [{
        'component': 'columns', 'only_a': ['main.sales.orders.gross_amount'],
        'only_b': ['main.sales.orders.net_amount'],
    }]


def test_count_distinct_vs_count_is_near():
    sim = similarity(_one("COUNT(DISTINCT customer_id)"), _one("COUNT(customer_id)"))
    assert DEFAULT_SIMILARITY_THRESHOLD <= sim['score'] < 1
    assert [d['component'] for d in sim['differences']] == ['aggregation']


def test_identical_measures_score_one():
    assert similarity(_one("SUM(amount)"), _one("sum(amount)")) == {
        'score': 1.0, 'differences': []}


# --- Classification ------------------------------------------------------------------


def _verdict(a, b, **kwargs):
    claimed = dict(same_concept=False, same_name=False, a_linked=False, b_linked=False)
    claimed.update(kwargs)
    result = classify(a, b, **claimed)
    return result and result['verdict']


def test_same_concept_and_same_definition_is_a_duplicate():
    assert _verdict(_one("SUM(amount)"), _one("sum(amount)"), same_concept=True,
                    a_linked=True, b_linked=True) == 'duplicate'
    assert _verdict(_one("SUM(amount)"), _one("sum(amount)"), same_name=True) == 'duplicate'


def test_same_concept_and_a_different_definition_is_a_conflict_with_the_first_level():
    result = classify(_one("SUM(gross_amount)"), _one("SUM(amount - refunds)"),
                      same_concept=True, same_name=False, a_linked=True, b_linked=True)
    assert result['verdict'] == 'conflict'
    assert result['first_level'] == 'expression'
    other_source = classify(_one("SUM(amount)"), _one("SUM(amount)", source='main.x.y'),
                            same_concept=False, same_name=True, a_linked=False,
                            b_linked=False)
    assert (other_source['verdict'], other_source['first_level']) == ('conflict', 'scope')


def test_different_concepts_and_the_same_definition_is_a_link_conflict():
    assert _verdict(_one("SUM(amount)"), _one("SUM(amount)"),
                    a_linked=True, b_linked=True) == 'link_conflict'


def test_unlinked_and_differently_named_with_the_same_definition_is_unrecognized():
    assert _verdict(_one("SUM(amount)"), _one("SUM(amount)")) == 'unrecognized_duplicate'
    assert _verdict(_one("SUM(amount)"), _one("SUM(amount)"),
                    a_linked=True) == 'unrecognized_duplicate'


def test_a_different_window_or_filter_only_is_a_variant():
    assert _verdict(_windowed('trailing 30 day'), _windowed('trailing 90 day'),
                    same_name=True) == 'variant'
    assert _verdict(_one("SUM(amount)"), _one("SUM(amount)", filter="status = 'closed'")) \
        == 'variant'


def test_overlapping_and_similar_is_a_near_duplicate():
    result = classify(_one("COUNT(DISTINCT customer_id)"), _one("COUNT(customer_id)"),
                      same_concept=False, same_name=False, a_linked=False, b_linked=False)
    assert result['verdict'] == 'near_duplicate'
    assert [d['component'] for d in result['differences']] == ['aggregation']


def test_overlapping_but_dissimilar_is_not_reported():
    assert _verdict(_one("SUM(gross_amount) FILTER (WHERE status = 'x')"),
                    _one("AVG(net_amount) FILTER (WHERE status = 'x')")) is None


def test_a_simple_expression_on_different_sources_is_not_a_duplicate():
    for expr in ("COUNT(*)", "SUM(amount)"):
        assert _verdict(_one(expr), _one(expr, source='main.finance.refunds')) is None
