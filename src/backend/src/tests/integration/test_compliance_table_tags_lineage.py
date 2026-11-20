"""Running a policy on UC table tags and lineage through the API (#1315)."""
import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from databricks.sdk.service.catalog import ColumnInfo, TableInfo, TableType
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.db_models.compliance import CompliancePolicyDb

RULE = "MATCH (t:table) ASSERT HAS_TAG('data_classification') AND t.upstream_count > 0"


def _table(name):
    return TableInfo(
        name=name, full_name=f'main.sales.{name}', catalog_name='main', schema_name='sales',
        table_type=TableType.MANAGED, columns=[ColumnInfo(name='id', comment='Id')],
    )


def _ws():
    ws = MagicMock()
    ws.catalogs.list.return_value = [SimpleNamespace(name='main')]
    ws.schemas.list.return_value = [SimpleNamespace(name='sales')]
    ws.tables.list.return_value = [_table('orders'), _table('raw_orders')]
    return ws


def _statement(columns, rows):
    return SimpleNamespace(
        statement_id='st', status=SimpleNamespace(state=SimpleNamespace(value='SUCCEEDED')),
        manifest=SimpleNamespace(schema=SimpleNamespace(
            columns=[SimpleNamespace(name=c) for c in columns])),
        result=SimpleNamespace(data_array=rows, next_chunk_index=None),
    )


def _answer(statement, **_):
    """The SQL warehouse: tags for orders, lineage for orders, nothing else."""
    if 'system.access.table_lineage' in statement:
        return _statement(['direction', 'table_full_name', 'table_count'],
                          [['upstream', 'main.sales.orders', '2']])
    return _statement(['schema_name', 'table_name', 'tag_name', 'tag_value'],
                      [['sales', 'orders', 'data_classification', 'internal']])


def _policy(db: Session) -> CompliancePolicyDb:
    policy = CompliancePolicyDb(
        id=str(uuid.uuid4()), name=f'policy-{uuid.uuid4().hex[:8]}', rule=RULE,
        category='Governance', severity='low', is_active=True,
    )
    db.add(policy)
    db.commit()
    return policy


def _run(client: TestClient, db: Session, ws, warehouse_id: str, app_ws=None):
    """Run the policy as a user: their token reads UC; ``app_ws`` is the app's client.

    The results are read back by the same user (their client lists what they see).
    """
    policy = _policy(db)
    with patch('src.common.workspace_client.get_obo_workspace_client', return_value=ws), \
            patch('src.common.workspace_client.get_workspace_client',
                  return_value=app_ws or MagicMock()), \
            patch('src.common.config.get_settings',
                  return_value=SimpleNamespace(DATABRICKS_WAREHOUSE_ID=warehouse_id)):
        response = client.post(
            f'/api/compliance/policies/{policy.id}/runs', json={},
            headers={'x-forwarded-access-token': 'user-token'},
        )
        assert response.status_code == 200, response.text
        run = response.json()
        results = _results(client, run['id'])
    return run, {r['object_name']: r for r in results['results']}


