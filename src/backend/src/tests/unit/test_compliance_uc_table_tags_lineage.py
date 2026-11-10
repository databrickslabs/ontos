"""Governed tags and lineage counts on UC table/view entities in compliance rules (#1315)."""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from databricks.sdk.service.catalog import ColumnInfo, TableInfo, TableType

from src.common.compliance_dsl import Evaluator, parse_rule
from src.common.compliance_entities import (
    EntityIterator, TableEnrichment, UnityCatalogLoader, parse_entity_filter,
)
from src.common import uc_table_enrichment as enr
from src.controller.compliance_manager import ComplianceManager
from src.db_models.compliance import CompliancePolicyDb, ComplianceResultDb
from src.common.uc_table_enrichment import (
    LINEAGE, TAGS, SourceUnavailable, WarehouseSqlRunner, enrich_catalog_tables, fields_read,
    groups_for_fields,
)


def _table(name, schema='sales', catalog='main', columns=None, table_type=TableType.MANAGED):
    return TableInfo(
        name=name, full_name=f'{catalog}.{schema}.{name}', catalog_name=catalog,
        schema_name=schema, table_type=table_type,
        columns=columns if columns is not None else [ColumnInfo(name='id', comment='Id')],
    )


def _ws(tables_by_schema, catalogs=('main',)):
    """Workspace client listing the given tables per (catalog, schema)."""
    ws = MagicMock()
    ws.catalogs.list.return_value = [SimpleNamespace(name=c) for c in catalogs]
    ws.schemas.list.side_effect = lambda catalog_name: [
        SimpleNamespace(name=s) for (c, s) in tables_by_schema if c == catalog_name
    ]
    ws.tables.list.side_effect = lambda catalog_name, schema_name: list(
        tables_by_schema.get((catalog_name, schema_name), [])
    )
    return ws


class FakeRunner:
    """SqlRunner returning canned rows per source; records each statement."""

    def __init__(self, tag_rows=(), lineage_rows=(), fail=None):
        self.tag_rows, self.lineage_rows, self.fail = list(tag_rows), list(lineage_rows), fail
        self.calls = []

    def rows(self, statement, parameters):
        source = LINEAGE if enr.LINEAGE_SOURCE in statement else TAGS
        self.calls.append((source, statement, dict(parameters)))
        if self.fail and source in self.fail:
            raise SourceUnavailable(self.fail[source])
        return self.tag_rows if source == TAGS else self.lineage_rows


def _tag(table, tag, value='', column=None, schema='sales'):
    return {'schema_name': schema, 'table_name': table, 'column_name': column,
            'tag_name': tag, 'tag_value': value}


def _lineage(direction, full_name, count):
    return {'direction': direction, 'table_full_name': full_name, 'table_count': str(count)}


def _rule_eval(rule, entity):
    return bool(Evaluator(entity).evaluate(parse_rule(rule)['assert_clause']))


# --- which fields a rule reads -------------------------------------------------

@pytest.mark.parametrize('rule, groups', [
    ("MATCH (t:table) ASSERT HAS_TAG('data_classification')", {TAGS}),
    ("MATCH (t:table) ASSERT TAG('tier') = 'gold'", {TAGS}),
    ("MATCH (t:table) ASSERT t.upstream_count > 0", {LINEAGE}),
    ("MATCH (t:table) WHERE NOT HAS_TAG('x') ASSERT t.downstream_count >= 0", {TAGS, LINEAGE}),
    ("MATCH (t:table) ASSERT CASE WHEN t.owner = 'a' THEN t.upstream_count > 0 ELSE true END",
     {LINEAGE}),
    ("MATCH (t:table) ASSERT t.column_comment_ratio >= 0.8", set()),
    ("MATCH (t:table) ASSERT t.owner IN ['a', 'b']", set()),
])
def test_rule_needs_only_the_groups_it_reads(rule, groups):
    parsed = parse_rule(rule)

    assert groups_for_fields(fields_read(parsed['where_clause'], parsed['assert_clause'])) == groups


# --- statements -------------------------------------------------------------------

def test_tags_statement_is_scoped_by_catalog_and_schemas_with_parameters():
    statement, params = enr.tags_statement('Main', {'sales', 'Ops'})

    assert enr.TABLE_TAGS_SOURCE in statement and enr.COLUMN_TAGS_SOURCE in statement
    assert statement.count('catalog_name = :catalog AND schema_name IN (:s0, :s1)') == 2
    assert params == {'catalog': 'main', 's0': 'ops', 's1': 'sales'}


