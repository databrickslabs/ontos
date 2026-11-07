"""Maturity levels for table and view assets, through the API (#1316)."""
import json
import uuid

import pytest
from databricks.sdk.errors import NotFound
from databricks.sdk.service.catalog import ColumnInfo, TableInfo

from src.common import workflow_triggers
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.compliance import CompliancePolicyDb
from src.db_models.maturity import MaturitySnapshotDb
from src.models.process_workflows import EntityType

FQN = 'main.sales.orders'


def _asset(db, type_name='Table', **fields):
    asset_type = db.query(AssetTypeDb).filter_by(name=type_name).first()
    if asset_type is None:
        asset_type = AssetTypeDb(name=type_name)
        db.add(asset_type)
        db.flush()
    row = AssetDb(name=f'orders-{uuid.uuid4().hex[:6]}', asset_type_id=asset_type.id,
                  platform='databricks', location=FQN, status='active', **fields)
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def fired(monkeypatch):
    """The ON_MATURITY_CHANGE events the evaluation fires."""
    events = []

    def record(self, **kwargs):
        events.append(kwargs)
        return []

    monkeypatch.setattr(workflow_triggers.TriggerRegistry, 'on_maturity_change', record)
    return events


@pytest.fixture
def uc_table(mock_workspace_client):
    mock_workspace_client.tables.get.return_value = TableInfo(full_name=FQN, columns=[
        ColumnInfo(name='id', comment='Order id', type_text='bigint'),
        ColumnInfo(name='amount', comment='Amount', type_text='decimal'),
    ])
    return mock_workspace_client


def _asset_ladder(client, db_session):
    """Two Asset levels created through the API: described, then documented columns."""
    ids = []
    for order, name, rule in [
        (1, 'Described', 'ASSERT obj.has_description = True'),
        (2, 'Documented columns', 'ASSERT obj.column_comment_ratio >= 0.8'),
    ]:
        response = client.post('/api/maturity-levels', json={
            'name': name, 'level_order': order, 'entity_type': 'Asset',
        })
        assert response.status_code == 201, response.text
        level = response.json()
        assert level['entity_type'] == 'Asset'
        policy = CompliancePolicyDb(id=str(uuid.uuid4()), name=f'Asset gate {name}', rule=rule,
                                    is_active=True)
        db_session.add(policy)
        db_session.flush()
        response = client.post(f"/api/maturity-levels/{level['id']}/gates",
                               json={'compliance_policy_id': policy.id})
        assert response.status_code == 201, response.text
        ids.append(level['id'])
    listed = client.get('/api/maturity-levels', params={'entity_type': 'Asset'}).json()
    assert [lv['name'] for lv in listed if lv['entity_type'] == 'Asset'] == [
        'Described', 'Documented columns',
    ]
    return ids


