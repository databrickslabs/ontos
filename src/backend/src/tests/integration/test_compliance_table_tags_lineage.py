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
    # The run and its counts for the starter, then the viewer's UC listings for its results
    assert calls[:2] == [
        compliance_routes.manager.run_policy_inline, compliance_routes.manager.viewer_run_counts,
    ]
    assert len(calls) == 3 and calls[2].__name__ == '_read'


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
    # The starter lists both tables; a reader without a token would see neither counted
    with patch('src.common.workspace_client.get_obo_workspace_client', return_value=_ws()):
        listed = client.get(
            f"/api/compliance/policies/{run['policy_id']}/runs",
            headers={'x-forwarded-access-token': 'user-token'},
        ).json()
    assert listed[0]['score'] is None and listed[0]['coverage']['not_evaluated'] == 2


def _viewer_of_orders_only():
    viewer = _ws()
    viewer.tables.list.return_value = [_table('orders')]
    return viewer


def test_counts_and_score_cover_only_the_results_the_viewer_reads(
    client: TestClient, db_session: Session,
):
    """orders passes and raw_orders fails; a viewer who lists only orders sees a run
    of one pass, scored 100, in the results and in the run list (#1387 review)."""
    ws = _ws()
    ws.statement_execution.execute_statement.side_effect = _answer
    run, _ = _run(client, db_session, ws, 'wh-1')
    assert (run['success_count'], run['failure_count'], run['score']) == (1, 1, 50.0)

    with patch('src.common.workspace_client.get_obo_workspace_client',
               return_value=_viewer_of_orders_only()):
        seen = _results(client, run['id'])['run']
        listed = client.get(
            f"/api/compliance/policies/{run['policy_id']}/runs",
            headers={'x-forwarded-access-token': 'user-token'},
        ).json()[0]

    for payload in (seen, listed):
        assert (payload['success_count'], payload['failure_count']) == (1, 0)
        assert payload['score'] == 100.0
        assert payload['coverage'] == {'evaluated': 1, 'not_evaluated': 0}
        assert payload['hidden_count'] == 1


def test_a_viewer_who_reads_every_result_gets_the_stored_counts(
    client: TestClient, db_session: Session,
):
    ws = _ws()
    ws.statement_execution.execute_statement.side_effect = _answer
    run, _ = _run(client, db_session, ws, 'wh-1')

    with patch('src.common.workspace_client.get_obo_workspace_client', return_value=_ws()):
        seen = _results(client, run['id'])['run']

    assert (seen['success_count'], seen['failure_count'], seen['score']) == (1, 1, 50.0)
    assert seen['hidden_count'] == 0


def _stored_run(db: Session, **values):
    from src.db_models.compliance import ComplianceRunDb

    policy = _policy(db)
    run = ComplianceRunDb(
        id=str(uuid.uuid4()), policy_id=policy.id, status='failed',
        success_count=0, failure_count=0, score=None, **values,
    )
    db.add(run)
    db.commit()
    return run


def test_a_failed_run_sends_a_code_not_the_stored_error_text(
    client: TestClient, db_session: Session,
):
    sdk_error = _stored_run(
        db_session, error_message='PERMISSION_DENIED: no USE on main.secret.payroll',
        error_code='PERMISSION_DENIED',
    )
    no_code = _stored_run(db_session, error_message='connect to db.internal.example failed')
    coded = _stored_run(
        db_session, error_message='Could not load the data_product entities',
        error_code='entities_load_failed', error_params='{"entityType": "data_product"}',
    )

    for run, code, params in ((sdk_error, 'run_failed', None), (no_code, 'run_failed', None),
                              (coded, 'entities_load_failed', {'entityType': 'data_product'})):
        body = _results(client, run.id)
        listed = client.get(f'/api/compliance/policies/{run.policy_id}/runs')
        for payload in (body['run'], listed.json()[0]):
            assert (payload['error_code'], payload['error_params']) == (code, params)
            assert 'error_message' not in payload
        assert 'payroll' not in listed.text + json.dumps(body)
        assert 'internal.example' not in listed.text + json.dumps(body)


def test_results_are_paged_after_the_viewer_filter(client: TestClient, db_session: Session):
    """Hidden results take no place on a page, and the total counts every visible one."""
    from src.db_models.compliance import ComplianceResultDb, ComplianceRunDb

    policy = _policy(db_session)
    run = ComplianceRunDb(id=str(uuid.uuid4()), policy_id=policy.id, status='succeeded',
                          success_count=0, failure_count=4, score=0.0)
    db_session.add(run)
    rows = [('table', 'main.sales.payroll')] + [('data_product', f'p{i}') for i in range(3)]
    for object_type, object_id in rows:
        db_session.add(ComplianceResultDb(
            id=str(uuid.uuid4()), run_id=run.id, object_type=object_type,
            object_id=object_id, object_name=object_id, passed=False,
        ))
    db_session.commit()

    pages = []
    with patch('src.common.workspace_client.get_obo_workspace_client',
               return_value=_viewer_of_orders_only()):
        for offset in (0, 2):
            response = client.get(
                f'/api/compliance/runs/{run.id}/results?offset={offset}&limit=2',
                headers={'x-forwarded-access-token': 'user-token'},
            )
            assert response.status_code == 200, response.text
            pages.append(response.json())

    assert [len(p['results']) for p in pages] == [2, 1]
    assert {r['object_id'] for p in pages for r in p['results']} == {'p0', 'p1', 'p2'}
    assert all(p['total'] == 3 and p['hidden_count'] == 1 for p in pages)
    assert pages[0]['run']['failure_count'] == 3