def _results(client: TestClient, run_id: str, headers=None):
    response = client.get(
        f"/api/compliance/runs/{run_id}/results",
        headers=headers if headers is not None else {'x-forwarded-access-token': 'user-token'},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_run_reads_tags_and_lineage_through_the_warehouse(client: TestClient, db_session: Session):
    ws = _ws()
    ws.statement_execution.execute_statement.side_effect = _answer

    run, results = _run(client, db_session, ws, 'wh-1')

    assert run['status'] == 'succeeded'
    assert run.get('warning_code') is None
    assert {n: r['passed'] for n, r in results.items()} == {'orders': True, 'raw_orders': False}
    calls = ws.statement_execution.execute_statement.call_args_list
    assert len(calls) == 2
    assert {c.kwargs['warehouse_id'] for c in calls} == {'wh-1'}


def test_run_without_warehouse_reports_not_evaluated(client: TestClient, db_session: Session):
    ws = _ws()

    run, results = _run(client, db_session, ws, '')

    ws.statement_execution.execute_statement.assert_not_called()
    assert run['status'] == 'succeeded'
    assert run['warning_code'] == 'rule_fields_unavailable'
    assert run['warning_params']['count'] == 2
    assert run['warning_params']['reasons'] == 'no_warehouse'
    # Not evaluated: out of the counts and the score
    assert (run['success_count'], run['failure_count']) == (0, 0)
    details = json.loads(results['orders']['details_json'])
    assert details['code'] == 'rule_field_unavailable'
    # Only the fields the rule reads
    assert details['params']['fields'] == 'tags, upstream_count'


def test_a_user_run_reads_uc_with_the_user_token(client: TestClient, db_session: Session):
    user_ws, app_ws = _ws(), _ws()
    user_ws.tables.list.return_value = [_table('orders')]
    user_ws.statement_execution.execute_statement.side_effect = _answer

    run, results = _run(client, db_session, user_ws, 'wh-1', app_ws=app_ws)

    assert run['status'] == 'succeeded'
    # A table the user can't list is not in the results, and the app reads nothing
    assert set(results) == {'orders'}
    app_ws.tables.list.assert_not_called()
    app_ws.statement_execution.execute_statement.assert_not_called()


def test_a_run_waits_on_the_warehouse_off_the_event_loop(
    client: TestClient, db_session: Session,
):
    from src.routes import compliance_routes

    ws = _ws()
    ws.statement_execution.execute_statement.side_effect = _answer
    calls = []
    real = compliance_routes.run_in_threadpool

    async def recording(func, *args, **kwargs):
        calls.append(func)
        return await real(func, *args, **kwargs)

    with patch.object(compliance_routes, 'run_in_threadpool', recording):
        run, _ = _run(client, db_session, ws, 'wh-1')

    assert run['status'] == 'succeeded'
    # The run, then the viewer's UC listings for its results
    assert calls == [compliance_routes.manager.run_policy_inline, compliance_routes.visible_results]


# --- results per viewer (#1387 review) --------------------------------------------------

def test_results_hide_tables_the_viewer_cannot_read(client: TestClient, db_session: Session):
    """A runs ASSERT HAS_TAG on two tables; B, who lists only orders, sees only orders."""
    ws = _ws()
    ws.statement_execution.execute_statement.side_effect = _answer
    run, _ = _run(client, db_session, ws, 'wh-1')
    viewer = _ws()
    viewer.tables.list.return_value = [_table('orders')]

    with patch('src.common.workspace_client.get_obo_workspace_client', return_value=viewer):
        body = _results(client, run['id'])

    assert [r['object_name'] for r in body['results']] == ['orders']
    assert body['hidden_count'] == 1 and body['total'] == 1
    # One listing for the schema, not one per result
    viewer.tables.list.assert_called_once_with(catalog_name='main', schema_name='sales')


def test_results_hide_every_uc_object_from_a_viewer_without_a_token(
    client: TestClient, db_session: Session,
):
    from src.common import workspace_client as wc

    ws = _ws()
    ws.statement_execution.execute_statement.side_effect = _answer
    run, _ = _run(client, db_session, ws, 'wh-1')

    # What get_obo_workspace_client does without a token outside ENV=LOCAL
    with patch('src.common.workspace_client.get_obo_workspace_client',
               side_effect=lambda *a, **k: wc.raise_user_token_required()):
        body = _results(client, run['id'], headers={})

    assert body['results'] == [] and body['hidden_count'] == 2


def test_a_run_that_evaluated_nothing_has_no_score_and_says_its_coverage(
    client: TestClient, db_session: Session,
):
    run, _ = _run(client, db_session, _ws(), '')

    assert run['score'] is None
    assert run['coverage'] == {'evaluated': 0, 'not_evaluated': 2}
    listed = client.get(f"/api/compliance/policies/{run['policy_id']}/runs").json()
    assert listed[0]['score'] is None and listed[0]['coverage']['not_evaluated'] == 2
