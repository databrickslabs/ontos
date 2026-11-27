"""Bulk maturity evaluation of table and view assets, through the API (#1316 slice)."""
import uuid

import pytest

from src.common.features import FeatureAccessLevel
from src.controller import maturity_bulk_evaluator as bulk
from src.controller.authorization_manager import AuthorizationManager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.maturity import MaturityLevelDb

START = '/api/maturity-evaluations/assets'
LATEST = '/api/maturity-evaluations/assets/latest'


@pytest.fixture(autouse=True)
def _no_run_in_memory():
    bulk._current = None
    yield
    bulk._current = None


def _asset(db, location, type_name='Table'):
    asset_type = db.query(AssetTypeDb).filter_by(name=type_name).first()
    if asset_type is None:
        asset_type = AssetTypeDb(name=type_name)
        db.add(asset_type)
        db.flush()
    # platform other than databricks: the evaluation reads no Unity Catalog table
    row = AssetDb(name=f'a-{uuid.uuid4().hex[:6]}', asset_type_id=asset_type.id,
                  platform='other', location=location, status='active')
    db.add(row)
    db.flush()
    return str(row.id)


def _asset_level(db):
    db.add(MaturityLevelDb(level_order=1, name='Prerequisite', entity_type='Asset'))
    db.flush()


class TestBulkAssetMaturityEvaluation:

    def test_an_admin_starts_a_run_for_the_scope_and_reads_the_summary(self, client, db_session):
        _asset_level(db_session)
        _asset(db_session, 'bulkt.sales.orders')
        _asset(db_session, 'bulkt.sales.items', type_name='View')
        _asset(db_session, 'bulkt.finance.gl')  # outside the schema
        _asset(db_session, 'bulkt.sales.board', type_name='Dashboard')  # not a table or view

        response = client.post(START, json={'catalog': 'bulkt', 'schema_name': 'sales',
                                            'max_workers': 2, 'batch_size': 10})

        assert response.status_code == 202, response.text
        assert response.json()['scope'] == {'catalog': 'bulkt', 'schema': 'sales',
                                            'asset_types': ['Table', 'View', 'Metric View']}
        latest = client.get(LATEST)
        assert latest.status_code == 200, latest.text
        summary = latest.json()
        assert summary['state'] == 'completed'
        assert summary['finished_at'] is not None
        assert summary['started_by']  # the caller's email
        assert (summary['total'], summary['processed']) == (2, 2)
        assert summary['evaluated'] == 2
        assert summary['skipped'] == {}
        assert summary['error_count'] == 0

    def test_a_second_run_while_one_is_running_gets_409(self, client, db_session):
        bulk.start_run(bulk.normalize_scope('bulkt', None, None))

        response = client.post(START, json={'catalog': 'bulkt'})

        assert response.status_code == 409, response.text
        assert response.json()['detail']['code'] == 'maturity_bulk_run_in_progress'

    def test_a_schema_without_a_catalog_gets_400(self, client):
        response = client.post(START, json={'schema_name': 'sales'})

        assert response.status_code == 400, response.text
        assert response.json()['detail']['code'] == 'maturity_bulk_scope_invalid'

    def test_no_run_yet_reads_as_null(self, client):
        response = client.get(LATEST)

        assert response.status_code == 200
        assert response.json() is None

    def test_a_user_without_settings_access_gets_403(self, client, mock_test_user):
        mock_test_user.groups = []

        assert client.post(START, json={}).status_code == 403
        assert client.get(LATEST).status_code == 403


class TestBulkAssetMaturityAccessLevels:
    """Reading the summary needs Settings read access; starting a run needs read/write."""

    @pytest.fixture
    def read_only_settings(self, monkeypatch):
        monkeypatch.setattr(
            AuthorizationManager, 'get_user_effective_permissions',
            lambda self, *args, **kwargs: {'settings': FeatureAccessLevel.READ_ONLY},
        )

    def test_a_read_only_user_reads_the_summary_but_cannot_start_a_run(
        self, client, read_only_settings,
    ):
        assert client.get(LATEST).status_code == 200
        assert client.post(START, json={}).status_code == 403


class TestBulkRunReadsAsTheCaller:
    """An admin-started bulk run reads the UC tables with the admin's token, not the app's."""

    def test_the_run_reads_with_the_callers_token(
            self, client, db_session, monkeypatch, mock_workspace_client):
        from unittest.mock import MagicMock

        from databricks.sdk.errors import PermissionDenied
        from databricks.sdk.service.catalog import ColumnInfo, TableInfo
        from src.common import workspace_client as workspace_client_module
        from src.db_models.compliance import CompliancePolicyDb
        from src.db_models.maturity import MaturitySnapshotDb
        from src.repositories.maturity_repository import maturity_repo

        mock_workspace_client.tables.get.side_effect = PermissionDenied('app has no grant')
        user_ws = MagicMock()
        user_ws.tables.get.return_value = TableInfo(full_name='bulku.sales.orders', columns=[
            ColumnInfo(name='id', comment='Id', type_text='bigint'),
        ])
        monkeypatch.setattr(workspace_client_module, 'get_obo_workspace_client',
                            lambda *a, **k: user_ws)
        level = MaturityLevelDb(level_order=1, name='Has columns', entity_type='Asset')
        policy = CompliancePolicyDb(id=str(uuid.uuid4()), name='Columns',
                                    rule='ASSERT obj.column_count > 0', is_active=True)
        db_session.add_all([level, policy])
        db_session.flush()
        maturity_repo.add_gate(db_session, maturity_level_id=level.id,
                               compliance_policy_id=policy.id)
        asset_type = db_session.query(AssetTypeDb).filter_by(name='Table').first()
        if asset_type is None:
            asset_type = AssetTypeDb(name='Table')
            db_session.add(asset_type)
            db_session.flush()
        row = AssetDb(name=f'a-{uuid.uuid4().hex[:6]}', asset_type_id=asset_type.id,
                      platform='databricks', location='bulku.sales.orders', status='active')
        db_session.add(row)
        db_session.flush()

        response = client.post(START, json={'catalog': 'bulku'})

        assert response.status_code == 202, response.text
        user_ws.tables.get.assert_called_with(full_name='bulku.sales.orders')
        snapshots = db_session.query(MaturitySnapshotDb).filter_by(entity_id=str(row.id)).all()
        assert [s.achieved_level_order for s in snapshots] == [1]
