"""Column fields on Unity Catalog table/view entities for compliance rules (#1315)."""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from databricks.sdk.errors import PermissionDenied
from databricks.sdk.service.catalog import (
    ColumnInfo, ColumnTypeName, ForeignKeyConstraint, PrimaryKeyConstraint, TableConstraint,
    TableInfo, TableType,
)

from src.common.compliance_dsl import Evaluator, parse_rule
from src.common.compliance_entities import UnityCatalogLoader
from src.common.uc_table_columns import KEY_FIELDS, table_column_fields
from src.common.uc_table_enrichment import (
    TableConstraintsReader, enrich_tables, unavailable_fields_read,
)
from src.controller.compliance_manager import ComplianceManager
from src.db_models.compliance import CompliancePolicyDb, ComplianceResultDb


def _col(name, comment=None, partition_index=None, type_text='string'):
    return ColumnInfo(
        name=name, comment=comment, partition_index=partition_index, type_text=type_text,
    )


def _table(name, columns, table_type=TableType.MANAGED):
    return TableInfo(
        name=name, full_name=f'main.sales.{name}', catalog_name='main', schema_name='sales',
        table_type=table_type, columns=columns,
    )


def _ws(tables):
    ws = MagicMock()
    ws.catalogs.list.return_value = [SimpleNamespace(name='main')]
    ws.schemas.list.return_value = [SimpleNamespace(name='sales')]
    ws.tables.list.return_value = tables
    return ws


def _assert(rule, entity):
    return bool(Evaluator(entity).evaluate(parse_rule(rule)['assert_clause']))


# --- helper ------------------------------------------------------------------

@pytest.mark.parametrize('columns', [None, []])
def test_no_columns_gives_zero_counts_and_no_ratio(columns):
    fields = table_column_fields(_table('empty', columns))

    assert fields == {
        'columns': [],
        'column_count': 0,
        'columns_without_comment_count': 0,
        'column_comment_ratio': None,
        'partition_column_count': 0,
        'partition_columns_without_comment_count': 0,
        'primary_key_columns': [],
        'foreign_key_columns': [],
        'primary_key_columns_without_comment_count': 0,
        'foreign_key_columns_without_comment_count': 0,
    }


def test_partial_comments_and_whitespace_comment_counts_as_missing():
    fields = table_column_fields(_table('orders', [
        _col('id', 'Order id'),
        _col('amount', '   '),
        _col('note'),
        _col('status', 'Order status'),
    ]))

    assert fields['column_count'] == 4
    assert fields['columns_without_comment_count'] == 2
    assert fields['column_comment_ratio'] == 0.5


def test_columns_list_shape_without_tags_key():
    fields = table_column_fields(_table('orders', [
        _col('id', 'Order id', type_text='bigint'),
        ColumnInfo(name='raw', type_name=ColumnTypeName.BINARY),
    ]))

    assert fields['columns'] == [
        {'name': 'id', 'type': 'bigint', 'comment': 'Order id', 'is_partition_key': False},
        {'name': 'raw', 'type': 'BINARY', 'comment': None, 'is_partition_key': False},
    ]


def test_partition_columns():
    fields = table_column_fields(_table('events', [
        _col('event_date', 'Event day', partition_index=0),
        _col('region', ' ', partition_index=1),
        _col('payload'),
    ]))

    assert [c['is_partition_key'] for c in fields['columns']] == [True, True, False]
    assert fields['partition_column_count'] == 2
    assert fields['partition_columns_without_comment_count'] == 1
    assert fields['columns_without_comment_count'] == 2


def _constraints(primary=(), foreign=()):
    found = []
    if primary:
        found.append(TableConstraint(
            primary_key_constraint=PrimaryKeyConstraint(name='pk', child_columns=list(primary))))
    for i, cols in enumerate(foreign):
        found.append(TableConstraint(foreign_key_constraint=ForeignKeyConstraint(
            name=f'fk{i}', child_columns=list(cols), parent_table='main.sales.parent',
            parent_columns=list(cols))))
    return found