def test_lineage_statement_has_a_bounded_window_and_counts_distinct_tables():
    statement, params = enr.lineage_statement('main', ['sales'])

    assert statement.count(f'INTERVAL {enr.LINEAGE_WINDOW_DAYS} DAYS') == 2
    assert 'COUNT(DISTINCT lower(source_table_full_name))' in statement
    assert 'COUNT(DISTINCT lower(target_table_full_name))' in statement
    assert 'source_table_full_name IS NOT NULL' in statement
    assert params == {'catalog': 'main', 's0': 'sales'}


# --- rows to fields ----------------------------------------------------------------

def test_tag_rows_fill_table_and_column_tags():
    entities = [
        {'schema': 'sales', 'name': 'orders', 'full_name': 'main.sales.orders',
         'columns': [{'name': 'Email'}, {'name': 'id'}]},
        {'schema': 'sales', 'name': 'untagged', 'full_name': 'main.sales.untagged',
         'columns': [{'name': 'id'}]},
    ]

    enr.apply_tag_rows(entities, [
        _tag('orders', 'data_classification', 'internal'),
        _tag('ORDERS', 'certified'),  # key-only tag: '' in UC
        _tag('orders', 'pii', 'email', column='email'),
        _tag('other_table', 'x'),
    ])

    orders, untagged = entities
    assert orders['tags'] == {'data_classification': 'internal', 'certified': True}
    assert orders['columns'][0]['tags'] == {'pii': 'email'}
    assert orders['columns'][1]['tags'] == {}
    assert untagged['tags'] == {} and untagged['columns'][0]['tags'] == {}


def test_lineage_rows_give_counts_and_zero_without_events():
    entities = [{'full_name': 'main.sales.Orders'}, {'full_name': 'main.sales.raw'}]

    enr.apply_lineage_rows(entities, [
        _lineage('upstream', 'main.sales.orders', 2),
        _lineage('downstream', 'main.sales.orders', 1),
    ])

    assert [(e['upstream_count'], e['downstream_count']) for e in entities] == [(2, 1), (0, 0)]


# --- loader ---------------------------------------------------------------------------

def test_loader_reads_tags_and_lineage_once_per_catalog_and_rules_see_them():
    ws = _ws({
        ('main', 'sales'): [_table('orders'), _table('raw_orders')],
        ('main', 'ops'): [_table('v_orders', schema='ops', table_type=TableType.VIEW)],
        ('lake', 'bronze'): [_table('events', schema='bronze', catalog='lake')],
    }, catalogs=('main', 'lake'))
    runner = FakeRunner(
        tag_rows=[_tag('orders', 'data_classification', 'internal')],
        lineage_rows=[_lineage('upstream', 'main.sales.orders', 1)],
    )
    loader = UnityCatalogLoader(ws, TableEnrichment(groups={TAGS, LINEAGE}, runner=runner))

    entities = {e['name']: e for e in loader.load_entities(['table', 'view'])}

    # One tags and one lineage statement per catalog, never one per table
    assert [(source, params['catalog']) for source, _, params in runner.calls] == [
        (TAGS, 'main'), (LINEAGE, 'main'), (TAGS, 'lake'), (LINEAGE, 'lake'),
    ]
    assert runner.calls[0][2] == {'catalog': 'main', 's0': 'ops', 's1': 'sales'}
    has_tag = "MATCH (t:table) ASSERT HAS_TAG('data_classification')"
    upstream = "MATCH (t:table) ASSERT t.upstream_count > 0"
    assert [_rule_eval(has_tag, entities[n]) for n in ('orders', 'raw_orders')] == [True, False]
    assert [_rule_eval(upstream, entities[n]) for n in ('orders', 'raw_orders')] == [True, False]
    assert entities['v_orders']['type'] == 'view' and entities['v_orders']['tags'] == {}
    assert entities['orders']['columns'][0]['tags'] == {}


def test_loader_without_enrichment_makes_no_statement_and_adds_no_fields():
    ws = _ws({('main', 'sales'): [_table('orders')]})

    [entity] = UnityCatalogLoader(ws).load_entities(['table'])

    assert 'tags' not in entity and 'upstream_count' not in entity
    ws.statement_execution.execute_statement.assert_not_called()


def test_where_scope_limits_the_statements_to_the_selected_schemas_and_catalogs():
    ws = _ws({
        ('main', 'sales'): [_table('orders')],
        ('main', 'ops'): [_table('jobs', schema='ops')],
        ('lake', 'bronze'): [_table('events', schema='bronze', catalog='lake')],
    }, catalogs=('main', 'lake'))
    runner = FakeRunner()
    rule = "MATCH (t:table) WHERE t.catalog = 'main' AND t.schema = 'sales' ASSERT HAS_TAG('x')"
    parsed = parse_rule(rule)
    loader = UnityCatalogLoader(
        ws, TableEnrichment(groups={TAGS}, runner=runner, scope_ast=parsed['where_clause']),
    )

    entities = {e['name']: e for e in loader.load_entities(['table'])}

    assert [params for _, _, params in runner.calls] == [{'catalog': 'main', 's0': 'sales'}]
    assert entities['orders']['tags'] == {}
    # Out of scope: not enriched (the WHERE drops them anyway)
    assert 'tags' not in entities['jobs'] and 'tags' not in entities['events']


