"""The read-only KPI consistency views over stored fingerprints (#1263, phase 1).

By concept: the linked measures grouped by full fingerprint. By asset: per
measure, the measures with the same or a similar definition and conflicting
links. A link check: the warnings a new measure link raises. Definitions are
shown only for views the caller can read.
"""
import uuid

import pytest

from src.common.metric_views import parse_metric_view_definition
from src.controller.metric_view_consistency_manager import (
    MetricViewAssetNotFoundError, MetricViewConsistencyManager, store_metric_view,
)
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.semantic_links import EntitySemanticLinkDb
from src.models.assets import METRIC_VIEW_ASSET_TYPE

REVENUE = 'http://example.com/glossary#Revenue'
NET_SALES = 'http://example.com/glossary#NetSales'
ACTIVE = 'http://example.com/glossary#ActiveCustomers'


def _yaml(source, measures):
    return f"version: 1.1\nsource: {source}\nmeasures:\n" + ''.join(
        f"  - name: {name}\n    expr: {expr}\n" + extra for name, expr, extra in measures)


def _window(days):
    return ("    window:\n      - order: order_date\n"
            f"        range: trailing {days} day\n        semiadditive: last\n")


GROSS = _yaml('main.sales.orders', [
    ('Revenue', 'SUM(gross_amount)', ''),
    ('Active customers', 'COUNT(DISTINCT customer_id)', _window(30)),
])
NET = _yaml('main.sales.orders', [
    ('Revenue', 'SUM(amount - refunds)', ''),
    ('Active customers', 'COUNT(DISTINCT customer_id)', _window(90)),
])
COPY = _yaml('dev.sales.orders', [('Revenue', 'SUM(gross_amount)', '')])
TWIN = _yaml('main.sales.orders', [('Gross sales', 'sum(gross_amount)', '')])


@pytest.fixture
def metric_view_type(db_session):
    found = db_session.query(AssetTypeDb).filter_by(name=METRIC_VIEW_ASSET_TYPE).first()
    if found is None:
        found = AssetTypeDb(name=METRIC_VIEW_ASSET_TYPE, category='data')
        db_session.add(found)
        db_session.flush()
    return found


@pytest.fixture
def views(db_session, metric_view_type):
    """Four metric views: gross, net, a copy of gross in a dev catalog, a renamed twin."""
    made = {}
    for key, fqn, definition in (
        ('gross', 'main.sales.revenue_gross', GROSS),
        ('net', 'main.sales.revenue_net', NET),
        ('copy', 'dev.sales.revenue_gross', COPY),
        ('twin', 'main.finance.sales_mv', TWIN),
    ):
        asset = AssetDb(name=fqn.rsplit('.', 1)[-1], asset_type_id=metric_view_type.id,
                        platform='databricks', location=fqn)
        db_session.add(asset)
        db_session.flush()
        store_metric_view(db_session, asset, parse_metric_view_definition(definition))
        made[key] = asset
    return made


def _link(db, entity_id, iri):
    db.add(EntitySemanticLinkDb(entity_type='uc_column', entity_id=entity_id, iri=iri))
    db.flush()


def _everyone(fqn):
    return True


def test_measures_of_a_concept_are_grouped_by_fingerprint(db_session, views):
    _link(db_session, 'main.sales.revenue_gross.Revenue', REVENUE)
    _link(db_session, 'dev.sales.revenue_gross.Revenue', REVENUE)
    _link(db_session, 'MAIN.SALES.REVENUE_NET.Revenue', REVENUE)  # UC names ignore case

    result = MetricViewConsistencyManager(db_session).for_concept(REVENUE, _everyone)

    assert result.verdict == 'conflict'
    assert [[m.entity_id for m in g.measures] for g in result.groups] == [
        ['dev.sales.revenue_gross.Revenue'],
        ['main.sales.revenue_gross.Revenue'],
        ['main.sales.revenue_net.Revenue'],
    ]
    copy, gross, net = result.groups
    assert copy.definition.source == 'dev.sales.orders'
    assert (gross.first_level, net.first_level) == ('scope', 'expression')
    assert gross.differences is not None
    assert {d.component for d in net.differences} == {'columns', 'source'}


def test_one_definition_is_consistent(db_session, views):
    _link(db_session, 'main.sales.revenue_gross.Revenue', REVENUE)
    _link(db_session, 'main.finance.sales_mv.Gross sales', REVENUE)

    result = MetricViewConsistencyManager(db_session).for_concept(REVENUE, _everyone)

    assert result.verdict == 'consistent'
    [group] = result.groups
    assert len(group.measures) == 2
    assert group.definition.expression == 'sum(gross_amount)'


def test_a_group_lists_the_other_concepts_its_definition_is_linked_to(db_session, views):
    _link(db_session, 'main.sales.revenue_gross.Revenue', REVENUE)
    _link(db_session, 'main.finance.sales_mv.Gross sales', NET_SALES)

    [group] = MetricViewConsistencyManager(db_session).for_concept(REVENUE, _everyone).groups

    assert group.other_concepts == [NET_SALES]


def test_a_concept_without_measures_has_no_verdict_and_unknown_fields_are_unresolved(
        db_session, views):
    _link(db_session, 'main.sales.revenue_gross.order_date', ACTIVE)  # not a measure
    _link(db_session, 'main.other.table.column', ACTIVE)  # not a metric view

    result = MetricViewConsistencyManager(db_session).for_concept(ACTIVE, _everyone)

    assert result.verdict == 'none' and result.groups == []
    assert [m.entity_id for m in result.unresolved] == ['main.sales.revenue_gross.order_date']