def test_key_columns_and_their_missing_comments():
    table = _table('orders', [
        _col('id', 'Order id'), _col('customer_id'), _col('region_id', ' '), _col('note'),
    ])
    table.table_constraints = _constraints(
        primary=['id'], foreign=[['customer_id'], ['customer_id', 'region_id']])

    fields = table_column_fields(table)

    assert fields['primary_key_columns'] == ['id']
    assert fields['foreign_key_columns'] == ['customer_id', 'region_id']
    assert fields['primary_key_columns_without_comment_count'] == 0
    assert fields['foreign_key_columns_without_comment_count'] == 2


def test_no_constraints_gives_empty_key_fields():
    fields = table_column_fields(_table('orders', [_col('id')]))

    assert fields['primary_key_columns'] == []
    assert fields['foreign_key_columns'] == []
    assert fields['primary_key_columns_without_comment_count'] == 0
    assert fields['foreign_key_columns_without_comment_count'] == 0


def test_rule_on_key_columns():
    table = _table('orders', [_col('id'), _col('amount', 'x')])
    table.table_constraints = _constraints(primary=['id'])
    rule = "MATCH (t:table) ASSERT t.primary_key_columns_without_comment_count = 0"

    entity = {'type': 'table', **table_column_fields(table)}

    assert _assert(rule, entity) is False


def test_accepts_any_table_like_object():
    table = SimpleNamespace(columns=[SimpleNamespace(name='a', comment='x', partition_index=0)])

    fields = table_column_fields(table)

    assert fields['columns'] == [
        {'name': 'a', 'type': None, 'comment': 'x', 'is_partition_key': True},
    ]
    assert fields['column_comment_ratio'] == 1.0


# --- loader ------------------------------------------------------------------

def test_loader_adds_column_fields_to_tables_and_views():
    ws = _ws([
        _table('orders', [_col('id', 'Order id'), _col('note')]),
        _table('v_orders', [_col('id', 'Order id')], table_type=TableType.VIEW),
        _table('mv_orders', [_col('id')], table_type=TableType.MATERIALIZED_VIEW),
    ])

    entities = list(UnityCatalogLoader(ws).load_entities(['table', 'view']))

    by_name = {e['name']: e for e in entities}
    assert by_name['orders']['type'] == 'table'
    assert by_name['orders']['column_count'] == 2
    assert by_name['orders']['column_comment_ratio'] == 0.5
    assert by_name['v_orders']['type'] == 'view'
    assert by_name['v_orders']['columns_without_comment_count'] == 0
    assert by_name['mv_orders']['type'] == 'view'
    assert by_name['mv_orders']['columns_without_comment_count'] == 1
    # tables.list has no constraints: key fields come from tables.get, never as []
    assert not set(KEY_FIELDS) & set(by_name['orders'])
    assert all('tags' not in c for e in entities for c in e['columns'])


# --- rules through the DSL evaluator ------------------------------------------

def test_rules_on_column_fields():
    [documented, partial, empty] = UnityCatalogLoader(_ws([
        _table('documented', [_col('id', 'Id'), _col('day', 'Day', partition_index=0)]),
        _table('partial', [_col('id', 'Id'), _col('day', '', partition_index=0)]),
        _table('empty', None),
    ])).load_entities(['table'])

    no_gaps = "MATCH (t:table) ASSERT t.columns_without_comment_count = 0"
    ratio = "MATCH (t:table) ASSERT t.column_comment_ratio >= 0.8"
    partitions = "MATCH (t:table) ASSERT t.partition_columns_without_comment_count = 0"
    guarded = "MATCH (t:table) ASSERT t.column_count = 0 OR t.column_comment_ratio >= 0.8"

    assert [_assert(no_gaps, e) for e in (documented, partial)] == [True, False]
    assert [_assert(ratio, e) for e in (documented, partial, empty)] == [True, False, False]
    assert [_assert(partitions, e) for e in (documented, partial)] == [True, False]
    assert _assert(guarded, empty) is True


