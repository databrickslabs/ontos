"""Follow-ups of the #1387 review: statement cancel and deadlines, per-policy budget,
tags on non-table UC objects, run scores with coverage, results per viewer."""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
import logging
import sqlite3
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from databricks.sdk.service.catalog import ColumnInfo, TableInfo, TableType

from src.common import uc_table_enrichment as enr
from src.common.compliance_result_visibility import ViewerReadChecks, visible_results
from src.common.uc_table_enrichment import SourceUnavailable, StatementCache, WarehouseSqlRunner
from src.controller.compliance_manager import ComplianceManager, run_score_fields
from src.db_models.compliance import CompliancePolicyDb, ComplianceResultDb, ComplianceRunDb
from src.repositories.compliance_repository import compliance_result_repo


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def _response(state, rows=None):
    return SimpleNamespace(
        statement_id='st-1',
        status=SimpleNamespace(state=SimpleNamespace(value=state), error=None),
        manifest=SimpleNamespace(schema=SimpleNamespace(
            columns=[SimpleNamespace(name='a')])),
        result=SimpleNamespace(data_array=rows or [], next_chunk_index=None),
    )


class CountingRunner:
    def __init__(self):
        self.calls = []

    def rows(self, statement, parameters):
        self.calls.append(dict(parameters))
        return [{'a': 1}]


# --- statements: cancel on a polling error, run deadline ----------------------------

def test_a_polling_error_cancels_the_statement_before_the_retry():
    from databricks.sdk import errors

    ws = MagicMock()
    ws.statement_execution.execute_statement.return_value = _response('RUNNING')
    ws.statement_execution.get_statement.side_effect = errors.TemporarilyUnavailable('503')
    clock = FakeClock()

    with pytest.raises(SourceUnavailable) as raised:
        WarehouseSqlRunner(ws, 'wh-1', clock=clock, sleep=clock.sleep).rows('SELECT 1', {})

    assert raised.value.reason == 'transient'
    # Every attempt cancels its own statement: no copy keeps running
    attempts = ws.statement_execution.execute_statement.call_count
    assert attempts == 3
    assert ws.statement_execution.cancel_execution.call_count == attempts


def test_the_run_deadline_cuts_a_running_statement_short():
    ws = MagicMock()
    ws.statement_execution.execute_statement.return_value = _response('RUNNING')
    ws.statement_execution.get_statement.return_value = _response('RUNNING')
    clock = FakeClock()
    cache = StatementCache(max_run_seconds=60, clock=clock)
    runner = cache.runner(WarehouseSqlRunner(ws, 'wh-1', clock=clock, sleep=clock.sleep))

    with pytest.raises(SourceUnavailable) as raised:
        runner.rows('SELECT 1', {})

    assert raised.value.reason == 'timed_out'
    assert 60 <= clock.now < WarehouseSqlRunner.DEADLINE_SECONDS
    ws.statement_execution.cancel_execution.assert_called_once_with('st-1')


def test_past_the_run_deadline_new_statements_are_timed_out_and_cached_rows_still_serve():
    clock = FakeClock()
    cache = StatementCache(max_run_seconds=900, clock=clock)
    inner = CountingRunner()
    runner = cache.runner(inner)
    assert runner.rows('SELECT 1', {'catalog': 'main'}) == [{'a': 1}]

    clock.now = 901
    with pytest.raises(SourceUnavailable) as raised:
        runner.rows('SELECT 1', {'catalog': 'lake'})
    assert raised.value.reason == 'timed_out'
    assert runner.rows('SELECT 1', {'catalog': 'main'}) == [{'a': 1}]
    # The next policy run has its own deadline, and sends the statement
    cache.start_run()
    assert runner.rows('SELECT 1', {'catalog': 'lake'}) == [{'a': 1}]
    assert [c['catalog'] for c in inner.calls] == ['main', 'lake']


def test_each_policy_run_has_its_own_statement_count_and_keeps_the_cache():
    cache = StatementCache(max_statements=1)
    inner = CountingRunner()
    runner = cache.runner(inner)
    runner.rows('SELECT 1', {'catalog': 'main'})
    with pytest.raises(SourceUnavailable):
        runner.rows('SELECT 1', {'catalog': 'lake'})

    cache.start_run()

    assert runner.rows('SELECT 1', {'catalog': 'main'}) == [{'a': 1}]  # cached, not counted
    assert runner.rows('SELECT 1', {'catalog': 'lake'}) == [{'a': 1}]
    assert [c['catalog'] for c in inner.calls] == ['main', 'lake']


def _table(name, schema='sales', catalog='main'):
    return TableInfo(
        name=name, full_name=f'{catalog}.{schema}.{name}', catalog_name=catalog,
        schema_name=schema, table_type=TableType.MANAGED,
        columns=[ColumnInfo(name='id', comment='Id')],
    )


def _ws(tables_by_schema, catalogs=('main',)):
    ws = MagicMock()
    ws.catalogs.list.return_value = [SimpleNamespace(name=c) for c in catalogs]
    ws.schemas.list.side_effect = lambda catalog_name: [
        SimpleNamespace(name=s, full_name=f'{c}.{s}')
        for (c, s) in tables_by_schema if c == catalog_name
    ]
    ws.tables.list.side_effect = lambda catalog_name, schema_name: list(
        tables_by_schema.get((catalog_name, schema_name), [])
    )
    return ws


