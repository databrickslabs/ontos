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
        # Nothing was stored before, so no level is kept and none is reported
        # Described (no UC field) is certain and reported; the UC level is not
        assert report['achieved_level_order'] == 1
        assert [lv['level_name'] for lv in report['levels']] == ['Described']
        assert 'gone' not in response.text
        assert [n['code'] for n in report['notices']] == [
            'maturity_uc_table_unreadable', 'maturity_level_partial',
        ]
        assert report['notices'][0]['params'] == {'tableName': FQN}

        assert db_session.query(MaturitySnapshotDb).filter_by(entity_id=str(asset.id)).count() == 0
        assert fired == []

    def test_get_computes_without_storing_or_firing(self, client, db_session, uc_table, fired):
        _asset_ladder(client, db_session)
        asset = _asset(db_session, description='Orders')

        response = client.get(f'/api/assets/{asset.id}/maturity')

        assert response.status_code == 200, response.text
        assert response.json()['achieved_level_order'] == 2
        assert db_session.query(MaturitySnapshotDb).filter_by(entity_id=str(asset.id)).count() == 0
        assert fired == []

    def test_get_says_it_is_not_stored_and_evaluate_says_it_is(
            self, client, db_session, uc_table, fired):
        _asset_ladder(client, db_session)
        asset = _asset(db_session, description='Orders')

        live = client.get(f'/api/assets/{asset.id}/maturity').json()
        stored = client.post(f'/api/assets/{asset.id}/maturity/evaluate').json()

        assert live['stored'] is False
        assert stored['stored'] is True

    def test_moving_a_level_to_assets_checks_the_order(self, client, db_session):
        _asset_ladder(client, db_session)
        response = client.post('/api/maturity-levels', json={
            'name': 'Products only', 'level_order': 1, 'entity_type': 'all',
        })
        assert response.status_code == 201, response.text
        level_id = response.json()['id']

        # Order 1 is taken by the Asset level 'Described'
        response = client.put(f'/api/maturity-levels/{level_id}', json={'entity_type': 'Asset'})
        assert response.status_code == 409, response.text

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


def _asset_type_id(db, name):
    asset_type = db.query(AssetTypeDb).filter_by(name=name).first()
    if asset_type is None:
        asset_type = AssetTypeDb(name=name)
        db.add(asset_type)
        db.flush()
    return str(asset_type.id)


class TestAssetCreationEvaluation:
    def _create(self, client, db_session, type_name):
        response = client.post('/api/assets', json={
            'name': f'orders-{uuid.uuid4().hex[:6]}',
            'asset_type_id': _asset_type_id(db_session, type_name),
            'platform': 'databricks', 'location': FQN,
            'description': 'Orders placed in the shop',
        })
        assert response.status_code == 201, response.text
        return response.json()['id']

    def _snapshots(self, db_session, asset_id):
        return db_session.query(MaturitySnapshotDb).filter_by(entity_id=asset_id).all()

    def test_creating_a_table_asset_evaluates_it(self, client, db_session, uc_table, fired):
        _asset_ladder(client, db_session)

        asset_id = self._create(client, db_session, 'Table')

        snapshots = self._snapshots(db_session, asset_id)
        assert [s.achieved_level_order for s in snapshots] == [2]
        assert snapshots[0].entity_type == 'Asset'
        assert snapshots[0].evaluated_by == 'test@example.com'
        uc_table.tables.get.assert_called_with(full_name=FQN)
        assert [e['entity_id'] for e in fired] == [FQN]

    def test_creating_another_asset_type_is_not_evaluated(
            self, client, db_session, uc_table, fired):
        _asset_ladder(client, db_session)

        asset_id = self._create(client, db_session, 'Dashboard')

        assert self._snapshots(db_session, asset_id) == []
        uc_table.tables.get.assert_not_called()
        assert fired == []

    def test_creating_a_table_without_asset_levels_is_not_evaluated(
            self, client, db_session, uc_table, fired):
        asset_id = self._create(client, db_session, 'Table')

        assert self._snapshots(db_session, asset_id) == []
        uc_table.tables.get.assert_not_called()
        assert fired == []


