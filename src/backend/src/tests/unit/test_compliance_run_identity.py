"""Whose Unity Catalog permissions a compliance run reads with (#1387 review).

A run a user starts reads UC with the user's own token, so its stored results
don't show tables, tags or lineage the user has no grant on; a scheduled run
(no identity passed) reads as the app.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from databricks.sdk.service.catalog import ColumnInfo, TableInfo, TableType

from src.common.api_errors import UserTokenRequiredError
from src.common.run_identity import RunIdentity
from src.controller.compliance_manager import ComplianceManager
from src.db_models.compliance import CompliancePolicyDb, ComplianceResultDb


def _ws(*table_names):
    ws = MagicMock()
    ws.catalogs.list.return_value = [SimpleNamespace(name='main')]
    ws.schemas.list.return_value = [SimpleNamespace(name='sales')]
    ws.tables.list.return_value = [
        TableInfo(name=n, full_name=f'main.sales.{n}', catalog_name='main',
                  schema_name='sales', table_type=TableType.MANAGED,
                  columns=[ColumnInfo(name='id', comment='Id')])
        for n in table_names
    ]
    return ws


def _policy(db, rule):
    policy = CompliancePolicyDb(id=str(uuid.uuid4()), name='p', is_active=True, rule=rule)
    db.add(policy)
    db.flush()
    return policy


def _names(db, run):
    rows = db.query(ComplianceResultDb).filter_by(run_id=run.id).all()
    return sorted(r.object_name for r in rows)


def _request(headers):
    return SimpleNamespace(headers=headers)


def test_user_identity_builds_the_client_lazily_from_the_user_token():
    user_ws = object()
    identity = RunIdentity.for_request(_request({'x-forwarded-access-token': 't'}))
    with patch('src.common.workspace_client.get_obo_workspace_client',
               return_value=user_ws) as obo:
        assert obo.call_count == 0  # nothing built before a UC read
        assert identity.workspace_client() is user_ws
        assert identity.workspace_client() is user_ws
    assert obo.call_count == 1
    assert identity.on_behalf_of_user is True
    assert RunIdentity.app().on_behalf_of_user is False


def test_user_identity_without_token_raises_the_coded_error():
    settings = SimpleNamespace(ENV='PROD', OBO_ALLOW_SP_FALLBACK=False)
    identity = RunIdentity.for_request(_request({}), settings)

    with patch('src.common.workspace_client.get_workspace_client') as app_client, \
            pytest.raises(UserTokenRequiredError):
        identity.workspace_client()
    app_client.assert_not_called()


def test_a_user_run_lists_tables_with_the_user_client_not_the_app(db_session):
    app_ws, user_ws = _ws('orders', 'salaries'), _ws('orders')
    identity = RunIdentity(lambda: user_ws, on_behalf_of_user=True)
    policy = _policy(db_session, "MATCH (t:table) ASSERT t.column_count > 0")

    with patch('src.common.workspace_client.get_workspace_client', return_value=app_ws):
        run = ComplianceManager().run_policy_inline(
            db_session, policy=policy, run_identity=identity,
        )

    assert run.status == 'succeeded'
    assert _names(db_session, run) == ['orders']
    app_ws.tables.list.assert_not_called()


def test_a_user_run_reads_tags_with_the_user_client(db_session):
    user_ws = _ws('orders')
    identity = RunIdentity(lambda: user_ws, on_behalf_of_user=True)
    policy = _policy(db_session, "MATCH (t:table) ASSERT HAS_TAG('pii')")
    settings = SimpleNamespace(DATABRICKS_WAREHOUSE_ID='wh-1')

    with patch('src.common.workspace_client.get_workspace_client') as app_client, \
            patch('src.common.config.get_settings', return_value=settings), \
            patch('src.controller.compliance_manager.WarehouseSqlRunner') as make_runner:
        make_runner.return_value.rows.return_value = []
        ComplianceManager().run_policy_inline(db_session, policy=policy, run_identity=identity)

    app_client.assert_not_called()
    assert make_runner.call_args.args[0] is user_ws


def test_a_scheduled_run_reads_as_the_app(db_session):
    app_ws = _ws('orders', 'salaries')
    policy = _policy(db_session, "MATCH (t:table) ASSERT t.column_count > 0")

    with patch('src.common.workspace_client.get_workspace_client', return_value=app_ws):
        run = ComplianceManager().run_policy_inline(db_session, policy=policy)

    assert _names(db_session, run) == ['orders', 'salaries']


def test_a_user_run_without_token_fails_with_a_code(db_session):
    def no_token():
        raise UserTokenRequiredError('no token')

    policy = _policy(db_session, "MATCH (t:table) ASSERT t.column_count > 0")

    run = ComplianceManager().run_policy_inline(
        db_session, policy=policy,
        run_identity=RunIdentity(no_token, on_behalf_of_user=True),
    )

    assert run.status == 'failed'
    assert run.error_code == 'user_token_required'
    assert _names(db_session, run) == []