def test_no_runner_marks_the_fields_unavailable_with_the_source():
    ws = _ws({('main', 'sales'): [_table('orders')]})
    loader = UnityCatalogLoader(ws, TableEnrichment(groups={TAGS, LINEAGE}, runner=None))

    [entity] = loader.load_entities(['table'])

    assert 'tags' not in entity and 'upstream_count' not in entity
    assert entity[enr.UNAVAILABLE_KEY] == {
        'tags': {'source': enr.GROUP_SOURCE[TAGS], 'reason': 'no_warehouse'},
        'upstream_count': {'source': enr.LINEAGE_SOURCE, 'reason': 'no_warehouse'},
        'downstream_count': {'source': enr.LINEAGE_SOURCE, 'reason': 'no_warehouse'},
    }


def test_a_failed_source_leaves_only_its_fields_out():
    entities = [{'schema': 'sales', 'name': 'orders', 'full_name': 'main.sales.orders',
                 'columns': []}]
    runner = FakeRunner(tag_rows=[_tag('orders', 'pii')], fail={LINEAGE: 'no_access'})

    enrich_catalog_tables('main', entities, {TAGS, LINEAGE}, runner)

    [entity] = entities
    assert entity['tags'] == {'pii': True}
    assert 'upstream_count' not in entity
    assert set(entity[enr.UNAVAILABLE_KEY]) == {'upstream_count', 'downstream_count'}
    assert entity[enr.UNAVAILABLE_KEY]['upstream_count']['reason'] == 'no_access'


def test_iterator_keeps_an_entity_whose_where_field_is_unavailable():
    ws = _ws({('main', 'sales'): [_table('orders')]})
    rule = "MATCH (t:table) WHERE HAS_TAG('gold') ASSERT t.upstream_count > 0"
    loader = UnityCatalogLoader(ws, TableEnrichment(groups={TAGS, LINEAGE}, runner=None))

    entities = list(EntityIterator([loader]).iterate(parse_entity_filter(rule)))

    # Without the tags, HAS_TAG('gold') would be false and the table silently dropped
    assert [e['name'] for e in entities] == ['orders']


# --- the warehouse runner -------------------------------------------------------------

def _response(state, rows=None, columns=('a', 'b'), next_chunk=None, error=None):
    return SimpleNamespace(
        statement_id='st-1',
        status=SimpleNamespace(state=SimpleNamespace(value=state),
                               error=SimpleNamespace(message=error) if error else None),
        manifest=SimpleNamespace(schema=SimpleNamespace(
            columns=[SimpleNamespace(name=c) for c in columns])),
        result=SimpleNamespace(data_array=rows, next_chunk_index=next_chunk),
    )


def test_runner_passes_parameters_and_reads_every_chunk():
    ws = MagicMock()
    ws.statement_execution.execute_statement.return_value = _response(
        'SUCCEEDED', rows=[['1', 'x']], next_chunk=1,
    )
    ws.statement_execution.get_statement_result_chunk_n.return_value = SimpleNamespace(
        data_array=[['2', 'y']], next_chunk_index=None,
    )

    rows = WarehouseSqlRunner(ws, 'wh-1').rows('SELECT :catalog', {'catalog': 'main'})

    assert rows == [{'a': '1', 'b': 'x'}, {'a': '2', 'b': 'y'}]
    kwargs = ws.statement_execution.execute_statement.call_args.kwargs
    assert kwargs['warehouse_id'] == 'wh-1'
    assert [(p.name, p.value) for p in kwargs['parameters']] == [('catalog', 'main')]
    ws.statement_execution.get_statement_result_chunk_n.assert_called_once_with('st-1', 1)


@pytest.mark.parametrize('response, reason', [
    (_response('FAILED', error='PERMISSION_DENIED: User does not have USE SCHEMA'), 'no_access'),
    (_response('FAILED', error='[TABLE_OR_VIEW_NOT_FOUND]'), 'query_failed'),
    (_response('CANCELED'), 'query_failed'),
])
def test_runner_turns_a_failed_statement_into_source_unavailable(response, reason):
    ws = MagicMock()
    ws.statement_execution.execute_statement.return_value = response

    with pytest.raises(SourceUnavailable) as raised:
        WarehouseSqlRunner(ws, 'wh-1').rows('SELECT 1', {})

    assert raised.value.reason == reason