_MATURITY_ROUTES = [
    ('get', '/api/assets/{id}/maturity'),
    ('post', '/api/assets/{id}/maturity/evaluate'),
    ('get', '/api/assets/{id}/maturity/history'),
]


class TestAssetMaturityAccess:
    """The asset maturity routes are readable by exactly the users who may read the asset."""

    @pytest.fixture
    def no_assets_feature(self, monkeypatch):
        from src.routes import assets_routes
        monkeypatch.setattr(assets_routes, '_user_has_assets_feature', lambda *a, **k: False)

    @pytest.mark.parametrize('method,path', _MATURITY_ROUTES)
    def test_a_user_who_cannot_read_the_asset_gets_403(
            self, client, db_session, uc_table, no_assets_feature, method, path):
        _asset_ladder(client, db_session)
        asset = _asset(db_session, description='Orders')
        asset_id = str(asset.id)

        response = getattr(client, method)(path.format(id=asset_id))

        assert response.status_code == 403, response.text
        uc_table.tables.get.assert_not_called()
        assert db_session.query(MaturitySnapshotDb).filter_by(entity_id=asset_id).count() == 0

    @pytest.mark.parametrize('method,path', _MATURITY_ROUTES)
    def test_a_user_who_reads_the_asset_through_a_product_gets_200(
            self, client, db_session, uc_table, no_assets_feature, monkeypatch, method, path):
        from src.controller.assets_manager import assets_manager
        monkeypatch.setattr(assets_manager, 'is_asset_accessible', lambda *a, **k: True)
        _asset_ladder(client, db_session)
        asset = _asset(db_session, description='Orders')

        response = getattr(client, method)(path.format(id=asset.id))

        assert response.status_code == 200, response.text


class TestAssetWriteAudit:
    """The audit row says success only once the asset write is committed."""

    @pytest.fixture
    def audited(self, client, monkeypatch):
        calls = []
        audit_manager = client.app.state.audit_manager
        monkeypatch.setattr(audit_manager, 'log_action', lambda **kw: calls.append(kw))
        return calls

    @pytest.fixture
    def failing_commit(self, monkeypatch):
        from src.routes import assets_routes

        def fail(*args, **kwargs):
            raise RuntimeError('commit failed')

        monkeypatch.setattr(assets_routes, '_schedule_maturity_evaluation', fail)

    def test_a_failed_update_commit_is_audited_as_a_failure(
            self, client, db_session, audited, failing_commit):
        asset = _asset(db_session)

        response = client.put(f'/api/assets/{asset.id}', json={'description': 'Orders'})

        assert response.status_code == 500
        assert [(c['action'], c['success']) for c in audited] == [('UPDATE_ASSET', False)]
        assert 'updated_resource_id' not in audited[0]['details']

    def test_a_failed_create_commit_is_audited_as_a_failure(
            self, client, db_session, audited, failing_commit):
        response = client.post('/api/assets', json={
            'name': f'orders-{uuid.uuid4().hex[:6]}',
            'asset_type_id': _asset_type_id(db_session, 'Table'),
            'platform': 'databricks', 'location': FQN,
        })

        assert response.status_code == 500
        assert [(c['action'], c['success']) for c in audited] == [('CREATE_ASSET', False)]
        assert 'created_resource_id' not in audited[0]['details']