def _policy(db, rule):
    policy = CompliancePolicyDb(id=str(uuid.uuid4()), name='p', is_active=True, rule=rule)
    db.add(policy)
    db.flush()
    return policy


def _run(db, rule, ws, cache=None, runner=None):
    settings = SimpleNamespace(DATABRICKS_WAREHOUSE_ID='wh-1')
    with patch('src.common.workspace_client.get_workspace_client', return_value=ws), \
            patch('src.common.config.get_settings', return_value=settings), \
            patch('src.controller.compliance_manager.WarehouseSqlRunner',
                  return_value=runner or CountingRunner()):
        return ComplianceManager().run_policy_inline(
            db, policy=_policy(db, rule), statement_cache=cache,
        )


def test_job_policies_sharing_a_cache_each_get_the_full_budget(db_session):
    """Results don't depend on policy order: the second policy isn't budget_exceeded."""
    ws = _ws({('main', 'sales'): [_table('orders')],
              ('lake', 'bronze'): [_table('events', 'bronze', 'lake')]},
             catalogs=('main', 'lake'))
    cache = StatementCache(max_statements=2)

    first = _run(db_session, "MATCH (t:table) ASSERT NOT HAS_TAG('x')", ws, cache)
    second = _run(db_session, "MATCH (t:table) ASSERT t.upstream_count >= 0", ws, cache)

    assert first.warning_code is None and second.warning_code is None
    assert (second.success_count, second.failure_count) == (2, 0)


# --- tags on catalogs and schemas ----------------------------------------------------

@pytest.mark.parametrize('entity_type', ['catalog', 'schema'])
def test_has_tag_on_catalogs_and_schemas_is_not_evaluated(db_session, entity_type):
    ws = _ws({('main', 'sales'): [_table('orders')]})

    run = _run(db_session, f"MATCH (o:{entity_type}) ASSERT NOT HAS_TAG('x')", ws)

    results = db_session.query(ComplianceResultDb).filter_by(run_id=run.id).all()
    assert results and not any(r.passed for r in results)
    assert (run.success_count, run.failure_count) == (0, 0)
    assert run.warning_code == 'rule_fields_unavailable'
    params = json.loads(results[0].details_json)['params']
    assert (params['fields'], params['reason']) == ('tags', 'not_loaded')


def test_rules_on_schemas_without_tags_still_evaluate(db_session):
    ws = _ws({('main', 'sales'): [_table('orders')]})

    run = _run(db_session, "MATCH (s:schema) ASSERT s.name = 'sales'", ws)

    assert (run.success_count, run.failure_count, run.warning_code) == (1, 0, None)


# --- the mixed-case tags statement, run on a database ---------------------------------

def test_tags_statement_matches_mixed_case_rows_when_run():
    statement, params = enr.tags_statement('Main', ['Sales'])
    con = sqlite3.connect(':memory:')
    con.execute('CREATE TABLE table_tags (catalog_name, schema_name, table_name, '
                'tag_name, tag_value)')
    con.executemany('INSERT INTO table_tags VALUES (?, ?, ?, ?, ?)', [
        ('MAIN', 'SALES', 'ORDERS', 'pii', ''),
        ('main', 'Sales', 'Customers', 'tier', 'gold'),
        ('other', 'sales', 'orders', 'pii', ''),
    ])
    con.row_factory = sqlite3.Row

    rows = [dict(r) for r in con.execute(
        statement.replace(enr.TABLE_TAGS_SOURCE, 'table_tags'), params)]

    orders = enr.table_entity(_table('Orders', schema='Sales', catalog='Main'))
    customers = enr.table_entity(_table('customers', schema='sales', catalog='main'))
    enr.apply_tag_rows([orders, customers], rows)
    assert orders['tags'] == {'pii': True}
    assert customers['tags'] == {'tier': 'gold'}


# --- user runs need the user's identity; the SP fallback warns ------------------------

def test_a_user_run_without_their_identity_is_refused(db_session):
    policy = _policy(db_session, "MATCH (p:data_product) ASSERT p.name != ''")

    with pytest.raises(ValueError):
        ComplianceManager().run_policy_inline(
            db_session, policy=policy, current_user='a@example.com',
        )


@pytest.mark.parametrize('settings, warned', [
    (SimpleNamespace(ENV='LOCAL', OBO_ALLOW_SP_FALLBACK=False), True),
    (SimpleNamespace(ENV='PROD', OBO_ALLOW_SP_FALLBACK=True), True),
    (SimpleNamespace(ENV='PROD', OBO_ALLOW_SP_FALLBACK=False), False),
])
def test_startup_warns_when_requests_without_a_token_read_as_the_app(caplog, settings, warned):
    from src.common.workspace_client import warn_if_sp_fallback

    with caplog.at_level(logging.WARNING):
        assert warn_if_sp_fallback(settings) is warned
    assert ('service principal' in caplog.text) is warned


