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
    return _statement(['schema_name', 'table_name', 'column_name', 'tag_name', 'tag_value'],
                      [['sales', 'orders', None, 'data_classification', 'internal']])


def _policy(db: Session) -> CompliancePolicyDb:
    policy = CompliancePolicyDb(
        id=str(uuid.uuid4()), name=f'policy-{uuid.uuid4().hex[:8]}', rule=RULE,
        category='Governance', severity='low', is_active=True,
    )
    db.add(policy)
    db.commit()
    return policy


def _run(client: TestClient, db: Session, ws, warehouse_id: str):
    policy = _policy(db)
    with patch('src.common.workspace_client.get_workspace_client', return_value=ws), \
            patch('src.common.config.get_settings',
                  return_value=SimpleNamespace(DATABRICKS_WAREHOUSE_ID=warehouse_id)):
        response = client.post(f'/api/compliance/policies/{policy.id}/runs', json={})
    assert response.status_code == 200, response.text
    run = response.json()
    results = client.get(f"/api/compliance/runs/{run['id']}/results")
    assert results.status_code == 200, results.text
    return run, {r['object_name']: r for r in results.json()['results']}


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
    assert run['failure_count'] == 2
    details = json.loads(results['orders']['details_json'])
    assert details['code'] == 'rule_field_unavailable'
    # Only the fields the rule reads
    assert details['params']['fields'] == 'tags, upstream_count'