class TestAssetMaturityReadsAsTheUser:
    """User-started evaluations read the UC table with the user's token, not the app's."""

    @pytest.fixture
    def user_client(self, monkeypatch, mock_workspace_client):
        from unittest.mock import MagicMock

        from databricks.sdk.errors import PermissionDenied
        from src.common import workspace_client as workspace_client_module

        # The app could not read the table; the user can
        mock_workspace_client.tables.get.side_effect = PermissionDenied('app has no grant')
        user_ws = MagicMock()
        user_ws.tables.get.return_value = TableInfo(full_name=FQN, columns=[
            ColumnInfo(name='id', comment='Order id', type_text='bigint'),
        ])
        monkeypatch.setattr(workspace_client_module, 'get_obo_workspace_client',
                            lambda *a, **k: user_ws)
        return user_ws

    def test_evaluate_reads_the_table_as_the_user(self, client, db_session, user_client, fired):
        _asset_ladder(client, db_session)
        asset = _asset(db_session, description='Orders')

        response = client.post(f'/api/assets/{asset.id}/maturity/evaluate')

        assert response.status_code == 200, response.text
        assert response.json()['achieved_level_order'] == 2
        assert response.json()['notices'] == []
        user_client.tables.get.assert_called_with(full_name=FQN)

    def test_an_asset_write_re_evaluates_as_the_user(
            self, client, db_session, user_client, fired):
        _asset_ladder(client, db_session)
        asset = _asset(db_session)

        response = client.put(f'/api/assets/{asset.id}', json={'description': 'Orders'})

        assert response.status_code == 200, response.text
        snapshots = db_session.query(MaturitySnapshotDb).filter_by(entity_id=str(asset.id)).all()
        assert [s.achieved_level_order for s in snapshots] == [2]
        user_client.tables.get.assert_called_with(full_name=FQN)


