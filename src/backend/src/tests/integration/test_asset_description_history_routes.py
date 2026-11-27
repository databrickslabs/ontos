"""GET /api/assets/{id}/description/history and POST .../restore.

Restoring is a normal edit whose history entry has the source ``restore``, so it follows the
Unity Catalog write-back rules of any other edit.
"""
import itertools
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from databricks.sdk.service.sql import StatementState
from sqlalchemy import event

from src.app import app
from src.common.dependencies import get_settings
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.change_log import ChangeLogDb
from src.tests.uc_comment_fakes import reads_back_comment_writes

TOKEN = {'x-forwarded-access-token': 'user-token', 'X-Forwarded-Email': 'user@example.com'}


def _type(db, name):
    found = db.query(AssetTypeDb).filter(AssetTypeDb.name == name).first()
    if found is None:
        found = AssetTypeDb(name=name, category='data')
        db.add(found)
        db.flush()
    return found


def _asset(db, type_name, name, location, description, properties=None):
    row = AssetDb(name=name, asset_type_id=_type(db, type_name).id, platform='databricks',
                  location=location, description=description, properties=properties)
    db.add(row)
    db.flush()
    return row


@pytest.fixture(autouse=True)
def distinct_timestamps():
    """Each change-log entry is a second after the last: SQLite's clock has whole seconds."""
    ticks = itertools.count()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def stamp(mapper, connection, entry):
        entry.timestamp = start + timedelta(seconds=next(ticks))

    event.listen(ChangeLogDb, 'before_insert', stamp)
    yield
    event.remove(ChangeLogDb, 'before_insert', stamp)


@pytest.fixture
def table(db_session):
    return _asset(db_session, 'Table', 'orders', 'main.sales.orders', 'v0')


def _put(client, asset, description):
    response = client.put(f'/api/assets/{asset.id}', json={'description': description},
                          headers=TOKEN)
    assert response.status_code == 200, response.text
    return response.json()