def test_one_user_token_required_error():
    from src.common import api_errors
    from src.controller import metric_views_manager

    assert metric_views_manager.UserTokenRequiredError is api_errors.UserTokenRequiredError


# --- only_failed parses the details ---------------------------------------------------

def test_only_failed_keeps_a_failure_whose_action_outcome_quotes_the_code(db_session):
    run = ComplianceRunDb(id=str(uuid.uuid4()), policy_id=_policy(db_session, 'x').id)
    db_session.add(run)
    action = json.dumps({'actions': [{'code': enr.NOT_EVALUATED_CODE, 'success': False}]})
    not_evaluated = json.dumps({'code': enr.NOT_EVALUATED_CODE, 'params': {}})
    for name, details in (('failed', action), ('skipped', not_evaluated), ('plain', None)):
        db_session.add(ComplianceResultDb(
            id=str(uuid.uuid4()), run_id=run.id, object_type='table', object_id=name,
            object_name=name, passed=False, details_json=details,
        ))
    db_session.flush()

    failed = compliance_result_repo.list_for_run(db_session, run_id=run.id, only_failed=True)

    assert sorted(r.object_name for r in failed) == ['failed', 'plain']
    assert compliance_result_repo.not_evaluated_counts(db_session, [run.id]) == {run.id: 1}


# --- scores and coverage --------------------------------------------------------------

def _stored_run(status='succeeded', success=0, failure=0, score=0.0):
    return SimpleNamespace(
        status=status, success_count=success, failure_count=failure, score=score,
    )


@pytest.mark.parametrize('run, not_evaluated, expected', [
    (_stored_run(success=1, failure=1, score=50.0), 4,
     {'score': 50.0, 'coverage': {'evaluated': 2, 'not_evaluated': 4}}),
    # Nothing evaluated (all not evaluated, or nothing matched): no score
    (_stored_run(), 2, {'score': None, 'coverage': {'evaluated': 0, 'not_evaluated': 2}}),
    (_stored_run(), 0, {'score': None, 'coverage': {'evaluated': 0, 'not_evaluated': 0}}),
    # A failed run has no score, whatever it evaluated before the error
    (_stored_run('failed', success=3, score=0.0), 0,
     {'score': None, 'coverage': {'evaluated': 3, 'not_evaluated': 0}}),
])
def test_run_score_fields(run, not_evaluated, expected):
    assert run_score_fields(run, not_evaluated) == expected


def test_a_failed_run_keeps_the_previous_score(db_session):
    from datetime import datetime, timedelta

    policy = _policy(db_session, "MATCH (p:data_product) ASSERT p.name != ''")
    now = datetime.utcnow()
    db_session.add_all([
        ComplianceRunDb(id=str(uuid.uuid4()), policy_id=policy.id, status='succeeded',
                        success_count=4, failure_count=1, score=80.0,
                        started_at=now - timedelta(minutes=2)),
        ComplianceRunDb(id=str(uuid.uuid4()), policy_id=policy.id, status='failed',
                        score=0.0, started_at=now - timedelta(minutes=1)),
    ])
    db_session.flush()

    assert ComplianceManager._latest_score(db_session, policy.id) == 80.0


# --- results per viewer ----------------------------------------------------------------

def _result(object_type, object_id):
    return SimpleNamespace(object_type=object_type, object_id=object_id)


def test_viewer_checks_list_each_schema_once_and_fail_closed():
    ws = MagicMock()
    ws.catalogs.list.return_value = [SimpleNamespace(name='main')]
    ws.schemas.list.side_effect = lambda catalog_name: (
        [SimpleNamespace(name='Sales')] if catalog_name == 'main' else []
    )
    ws.tables.list.side_effect = lambda catalog_name, schema_name: (
        [SimpleNamespace(name='orders')] if schema_name == 'sales' else
        (_ for _ in ()).throw(PermissionError('denied'))
    )
    results = [
        _result('table', 'main.sales.orders'), _result('table', 'main.sales.Orders'),
        _result('table', 'main.sales.salaries'), _result('view', 'main.hr.people'),
        _result('schema', 'main.sales'), _result('schema', 'lake.raw'),
        _result('catalog', 'main'), _result('catalog', 'hr'),
        _result('data_product', 'p1'),
    ]

    shown, hidden = visible_results(results, ViewerReadChecks(lambda: ws))

    assert [(r.object_type, r.object_id) for r in shown] == [
        ('table', 'main.sales.orders'), ('table', 'main.sales.Orders'),
        ('schema', 'main.sales'), ('catalog', 'main'), ('data_product', 'p1'),
    ]
    assert hidden == 4
    assert ws.tables.list.call_count == 2  # sales once, hr once (denied: hidden)


def test_a_viewer_without_a_client_sees_no_uc_result():
    def no_token():
        raise RuntimeError('no token')

    shown, hidden = visible_results(
        [_result('table', 'main.sales.orders'), _result('domain', 'd1')],
        ViewerReadChecks(no_token),
    )

    assert [r.object_type for r in shown] == ['domain'] and hidden == 1
