"""Column fields on Unity Catalog table/view entities for compliance rules (#1315)."""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from databricks.sdk.service.catalog import ColumnInfo, ColumnTypeName, TableInfo, TableType

from src.common.compliance_dsl import Evaluator, parse_rule
from src.common.compliance_entities import UnityCatalogLoader
from src.common.uc_table_columns import table_column_fields
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
        # The loader tells views apart by the string 'VIEW'
        _table('v_orders', [_col('id', 'Order id')], table_type='VIEW'),
    ])

    entities = list(UnityCatalogLoader(ws).load_entities(['table', 'view']))

    by_name = {e['name']: e for e in entities}
    assert by_name['orders']['type'] == 'table'
    assert by_name['orders']['column_count'] == 2
    assert by_name['orders']['column_comment_ratio'] == 0.5
    assert by_name['v_orders']['type'] == 'view'
    assert by_name['v_orders']['columns_without_comment_count'] == 0
    assert 'primary_key_columns' not in by_name['orders']
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