def _history(client, asset, **params):
    response = client.get(f'/api/assets/{asset.id}/description/history', params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _restore(client, asset, entry_id, version=None, headers=TOKEN):
    body = {'entry_id': entry_id}
    if version:
        body['version'] = version
    return client.post(f'/api/assets/{asset.id}/description/restore', json=body, headers=headers)


@pytest.fixture
def writeback_on(test_settings):
    test_settings.UC_DESCRIPTION_WRITEBACK_ENABLED = True
    app.dependency_overrides[get_settings] = lambda: test_settings
    yield test_settings
    app.dependency_overrides.pop(get_settings, None)


@pytest.fixture
def user_ws(monkeypatch):
    from src.routes import assets_routes

    ws = MagicMock()
    ws.statement_execution.execute_statement.return_value = SimpleNamespace(
        status=SimpleNamespace(state=StatementState.SUCCEEDED, error=None), statement_id='st-1')
    ws.tables.get.return_value = SimpleNamespace(
        table_type=None, comment=None, columns=[SimpleNamespace(name='order_id', comment=None)])
    reads_back_comment_writes(ws)
    monkeypatch.setattr(assets_routes, 'get_obo_workspace_client', lambda request: ws)
    return ws


class TestHistory:
    def test_the_changes_come_newest_first_with_who_what_and_where_from(self, client, table):
        _put(client, table, 'v1')
        _put(client, table, 'v2')

        body = _history(client, table)

        assert body['asset_id'] == str(table.id) and body['total'] == 2
        newest, oldest = body['items']
        assert (newest['before'], newest['after'], newest['source']) == ('v1', 'v2', 'manual')
        assert (oldest['before'], oldest['after']) == ('v0', 'v1')
        assert newest['username'] and newest['timestamp'] and newest['object_type'] == 'table'

    def test_it_pages(self, client, table):
        for text in ('v1', 'v2', 'v3'):
            _put(client, table, text)

        first = _history(client, table, limit=2)
        rest = _history(client, table, skip=2, limit=2)

        assert first['total'] == 3 and [i['after'] for i in first['items']] == ['v3', 'v2']
        assert [i['after'] for i in rest['items']] == ['v1']

    def test_an_asset_without_changes_has_an_empty_history(self, client, table):
        assert _history(client, table) == {'asset_id': str(table.id), 'total': 0, 'items': []}

    def test_only_the_assets_own_changes_are_listed(self, client, db_session, table):
        other = _asset(db_session, 'Table', 'items', 'main.sales.items', 'x0')
        _put(client, other, 'x1')
        _put(client, table, 'v1')

        assert [i['after'] for i in _history(client, table)['items']] == ['v1']

    def test_an_unknown_asset_is_not_found(self, client):
        response = client.get(
            '/api/assets/00000000-0000-0000-0000-000000000000/description/history')

        assert response.status_code == 404

    def test_a_reset_is_listed_with_its_source(self, client, table, monkeypatch):
        from src.routes import assets_routes

        ws = MagicMock()
        ws.tables.get.return_value = SimpleNamespace(
            table_type=None, comment='From UC', columns=[])
        monkeypatch.setattr(assets_routes, 'get_obo_workspace_client', lambda request: ws)
        assert client.post(f'/api/assets/{table.id}/description/reset-to-uc',
                           headers=TOKEN).status_code == 200

        [entry] = _history(client, table)['items']

        assert (entry['source'], entry['before'], entry['after']) == ('uc_reset', 'v0', 'From UC')


class TestRestore:
    def test_the_text_an_entry_set_is_restored_as_a_normal_edit(self, client, table):
        _put(client, table, 'v1')
        _put(client, table, 'v2')
        first = _history(client, table)['items'][1]  # v0 -> v1

        response = _restore(client, table, first['id'])

        assert response.status_code == 200, response.text
        assert response.json()['description'] == 'v1' and response.json()['warnings'] == []
        newest = _history(client, table)['items'][0]
        assert (newest['source'], newest['before'], newest['after']) == ('restore', 'v2', 'v1')
        assert newest['restored_from'] == first['id']
        assert client.get(f'/api/assets/{table.id}').json()['description'] == 'v1'

    def test_the_text_an_entry_replaced_is_restored_with_version_before(self, client, table):
        _put(client, table, 'v1')
        entry = _history(client, table)['items'][0]  # v0 -> v1

        response = _restore(client, table, entry['id'], 'before')

        assert response.json()['description'] == 'v0'

    def test_the_previous_text_of_a_first_description_is_refused(
            self, client, db_session, writeback_on, user_ws):
        asset = _asset(db_session, 'Table', 't', 'main.sales.t', None)
        _put(client, asset, 'v1')
        entry = _history(client, asset)['items'][0]  # nothing -> v1
        user_ws.statement_execution.execute_statement.reset_mock()

        response = _restore(client, asset, entry['id'], 'before')

        assert response.status_code == 400
        assert response.json()['detail']['code'] == 'description_restore_no_previous_text'
        user_ws.statement_execution.execute_statement.assert_not_called()

    def test_restoring_the_current_text_changes_nothing(self, client, table):
        _put(client, table, 'v1')
        entry = _history(client, table)['items'][0]

        assert _restore(client, table, entry['id']).status_code == 200

        assert _history(client, table)['total'] == 1

    def test_an_unknown_entry_is_a_coded_404(self, client, table):
        response = _restore(client, table, 'no-such-entry')

        assert response.status_code == 404
        assert response.json()['detail']['code'] == 'description_history_entry_not_found'

    def test_an_entry_of_another_asset_is_not_restorable(self, client, db_session, table):
        other = _asset(db_session, 'Table', 'items', 'main.sales.items', 'x0')
        _put(client, other, 'x1')
        entry = _history(client, other)['items'][0]

        response = _restore(client, table, entry['id'])

        assert response.status_code == 404
        assert response.json()['detail']['code'] == 'description_history_entry_not_found'

    def test_with_write_back_on_the_restored_text_goes_to_unity_catalog(
            self, client, writeback_on, table, user_ws):
        user_ws.tables.get.return_value.comment = 'v0'  # Unity Catalog still has the first text
        _put(client, table, 'v1')
        calls = user_ws.statement_execution.execute_statement.call_args_list
        written_by_the_edit = len(calls)
        entry = _history(client, table)['items'][0]  # v0 -> v1

        response = _restore(client, table, entry['id'], 'before')

        assert response.status_code == 200, response.text
        assert response.json()['warnings'] == []
        assert [c.kwargs['statement'] for c in calls[written_by_the_edit:]] == [
            "COMMENT ON TABLE `main`.`sales`.`orders` IS 'v0'"]

    def test_a_comment_someone_else_wrote_is_kept_and_the_restore_warns(
            self, client, writeback_on, table, user_ws):
        _put(client, table, 'v1')
        entry = _history(client, table)['items'][0]
        user_ws.tables.get.side_effect = None
        user_ws.tables.get.return_value = SimpleNamespace(
            table_type=None, comment='Written in Unity Catalog', columns=[])
        written_before = len(user_ws.statement_execution.execute_statement.call_args_list)

        response = _restore(client, table, entry['id'], 'before')

        assert response.status_code == 200
        assert response.json()['description'] == 'v0'
        assert response.json()['warnings'][0]['code'] == 'uc_description_existing_comment'
        assert len(user_ws.statement_execution.execute_statement.call_args_list) == written_before

    def test_a_column_restore_updates_its_table_snapshot_once_in_unity_catalog(
            self, client, writeback_on, db_session, user_ws):
        table = _asset(db_session, 'Table', 'orders', 'main.sales.orders', None, properties={
            'schema': {'columns': [{'name': 'order_id', 'description': 'k0'}]}})
        column = _asset(db_session, 'Column', 'order_id', 'main.sales.orders.order_id', 'k0')
        user_ws.tables.get.return_value.columns[0].comment = 'k0'
        _put(client, column, 'k1')
        entry = _history(client, column)['items'][0]

        response = _restore(client, column, entry['id'], 'before')

        assert response.status_code == 200 and response.json()['description'] == 'k0'
        db_session.refresh(table)
        assert table.properties['schema']['columns'][0]['description'] == 'k0'


class TestReadAccess:
    """The history is as readable as the asset: the data-product scoping of GET /assets/{id}."""

    @pytest.fixture
    def reader(self, client, mock_test_user):
        """The test user acts as a role with ``assets`` READ_ONLY (no write access)."""
        from src.common.features import FeatureAccessLevel
        from src.models.settings import AppRoleCreate

        settings_manager = app.state.settings_manager
        role = settings_manager.get_app_role_by_name('Assets history reader')
        if role is None:
            role = settings_manager.create_app_role(AppRoleCreate(
                name='Assets history reader',
                feature_permissions={'assets': FeatureAccessLevel.READ_ONLY}))
        settings_manager.set_applied_role_override_for_user(
            mock_test_user.email, str(role.id), caller_is_admin=True)
        yield
        settings_manager.set_applied_role_override_for_user(mock_test_user.email, None)

    def _linked(self, monkeypatch, asset, linked):
        from src.controller.assets_manager import AssetsManager

        monkeypatch.setattr(
            AssetsManager, 'is_asset_accessible',
            lambda self, db, *, asset_id, data_products_manager, is_admin: linked)

    def test_an_asset_outside_the_users_data_products_is_refused_like_the_asset(
            self, client, table, reader, monkeypatch):
        self._linked(monkeypatch, table, False)
        asset = client.get(f'/api/assets/{table.id}')

        history = client.get(f'/api/assets/{table.id}/description/history')

        assert asset.status_code == 403
        assert history.status_code == 403
        assert history.json() == asset.json()

    def test_an_asset_of_an_accessible_data_product_is_readable(
            self, client, table, reader, monkeypatch):
        self._linked(monkeypatch, table, True)

        history = client.get(f'/api/assets/{table.id}/description/history')

        assert history.status_code == 200, history.text

    def test_a_restore_checks_the_read_access_too(self, client, table, monkeypatch):
        """Even where the write permission is there, the same check runs first."""
        from src.routes import assets_routes

        calls = []

        def refuse(request, db, current_user, manager, asset_id):
            calls.append(asset_id)
            raise HTTPException(status_code=403, detail='refused like GET /assets/{id}')

        monkeypatch.setattr(assets_routes, '_ensure_asset_readable', refuse)

        response = _restore(client, table, 'any-entry')

        assert response.status_code == 403
        assert response.json()['detail'] == 'refused like GET /assets/{id}'
        assert calls == [table.id]