def test_runner_turns_an_sdk_error_into_source_unavailable():
    ws = MagicMock()
    ws.statement_execution.execute_statement.side_effect = RuntimeError('warehouse stopped')

    with pytest.raises(SourceUnavailable) as raised:
        WarehouseSqlRunner(ws, 'wh-1').rows('SELECT 1', {})

    assert raised.value.reason == 'query_failed'


# --- policy runs ----------------------------------------------------------------------

def _policy(db_session, rule):
    policy = CompliancePolicyDb(id=str(uuid.uuid4()), name='p', is_active=True, rule=rule)
    db_session.add(policy)
    db_session.flush()
    return policy


def _run(db_session, rule, ws, runner=None, warehouse_id='wh-1'):
    policy = _policy(db_session, rule)
    settings = SimpleNamespace(DATABRICKS_WAREHOUSE_ID=warehouse_id)
    with patch('src.common.workspace_client.get_workspace_client', return_value=ws), \
            patch('src.common.config.get_settings', return_value=settings), \
            patch('src.controller.compliance_manager.WarehouseSqlRunner',
                  return_value=runner) as make_runner:
        run = ComplianceManager().run_policy_inline(db_session, policy=policy)
    results = db_session.query(ComplianceResultDb).filter_by(run_id=run.id).all()
    return run, {r.object_name: r for r in results}, make_runner


def test_policy_run_on_tags_and_lineage(db_session):
    ws = _ws({('main', 'sales'): [_table('orders'), _table('raw_orders')]})
    runner = FakeRunner(
        tag_rows=[_tag('orders', 'data_classification', 'internal')],
        lineage_rows=[_lineage('upstream', 'main.sales.orders', 3)],
    )
    rule = "MATCH (t:table) ASSERT HAS_TAG('data_classification') AND t.upstream_count > 0"

    run, results, make_runner = _run(db_session, rule, ws, runner)

    make_runner.assert_called_once_with(ws, 'wh-1')
    assert run.status == 'succeeded' and run.warning_code is None
    assert {n: r.passed for n, r in results.items()} == {'orders': True, 'raw_orders': False}
    assert len(runner.calls) == 2


def test_policy_run_without_tag_or_lineage_fields_runs_no_statement(db_session):
    ws = _ws({('main', 'sales'): [_table('orders')]})

    run, results, make_runner = _run(
        db_session, "MATCH (t:table) ASSERT t.column_comment_ratio >= 0.8", ws, FakeRunner(),
    )

    make_runner.assert_not_called()
    assert results['orders'].passed is True and run.warning_code is None


def test_policy_run_without_warehouse_reports_entities_not_evaluated(db_session):
    ws = _ws({('main', 'sales'): [_table('orders'), _table('raw_orders')]})
    rule = ("MATCH (t:table) ASSERT HAS_TAG('data_classification')\n"
            "ON_FAIL ASSIGN_TAG compliance: 'failed'")

    with patch('src.controller.compliance_manager.ActionExecutor.execute_actions') as act:
        run, results, make_runner = _run(db_session, rule, ws, warehouse_id='')

    make_runner.assert_not_called()
    act.assert_not_called()  # no ON_FAIL for an entity that was not evaluated
    assert run.status == 'succeeded'
    assert (run.success_count, run.failure_count) == (0, 2)
    assert run.warning_code == 'rule_fields_unavailable'
    assert json.loads(run.warning_params) == {
        'count': 2, 'sources': enr.GROUP_SOURCE[TAGS], 'reasons': 'no_warehouse',
    }
    details = json.loads(results['orders'].details_json)
    assert details == {'code': 'rule_field_unavailable', 'params': {
        'fields': 'tags', 'sources': enr.GROUP_SOURCE[TAGS], 'reason': 'no_warehouse',
    }}
    assert results['orders'].passed is False
    assert 'Not evaluated' in results['orders'].message


def test_policy_run_with_lineage_denied_still_evaluates_tag_only_rules(db_session):
    ws = _ws({('main', 'sales'): [_table('orders')]})
    runner = FakeRunner(tag_rows=[_tag('orders', 'pii')], fail={LINEAGE: 'no_access'})

    run, results, _ = _run(
        db_session, "MATCH (t:table) ASSERT HAS_TAG('pii') AND t.downstream_count >= 0",
        ws, runner,
    )

    assert run.warning_code == 'rule_fields_unavailable'
    assert json.loads(run.warning_params)['reasons'] == 'no_access'
    assert json.loads(results['orders'].details_json)['params']['fields'] == (
        'downstream_count'
    )