class TestAssetMaturityRoutes:
    def test_evaluate_stores_a_snapshot_and_fires_the_event(
            self, client, db_session, uc_table, fired):
        _asset_ladder(client, db_session)
        asset = _asset(db_session, description='Orders placed in the shop')

        response = client.post(f'/api/assets/{asset.id}/maturity/evaluate')

        assert response.status_code == 200, response.text
        report = response.json()
        assert report['entity_type'] == 'Asset'
        assert report['achieved_level_order'] == 2
        assert report['achieved_level_name'] == 'Documented columns'
        assert report['notices'] == []
        uc_table.tables.get.assert_called_with(full_name=FQN)

        history = client.get(f'/api/assets/{asset.id}/maturity/history').json()
        assert len(history) == 1 and history[0]['achieved_level_order'] == 2
        assert history[0]['entity_type'] == 'Asset'

        assert len(fired) == 1
        assert fired[0]['entity_type'] == EntityType.TABLE
        # The UC full name, like the self-service table events; asset id in the payload
        assert fired[0]['entity_id'] == FQN
        assert fired[0]['entity_data']['asset_id'] == str(asset.id)
        assert fired[0]['from_level'] is None and fired[0]['to_level'] == 2

    def test_unreadable_table_is_a_coded_gate_message(
            self, client, db_session, mock_workspace_client, fired):
        _asset_ladder(client, db_session)
        asset = _asset(db_session, description='Orders')
        mock_workspace_client.tables.get.side_effect = NotFound('Table main.sales.orders gone')

        response = client.get(f'/api/assets/{asset.id}/maturity')

        assert response.status_code == 200, response.text
        report = response.json()
        assert report['achieved_level_order'] == 1
        gate = report['levels'][1]['gates'][0]
        assert gate['passed'] is False
        assert gate['message_code'] == 'maturity_uc_table_not_found'
        assert gate['message_params'] == {'tableName': FQN}
        assert 'gone' not in response.text
        assert [n['code'] for n in report['notices']] == ['maturity_uc_table_not_found']

        snapshot = db_session.query(MaturitySnapshotDb).filter_by(entity_id=str(asset.id)).one()
        stored = json.loads(snapshot.gate_results_json)
        assert stored[1]['message_code'] == 'maturity_uc_table_not_found'

    def test_other_asset_types_answer_a_coded_400(self, client, db_session):
        asset = _asset(db_session, 'Dashboard')

        response = client.post(f'/api/assets/{asset.id}/maturity/evaluate')

        assert response.status_code == 400, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'maturity_asset_type_unsupported'
        assert detail['params'] == {'assetType': 'Dashboard'}

    def test_unknown_asset_is_404(self, client):
        response = client.post(f'/api/assets/{uuid.uuid4()}/maturity/evaluate')

        assert response.status_code == 404

    def test_updating_an_asset_re_evaluates_it(self, client, db_session, uc_table, fired):
        _asset_ladder(client, db_session)
        asset = _asset(db_session)

        response = client.put(f'/api/assets/{asset.id}', json={
            'description': 'Orders placed in the shop',
        })

        assert response.status_code == 200, response.text
        snapshots = db_session.query(MaturitySnapshotDb).filter_by(entity_id=str(asset.id)).all()
        assert [s.achieved_level_order for s in snapshots] == [2]
        assert snapshots[0].evaluated_by == 'test@example.com'
        assert [e['to_level'] for e in fired] == [2]

    def test_asset_levels_leave_product_ladders_alone(self, client, db_session):
        _asset_ladder(client, db_session)

        product_levels = client.get(
            '/api/maturity-levels', params={'entity_type': 'DataProduct'},
        ).json()

        assert all(lv['entity_type'] != 'Asset' for lv in product_levels)

    def test_gate_error_answers_a_code_without_the_exception(self, client, db_session, uc_table):
        response = client.post('/api/maturity-levels', json={
            'name': 'Broken', 'level_order': 1, 'entity_type': 'Asset',
        })
        level = response.json()
        policy = CompliancePolicyDb(id=str(uuid.uuid4()), name='Broken gate',
                                    rule='ASSERT LENGTH(obj.name, obj.status) > 0',
                                    is_active=True)
        db_session.add(policy)
        db_session.flush()
        client.post(f"/api/maturity-levels/{level['id']}/gates",
                    json={'compliance_policy_id': policy.id})
        asset = _asset(db_session)

        response = client.post(f'/api/assets/{asset.id}/maturity/evaluate')

        assert response.status_code == 200, response.text
        gate = response.json()['levels'][0]['gates'][0]
        assert gate['message_code'] == 'maturity_gate_error'
        assert gate['message_params'] == {'gateName': 'Broken gate'}
        assert 'LENGTH expects' not in response.text
        snapshot = db_session.query(MaturitySnapshotDb).filter_by(entity_id=str(asset.id)).one()
        assert 'LENGTH expects' not in snapshot.gate_results_json
        assert json.loads(snapshot.gate_results_json)[0]['message_code'] == 'maturity_gate_error'


class TestLevelDeletionPerEntityType:
    def _create(self, client, name, entity_type):
        response = client.post('/api/maturity-levels', json={
            'name': name, 'level_order': 7, 'entity_type': entity_type,
        })
        assert response.status_code == 201, response.text
        return response.json()['id']

    def _snapshot(self, db_session, entity_type):
        db_session.add(MaturitySnapshotDb(
            entity_type=entity_type, entity_id=str(uuid.uuid4()),
            achieved_level_order=7, achieved_level_name='x',
        ))
        db_session.flush()

    def test_an_asset_snapshot_does_not_block_product_or_shared_levels(self, client, db_session):
        product = self._create(client, 'Product L7', 'DataProduct')
        shared = self._create(client, 'Shared L7', 'all')
        asset = self._create(client, 'Asset L7', 'Asset')
        self._snapshot(db_session, 'Asset')

        assert client.delete(f'/api/maturity-levels/{product}').status_code == 204
        assert client.delete(f'/api/maturity-levels/{shared}').status_code == 204
        # Last: a refused request rolls back the test's transaction
        assert client.delete(f'/api/maturity-levels/{asset}').status_code == 409

    def test_a_product_snapshot_does_not_block_an_asset_level(self, client, db_session):
        shared = self._create(client, 'Shared L7', 'all')
        asset = self._create(client, 'Asset L7', 'Asset')
        self._snapshot(db_session, 'DataProduct')

        assert client.delete(f'/api/maturity-levels/{asset}').status_code == 204
        # Last: a refused request rolls back the test's transaction
        assert client.delete(f'/api/maturity-levels/{shared}').status_code == 409