class TestAssetMaturityVisibleToUcReaders:
    """Stored maturity results come from the evaluator's UC read: a reader without their
    own UC read of the table gets none of them (#1352 review)."""

    @pytest.fixture
    def tokens(self, monkeypatch):
        """A workspace client per user token: A and C can read the table, B can't."""
        from unittest.mock import MagicMock

        from databricks.sdk.errors import PermissionDenied
        from src.common import workspace_client as workspace_client_module

        readable = TableInfo(full_name=FQN, columns=[
            ColumnInfo(name='id', comment='Order id', type_text='bigint'),
        ])
        clients = {}
        for token, can_read in (('token-a', True), ('token-b', False), ('token-c', True)):
            ws = MagicMock()
            if can_read:
                ws.tables.get.return_value = readable
            else:
                ws.tables.get.side_effect = PermissionDenied('no SELECT on main.sales.orders')
            clients[token] = ws

        def obo(request, *args, **kwargs):
            return clients[request.headers['x-forwarded-access-token']]

        monkeypatch.setattr(workspace_client_module, 'get_obo_workspace_client', obo)
        return clients

    @staticmethod
    def _as(token):
        return {'x-forwarded-access-token': token}

    def _stored_by_a(self, client, db_session):
        _asset_ladder(client, db_session)
        asset = _asset(db_session, description='Orders')
        response = client.post(f'/api/assets/{asset.id}/maturity/evaluate',
                               headers=self._as('token-a'))
        assert response.status_code == 200, response.text
        assert response.json()['achieved_level_order'] == 2
        return asset

    def test_a_reader_without_uc_read_gets_no_history(
            self, client, db_session, tokens, fired):
        asset = self._stored_by_a(client, db_session)

        response = client.get(f'/api/assets/{asset.id}/maturity/history',
                              headers=self._as('token-b'))

        assert response.status_code == 200, response.text
        assert response.json() == []
        tokens['token-b'].tables.get.assert_called_with(full_name=FQN)

    def test_a_reader_with_uc_read_gets_the_history(
            self, client, db_session, tokens, fired):
        asset = self._stored_by_a(client, db_session)

        response = client.get(f'/api/assets/{asset.id}/maturity/history',
                              headers=self._as('token-c'))

        assert response.status_code == 200, response.text
        history = response.json()
        assert [s['achieved_level_order'] for s in history] == [2]

    def test_a_reader_without_uc_read_does_not_get_the_stored_level(
            self, client, db_session, tokens, fired):
        asset = self._stored_by_a(client, db_session)

        for method, path in (('get', 'maturity'), ('post', 'maturity/evaluate')):
            response = getattr(client, method)(f'/api/assets/{asset.id}/{path}',
                                               headers=self._as('token-b'))

            assert response.status_code == 200, response.text
            report = response.json()
            # Only what B's own read proves: level 1 (no UC field), never the stored 2
            assert report['achieved_level_order'] == 1, path
            assert [lv['level_order'] for lv in report['levels']] == [1]
            assert 'Documented columns' not in response.text
            assert [n['code'] for n in report['notices']] == [
                'maturity_uc_table_unreadable', 'maturity_level_partial',
            ]
        snapshots = db_session.query(MaturitySnapshotDb).filter_by(entity_id=str(asset.id))
        assert [s.achieved_level_order for s in snapshots] == [2]

    def test_history_fails_closed_when_the_reader_has_no_client(
            self, client, db_session, tokens, fired, monkeypatch):
        from src.common import workspace_client as workspace_client_module

        asset = self._stored_by_a(client, db_session)

        def broken(*args, **kwargs):
            raise RuntimeError('client could not be built')

        monkeypatch.setattr(workspace_client_module, 'get_obo_workspace_client', broken)
        response = client.get(f'/api/assets/{asset.id}/maturity/history')

        assert response.status_code == 200, response.text
        assert response.json() == []

    def test_history_of_an_asset_without_a_uc_table_needs_no_uc_read(
            self, client, db_session, tokens, fired):
        _asset_ladder(client, db_session)
        asset = _asset(db_session, description='Orders')
        asset.platform = 'snowflake'
        db_session.flush()
        response = client.post(f'/api/assets/{asset.id}/maturity/evaluate',
                               headers=self._as('token-b'))
        assert response.status_code == 200, response.text

        response = client.get(f'/api/assets/{asset.id}/maturity/history',
                              headers=self._as('token-b'))

        assert [s['achieved_level_order'] for s in response.json()] == [1]
        tokens['token-b'].tables.get.assert_not_called()

    def test_the_timeline_change_row_has_no_level(
            self, client, db_session, tokens, fired):
        asset = self._stored_by_a(client, db_session)

        response = client.get(f'/api/entities/Asset/{asset.id}/timeline',
                              params={'filter_type': 'changes'},
                              headers=self._as('token-b'))

        assert response.status_code == 200, response.text
        changes = [e for e in response.json()['timeline']
                   if e['metadata']['action'] == 'MATURITY_CHANGED']
        # The row says the level changed; the level itself stays in the gated history
        assert len(changes) == 1
        assert 'maturity_level' not in changes[0]['content']

    def test_snapshots_stay_gated_by_their_table_after_the_asset_leaves_it(
            self, client, db_session, tokens, fired):
        asset = self._stored_by_a(client, db_session)
        asset.platform = 'snowflake'
        db_session.flush()
        # Evaluated without a UC table now: B's own snapshot
        response = client.post(f'/api/assets/{asset.id}/maturity/evaluate',
                               headers=self._as('token-b'))
        assert response.status_code == 200, response.text

        def history(token):
            response = client.get(f'/api/assets/{asset.id}/maturity/history',
                                  headers=self._as(token))
            assert response.status_code == 200, response.text
            return [s['achieved_level_order'] for s in response.json()]

        # A's snapshot came from main.sales.orders: only its readers see it
        assert history('token-b') == [1]
        assert sorted(history('token-c')) == [1, 2]
        tokens['token-b'].tables.get.assert_called_with(full_name=FQN)

    def test_snapshots_stay_gated_by_their_table_when_the_asset_points_elsewhere(
            self, client, db_session, tokens, fired):
        asset = self._stored_by_a(client, db_session)
        asset.location = 'main.sales.refunds'
        db_session.flush()
        # B can read the new table, not the one A's snapshot was evaluated against
        refunds = TableInfo(full_name='main.sales.refunds', columns=[])

        def get(full_name):
            if full_name == FQN:
                raise NotFound('no SELECT on main.sales.orders')
            return refunds

        tokens['token-b'].tables.get.side_effect = get

        response = client.get(f'/api/assets/{asset.id}/maturity/history',
                              headers=self._as('token-b'))

        assert response.status_code == 200, response.text
        assert response.json() == []