def test_guide_example_rule_parses_and_evaluates():
    rule = (
        "MATCH (t:table)\n"
        "WHERE t.catalog = 'production'\n"
        "ASSERT\n"
        "  t.column_comment_ratio >= 0.8 AND\n"
        "  t.partition_columns_without_comment_count = 0\n"
        "ON_FAIL FAIL 'Comment at least 80% of the columns and every partition column'"
    )
    parsed = parse_rule(rule)
    [good, bad] = UnityCatalogLoader(_ws([
        # 5 of 6 columns commented (0.83), the partition column included
        _table('good', [_col('day', 'Day', partition_index=0)]
               + [_col(f'c{i}', 'x') for i in range(4)] + [_col('c4')]),
        _table('bad', [_col('day', partition_index=0), _col('id', 'Id')]),
    ])).load_entities(['table'])

    assert parsed['on_fail_actions']
    assert [Evaluator(e).evaluate(parsed['assert_clause']) for e in (good, bad)] == [True, False]


def test_policy_run_scores_tables_by_column_comments(db_session):
    policy = CompliancePolicyDb(
        id=str(uuid.uuid4()), name='Columns documented', is_active=True,
        rule="MATCH (t:table)\nASSERT t.column_comment_ratio >= 0.8",
    )
    db_session.add(policy)
    db_session.flush()
    ws = _ws([
        _table('documented', [_col('id', 'Id'), _col('amount', 'Amount')]),
        _table('undocumented', [_col('id'), _col('amount', '  ')]),
    ])

    with patch('src.common.workspace_client.get_workspace_client', return_value=ws):
        run = ComplianceManager().run_policy_inline(db_session, policy=policy)

    results = db_session.query(ComplianceResultDb).filter_by(run_id=run.id).all()
    assert {r.object_name: r.passed for r in results} == {
        'documented': True, 'undocumented': False,
    }


# --- key columns: tables.list has no table_constraints, tables.get does ---------

PK_RULE = "MATCH (t:table) ASSERT t.primary_key_columns_without_comment_count = 0"


def _listed(table):
    """The table as ``tables.list`` returns it: columns, no constraints."""
    return TableInfo(
        name=table.name, full_name=table.full_name, catalog_name='main', schema_name='sales',
        table_type=table.table_type, columns=table.columns,
    )


def _entities(*tables):
    return list(UnityCatalogLoader(_ws([_listed(t) for t in tables])).load_entities(['table']))


def _ws_with_get(by_name):
    ws = MagicMock()
    ws.tables.get.side_effect = lambda full_name: by_name[full_name.split('.')[-1]]
    return ws


def test_a_listed_table_has_no_key_fields_instead_of_empty_ones():
    [entity] = _entities(_table('orders', [_col('id')]))

    assert not set(KEY_FIELDS) & set(entity)


def test_key_fields_come_from_tables_get():
    undocumented = _table('undocumented', [_col('id')])
    undocumented.table_constraints = _constraints(primary=['id'])
    documented = _table('documented', [_col('id', 'Id')])
    documented.table_constraints = _constraints(primary=['id'])
    keyless = _table('keyless', [_col('id')])
    entities = _entities(undocumented, documented, keyless)
    reader = TableConstraintsReader(_ws_with_get({
        'undocumented': undocumented, 'documented': documented, 'keyless': keyless,
    }))

    enrich_tables(entities, {'keys'}, None, reader)

    by_name = {e['name']: e for e in entities}
    assert [_assert(PK_RULE, by_name[n]) for n in ('undocumented', 'documented', 'keyless')] == [
        False, True, True,
    ]
    assert by_name['undocumented']['primary_key_columns'] == ['id']
    assert by_name['keyless']['primary_key_columns'] == []
    assert not unavailable_fields_read(by_name['undocumented'], KEY_FIELDS)


def test_unreadable_constraints_leave_the_key_fields_unavailable_not_empty():
    entities = _entities(_table('orders', [_col('id')]), _table('items', [_col('id')]))
    ws = MagicMock()
    ws.tables.get.side_effect = PermissionDenied('no')

    enrich_tables(entities, {'keys'}, None, TableConstraintsReader(ws))

    for entity in entities:
        assert not set(KEY_FIELDS) & set(entity)
        missing = unavailable_fields_read(entity, ['primary_key_columns_without_comment_count'])
        assert missing['primary_key_columns_without_comment_count'] == {
            'source': 'unity_catalog.tables.get', 'reason': 'table_no_access',
        }