def test_definitions_of_views_the_user_cant_read_are_not_shown(db_session, views):
    _link(db_session, 'main.sales.revenue_gross.Revenue', REVENUE)
    _link(db_session, 'main.sales.revenue_net.Revenue', REVENUE)
    readable = {'main.sales.revenue_gross'}

    result = MetricViewConsistencyManager(db_session).for_concept(
        REVENUE, lambda fqn: fqn in readable)

    gross, net = result.groups
    assert gross.definition is not None and gross.measures[0].readable is True
    assert net.definition is None and net.differences is None
    # Ontos-level metadata stays: the asset, the name, the concept and the verdict
    assert net.measures[0].readable is False
    assert net.measures[0].asset_name == 'revenue_net'
    assert net.measures[0].concepts == [REVENUE]
    assert result.verdict == 'conflict' and net.first_level == 'expression'


def test_readability_is_asked_once_per_view_and_a_failure_means_unreadable(
        db_session, views):
    _link(db_session, 'main.sales.revenue_gross.Revenue', REVENUE)
    _link(db_session, 'main.finance.sales_mv.Gross sales', REVENUE)
    asked = []

    def readable(fqn):
        asked.append(fqn)
        raise RuntimeError('boom')

    [group] = MetricViewConsistencyManager(db_session).for_concept(REVENUE, readable).groups

    assert group.definition is None
    assert sorted(asked) == ['main.finance.sales_mv', 'main.sales.revenue_gross']


def _matches(result, name):
    measure = next(m for m in result.measures if m.measure.name == name)
    return {(x.measure.entity_id, x.verdict) for x in measure.matches}


def test_per_measure_matches_of_a_metric_view(db_session, views):
    _link(db_session, 'main.sales.revenue_gross.Revenue', REVENUE)
    _link(db_session, 'main.sales.revenue_net.Revenue', REVENUE)

    result = MetricViewConsistencyManager(db_session).for_asset(views['gross'].id, _everyone)

    assert result.asset_id == str(views['gross'].id)
    assert _matches(result, 'Revenue') == {
        ('main.sales.revenue_net.Revenue', 'conflict'),
        ('dev.sales.revenue_gross.Revenue', 'conflict'),  # same name, other source
        ('main.finance.sales_mv.Gross sales', 'unrecognized_duplicate'),
    }
    assert _matches(result, 'Active customers') == {
        ('main.sales.revenue_net.Active customers', 'variant'),
    }
    revenue = next(m for m in result.measures if m.measure.name == 'Revenue')
    assert revenue.measure.concepts == [REVENUE]
    assert revenue.matches[0].verdict == 'conflict'


def test_a_link_conflict_is_listed(db_session, views):
    _link(db_session, 'main.sales.revenue_gross.Revenue', REVENUE)
    _link(db_session, 'main.finance.sales_mv.Gross sales', NET_SALES)

    result = MetricViewConsistencyManager(db_session).for_asset(views['twin'].id, _everyone)

    assert _matches(result, 'Gross sales') == {
        ('main.sales.revenue_gross.Revenue', 'link_conflict')}


def test_match_differences_are_hidden_when_either_view_is_unreadable(db_session, views):
    result = MetricViewConsistencyManager(db_session).for_asset(
        views['gross'].id, lambda fqn: fqn == 'main.sales.revenue_gross')

    active = next(m for m in result.measures if m.measure.name == 'Active customers')
    [variant] = active.matches
    assert variant.verdict == 'variant' and variant.differences is None
    assert variant.measure.readable is False


def test_an_unknown_asset_is_refused(db_session, views):
    with pytest.raises(MetricViewAssetNotFoundError):
        MetricViewConsistencyManager(db_session).for_asset(uuid.uuid4(), _everyone)


def test_an_asset_without_fingerprints_has_no_measures(db_session, metric_view_type):
    asset = AssetDb(name='bare', asset_type_id=metric_view_type.id, platform='databricks',
                    location='main.sales.bare')
    db_session.add(asset)
    db_session.flush()

    assert MetricViewConsistencyManager(db_session).for_asset(asset.id, _everyone).measures == []


def test_linking_a_different_definition_to_a_concept_warns(db_session, views):
    _link(db_session, 'main.sales.revenue_gross.Revenue', REVENUE)

    check = MetricViewConsistencyManager(db_session).check_link(
        'main.sales.revenue_net.Revenue', REVENUE)

    [warning] = check.warnings
    assert warning.code == 'concept_has_other_definitions'
    assert warning.params == {'count': 1, 'measures': ['main.sales.revenue_gross.Revenue']}


def test_linking_a_definition_linked_to_another_concept_warns(db_session, views):
    _link(db_session, 'main.sales.revenue_gross.Revenue', NET_SALES)

    check = MetricViewConsistencyManager(db_session).check_link(
        'main.finance.sales_mv.Gross sales', REVENUE)

    [warning] = check.warnings
    assert warning.code == 'definition_linked_to_other_concepts'
    assert warning.params == {'count': 1, 'concepts': [NET_SALES]}


def test_a_consistent_link_or_an_unknown_field_raises_no_warning(db_session, views):
    _link(db_session, 'main.sales.revenue_gross.Revenue', REVENUE)
    manager = MetricViewConsistencyManager(db_session)

    assert manager.check_link('main.finance.sales_mv.Gross sales', REVENUE).warnings == []
    assert manager.check_link('main.sales.revenue_gross.order_date', REVENUE).warnings == []