def test_no_reader_marks_the_key_fields_unavailable():
    [entity] = _entities(_table('orders', [_col('id')]))

    enrich_tables([entity], {'keys'}, None, None)

    assert set(unavailable_fields_read(entity, KEY_FIELDS)) == set(KEY_FIELDS)


def test_table_reads_are_capped_per_reader():
    a, b = _table('a', [_col('id')]), _table('b', [_col('id')])
    entities = _entities(a, b)
    ws = _ws_with_get({'a': a, 'b': b})

    enrich_tables(entities, {'keys'}, None, TableConstraintsReader(ws, max_reads=1))

    assert ws.tables.get.call_count == 1
    assert 'primary_key_columns' in entities[0]
    assert unavailable_fields_read(entities[1], ['primary_key_columns'])[
        'primary_key_columns']['reason'] == 'table_read_limit'


def test_table_reads_stop_at_the_time_limit():
    a, b = _table('a', [_col('id')]), _table('b', [_col('id')])
    entities = _entities(a, b)
    times = [0.0]
    ws = _ws_with_get({'a': a, 'b': b})
    reader = TableConstraintsReader(ws, max_seconds=1, clock=lambda: times[0])

    enrich_tables([entities[0]], {'keys'}, None, reader)  # the first read starts the budget
    times[0] = 5.0  # past the budget that first read started
    enrich_tables([entities[1]], {'keys'}, None, reader)

    assert 'primary_key_columns' in entities[0]
    assert ws.tables.get.call_count == 1
    assert unavailable_fields_read(entities[1], ['primary_key_columns'])[
        'primary_key_columns']['reason'] == 'table_read_limit'


def test_the_read_budget_starts_at_the_first_read_not_at_the_reader():
    a = _table('a', [_col('id')])
    [entity] = _entities(a)
    times = [0.0]
    ws = _ws_with_get({'a': a})
    reader = TableConstraintsReader(ws, max_seconds=1, clock=lambda: times[0])
    times[0] = 500.0  # the table listing and LLM checks spent the time, no key read yet

    enrich_tables([entity], {'keys'}, None, reader)

    ws.tables.get.assert_called_once_with(full_name='main.sales.a')
    assert entity['primary_key_columns'] == []


def test_policy_run_checks_key_columns_through_tables_get(db_session):
    policy = CompliancePolicyDb(
        id=str(uuid.uuid4()), name='Key columns documented', is_active=True, rule=PK_RULE,
    )
    db_session.add(policy)
    db_session.flush()
    bad = _table('bad', [_col('id')])
    bad.table_constraints = _constraints(primary=['id'])
    good = _table('good', [_col('id', 'Id')])
    good.table_constraints = _constraints(primary=['id'])
    ws = _ws([_listed(bad), _listed(good)])
    ws.tables.get.side_effect = lambda full_name: {'bad': bad, 'good': good}[
        full_name.split('.')[-1]]

    with patch('src.common.workspace_client.get_workspace_client', return_value=ws):
        run = ComplianceManager().run_policy_inline(db_session, policy=policy)

    results = db_session.query(ComplianceResultDb).filter_by(run_id=run.id).all()
    assert {r.object_name: r.passed for r in results} == {'bad': False, 'good': True}


def test_policy_run_does_not_pass_tables_whose_constraints_could_not_be_read(db_session):
    policy = CompliancePolicyDb(
        id=str(uuid.uuid4()), name='Key columns documented', is_active=True, rule=PK_RULE,
    )
    db_session.add(policy)
    db_session.flush()
    ws = _ws([_listed(_table('orders', [_col('id')]))])
    ws.tables.get.side_effect = PermissionDenied('no')

    with patch('src.common.workspace_client.get_workspace_client', return_value=ws):
        run = ComplianceManager().run_policy_inline(db_session, policy=policy)

    results = db_session.query(ComplianceResultDb).filter_by(run_id=run.id).all()
    assert [r.passed for r in results] == [False]
    assert 'Not evaluated' in (results[0].message or '')
    assert 'table_no_access' in (results[0].message or '')
