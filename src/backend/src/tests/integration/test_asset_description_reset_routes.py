"""Description history and "use the Unity Catalog comment" for table, view and column assets.

Every change of a table, view or column description is one ``description_changed`` entry
in the change log (before, after, source). ``POST /api/assets/{id}/description/reset-to-uc``
replaces the Ontos description with the Unity Catalog comment, read as the user.
"""
import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.errors import NotFound, PermissionDenied

from src.app import app
from src.common.dependencies import get_settings
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.change_log import ChangeLogDb

TOKEN = {'x-forwarded-access-token': 'user-token', 'X-Forwarded-Email': 'user@example.com'}


def _type(db, name):
    found = db.query(AssetTypeDb).filter(AssetTypeDb.name == name).first()
    if found is None:
        found = AssetTypeDb(name=name, category='data')
        db.add(found)
        db.flush()
    return found


def _asset(db, type_name, name, location, description, platform='databricks', properties=None):
    row = AssetDb(name=name, asset_type_id=_type(db, type_name).id, platform=platform,
                  location=location, description=description, properties=properties)
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def table(db_session):
    return _asset(db_session, 'Table', 'orders', 'main.sales.orders', 'Old',
                  properties={'owner': 'sales', 'schema': {'columns': [
                      {'name': 'order_id', 'description': 'Old key'}]}})


@pytest.fixture
def column(db_session):
    return _asset(db_session, 'Column', 'order_id', 'main.sales.orders.order_id', 'Old key')


def _uc_info(comment=None, columns=None, table_type=None):
    columns = {'order_id': None} if columns is None else columns
    return SimpleNamespace(
        table_type=table_type, comment=comment,
        columns=[SimpleNamespace(name=n, comment=c) for n, c in columns.items()])


@pytest.fixture
def user_ws(monkeypatch):
    """The user's (OBO) workspace client; ``ws.tables.get.return_value`` is what UC holds."""
    from src.routes import assets_routes

    ws = MagicMock()
    ws.tables.get.return_value = _uc_info()
    monkeypatch.setattr(assets_routes, 'get_obo_workspace_client', lambda request: ws)
    return ws


@pytest.fixture
def no_update(monkeypatch):
    """Fails the test if a refused reset saves the asset (a failed request is rolled back, so
    the stored description can't be read afterwards)."""
    from src.controller.assets_manager import AssetsManager

    def refused(*args, **kwargs):
        raise AssertionError('the asset was saved')

    monkeypatch.setattr(AssetsManager, 'update_asset', refused)


@pytest.fixture
def writeback_on(test_settings):
    test_settings.UC_DESCRIPTION_WRITEBACK_ENABLED = True
    app.dependency_overrides[get_settings] = lambda: test_settings
    yield test_settings
    app.dependency_overrides.pop(get_settings, None)


def _history(db, asset):
    """The ``description_changed`` entries of an asset, oldest first, as dicts."""
    entries = db.query(ChangeLogDb).filter(
        ChangeLogDb.entity_type == 'asset', ChangeLogDb.entity_id == str(asset.id),
        ChangeLogDb.action == 'description_changed',
    ).order_by(ChangeLogDb.timestamp, ChangeLogDb.id).all()
    return [{**json.loads(e.details_json), 'username': e.username} for e in entries]


def _put(client, asset, description):
    response = client.put(f'/api/assets/{asset.id}', json={'description': description},
                          headers=TOKEN)
    assert response.status_code == 200, response.text
    return response.json()


def _reset(client, asset, headers=TOKEN, **body):
    return client.post(f'/api/assets/{asset.id}/description/reset-to-uc', headers=headers,
                       json=body or None)


class TestDescriptionHistory:
    def test_an_edit_is_logged_with_before_after_and_source(self, client, db_session, table):
        _put(client, table, 'Orders placed online')

        [entry] = _history(db_session, table)
        assert (entry['before'], entry['after'], entry['source']) == (
            'Old', 'Orders placed online', 'manual')
        assert entry['object_type'] == 'table' and entry['location'] == 'main.sales.orders'
        assert entry['username']

    def test_a_save_that_keeps_the_description_logs_nothing(self, client, db_session, table):
        _put(client, table, 'Old')

        assert _history(db_session, table) == []

    def test_a_save_without_a_description_logs_nothing(self, client, db_session, table):
        response = client.put(f'/api/assets/{table.id}', json={'name': 'orders v2'}, headers=TOKEN)
        assert response.status_code == 200, response.text

        assert _history(db_session, table) == []

    def test_an_emptied_description_is_logged(self, client, db_session, table):
        _put(client, table, '')

        [entry] = _history(db_session, table)
        assert (entry['before'], entry['after']) == ('Old', None)

    @pytest.mark.parametrize('type_name,location', [
        ('Column', 'main.sales.orders.order_id'), ('View', 'main.sales.v_orders')])
    def test_columns_and_views_are_tracked(self, client, db_session, type_name, location):
        asset = _asset(db_session, type_name, 'x', location, None)

        _put(client, asset, 'New')

        [entry] = _history(db_session, asset)
        assert entry['object_type'] == type_name.lower()
        assert (entry['before'], entry['after']) == (None, 'New')

    def test_other_asset_types_are_not_tracked(self, client, db_session):
        asset = _asset(db_session, 'Dashboard', 'sales', 'https://bi/sales', 'Old')

        _put(client, asset, 'New')

        assert _history(db_session, asset) == []

    def test_a_new_asset_logs_its_description(self, client, db_session):
        response = client.post('/api/assets', headers=TOKEN, json={
            'name': 'orders', 'asset_type_id': str(_type(db_session, 'Table').id),
            'platform': 'databricks', 'location': 'main.sales.orders', 'description': 'Orders'})
        assert response.status_code == 201, response.text
        asset = db_session.get(AssetDb, uuid.UUID(response.json()['id']))

        [entry] = _history(db_session, asset)
        assert (entry['before'], entry['after'], entry['source']) == (None, 'Orders', 'manual')

    def test_a_new_asset_without_a_description_logs_nothing(self, client, db_session):
        response = client.post('/api/assets', headers=TOKEN, json={
            'name': 'orders', 'asset_type_id': str(_type(db_session, 'Table').id)})
        assert response.status_code == 201, response.text

        created = db_session.get(AssetDb, uuid.UUID(response.json()['id']))
        assert _history(db_session, created) == []

    def test_a_failure_to_log_fails_the_save_instead_of_dropping_the_entry(
            self, client, table, monkeypatch):
        from src.controller import asset_description_history as history

        def failing(*args, **kwargs):
            raise RuntimeError('change log down')

        monkeypatch.setattr(history.change_log_manager, 'log_change_with_details', failing)

        response = client.put(f'/api/assets/{table.id}', json={'description': 'New'},
                              headers=TOKEN)

        # Nothing is kept: the request's session is rolled back (a 5xx), history and change
        assert response.status_code == 500

    def test_a_csv_import_logs_the_descriptions_it_sets(self, client, db_session, table):
        csv_text = ('name,asset_type,platform,location,description\n'
                    'orders,Table,databricks,main.sales.orders,From the file\n'
                    'items,Table,databricks,main.sales.items,New table\n')

        response = client.post('/api/assets/bulk/import', headers=TOKEN, files={
            'file': ('assets.csv', csv_text.encode('utf-8'), 'text/csv')})

        assert response.status_code == 200, response.text
        [updated] = _history(db_session, table)
        assert (updated['before'], updated['after'], updated['source']) == (
            'Old', 'From the file', 'bulk_import')
        items = db_session.query(AssetDb).filter(AssetDb.location == 'main.sales.items').one()
        [created] = _history(db_session, items)
        assert (created['before'], created['after']) == (None, 'New table')


class TestResetToUc:
    def test_the_search_index_is_updated_once_for_the_reset_asset(
            self, client, table, user_ws, monkeypatch):
        from src.controller.assets_manager import AssetsManager

        upserts = []
        monkeypatch.setattr(
            AssetsManager, '_notify_index_upsert', lambda self, item: upserts.append(item))
        user_ws.tables.get.return_value = _uc_info('Orders placed online')

        assert _reset(client, table).status_code == 200

        assert len(upserts) == 1

    def test_unity_catalog_is_read_before_the_row_is_locked(
            self, client, table, user_ws, monkeypatch):
        from sqlalchemy.orm import Query

        events = []
        lock = Query.with_for_update

        def recording_lock(query, *args, **kwargs):
            events.append('lock')
            return lock(query, *args, **kwargs)

        def recording_read(*args, **kwargs):
            events.append('uc_read')
            return _uc_info('From UC')

        monkeypatch.setattr(Query, 'with_for_update', recording_lock)
        user_ws.tables.get.side_effect = recording_read

        assert _reset(client, table).status_code == 200

        # The slow read is done before the lock is taken (and the lock comes once)
        assert events[:2] == ['uc_read', 'lock'] and events.count('uc_read') == 1

    def test_the_uc_comment_replaces_the_description(self, client, db_session, table, user_ws):
        user_ws.tables.get.return_value = _uc_info('Orders placed online')

        response = _reset(client, table)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body['changed'] is True and body['warnings'] == []
        assert (body['previous_description'], body['description']) == (
            'Old', 'Orders placed online')
        assert client.get(f'/api/assets/{table.id}').json()['description'] == (
            'Orders placed online')
        user_ws.tables.get.assert_called_once_with(full_name='main.sales.orders')
        [entry] = _history(db_session, table)
        assert (entry['before'], entry['after'], entry['source']) == (
            'Old', 'Orders placed online', 'uc_reset')

    def test_it_reads_as_the_user_and_writes_nothing_to_uc(
            self, client, writeback_on, table, user_ws):
        user_ws.tables.get.return_value = _uc_info('Orders placed online')

        assert _reset(client, table).status_code == 200

        user_ws.statement_execution.execute_statement.assert_not_called()

    def test_it_works_with_the_writeback_setting_off(self, client, test_settings, table, user_ws):
        assert not test_settings.UC_DESCRIPTION_WRITEBACK_ENABLED
        user_ws.tables.get.return_value = _uc_info('From UC')

        assert _reset(client, table).json()['changed'] is True

    def test_a_column_is_reset_from_its_own_comment_and_the_table_snapshot_follows(
            self, client, db_session, table, column, user_ws):
        user_ws.tables.get.return_value = _uc_info(
            'Orders', columns={'order_id': 'Order key', 'other': 'x'})

        response = _reset(client, column)

        assert response.status_code == 200, response.text
        assert response.json()['description'] == 'Order key'
        assert response.json()['target'] == 'main.sales.orders.order_id'
        db_session.refresh(table)
        assert table.description == 'Old'
        assert table.properties['schema']['columns'][0]['description'] == 'Order key'
        [entry] = _history(db_session, column)
        assert entry['object_type'] == 'column' and entry['source'] == 'uc_reset'

    def test_a_not_in_sync_mark_is_cleared(self, client, db_session, writeback_on, table, user_ws):
        table.properties = {**table.properties, 'uc_description_sync': {
            'code': 'uc_description_existing_comment', 'message': 'm', 'params': {},
            'agreed': 'Old'}}
        db_session.flush()
        assert client.get(f'/api/assets/{table.id}').json()['description_sync'] is not None
        user_ws.tables.get.return_value = _uc_info('From UC')

        assert _reset(client, table).status_code == 200

        read = client.get(f'/api/assets/{table.id}').json()
        assert read['description_sync'] is None and read['description'] == 'From UC'
        db_session.refresh(table)
        assert 'uc_description_sync' not in table.properties
        assert table.properties['owner'] == 'sales'

    def test_an_empty_uc_comment_keeps_the_description_and_warns(
            self, client, db_session, table, user_ws):
        user_ws.tables.get.return_value = _uc_info(None)

        response = _reset(client, table)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body['changed'] is False and body['description'] == 'Old'
        [warning] = body['warnings']
        assert warning['code'] == 'uc_description_empty'
        assert warning['params'] == {'object': 'main.sales.orders'}
        assert client.get(f'/api/assets/{table.id}').json()['description'] == 'Old'
        assert _history(db_session, table) == []

    def test_an_empty_uc_comment_on_an_empty_description_is_no_warning(
            self, client, db_session, user_ws):
        asset = _asset(db_session, 'Table', 't', 'main.sales.t', None)

        body = _reset(client, asset).json()

        assert body['changed'] is False and body['warnings'] == []

    def test_a_description_equal_to_the_comment_changes_nothing(
            self, client, db_session, table, user_ws):
        user_ws.tables.get.return_value = _uc_info('Old  \r\n')  # as UC may store it

        body = _reset(client, table).json()

        assert body['changed'] is False and body['warnings'] == []
        assert _history(db_session, table) == []

    def test_the_confirmed_comment_must_still_be_the_one_in_uc(
            self, client, table, user_ws, no_update):
        user_ws.tables.get.return_value = _uc_info('Changed meanwhile')

        response = _reset(client, table, expected_uc_comment='What the dialog showed')

        assert response.status_code == 409
        assert response.json()['detail']['code'] == 'uc_reset_uc_changed'

    def test_the_confirmed_comment_that_still_holds_is_applied(self, client, table, user_ws):
        user_ws.tables.get.return_value = _uc_info('From UC')

        response = _reset(client, table, expected_uc_comment='From UC')

        assert response.status_code == 200 and response.json()['changed'] is True

    def test_without_the_user_token_nothing_is_read_as_the_app(self, client, table, user_ws):
        response = _reset(client, table, headers={'X-Forwarded-Email': 'user@example.com'})

        assert response.status_code == 403
        assert response.json()['detail']['code'] == 'user_token_required'
        user_ws.tables.get.assert_not_called()

    @pytest.mark.parametrize('error,status,code', [
        (PermissionDenied('no SELECT'), 403, 'uc_reset_permission_denied'),
        (NotFound('gone'), 404, 'uc_reset_object_not_found'),
        (RuntimeError('boom'), 502, 'uc_reset_unavailable'),
    ])
    def test_a_comment_that_cannot_be_read_is_a_coded_error(
            self, client, table, user_ws, no_update, error, status, code):
        user_ws.tables.get.side_effect = error

        response = _reset(client, table)

        assert response.status_code == status, response.text
        detail = response.json()['detail']
        assert detail['code'] == code and detail['params'] == {'object': 'main.sales.orders'}
        assert 'boom' not in response.text

    def test_a_column_missing_from_the_table_is_not_found(self, client, column, user_ws):
        user_ws.tables.get.return_value = _uc_info('x', columns={'other': 'y'})

        response = _reset(client, column)

        assert response.status_code == 404
        assert response.json()['detail']['code'] == 'uc_reset_object_not_found'

    def test_a_metric_view_is_refused(self, client, table, user_ws):
        user_ws.tables.get.return_value = _uc_info('x', table_type='METRIC_VIEW')

        response = _reset(client, table)

        assert response.status_code == 409
        assert response.json()['detail']['code'] == 'uc_reset_metric_view'

    def test_a_metric_view_asset_is_refused_without_reading_uc(self, client, db_session, user_ws):
        asset = _asset(db_session, 'Metric View', 'mv', 'main.sales.mv', 'Old')

        response = _reset(client, asset)

        assert response.status_code == 409
        user_ws.tables.get.assert_not_called()

    @pytest.mark.parametrize('type_name,platform,location', [
        ('Dashboard', 'databricks', 'main.sales.d'), ('Table', 'snowflake', 'db.s.t'),
        ('Table', 'databricks', 'only.two')])
    def test_other_assets_are_not_applicable(
            self, client, db_session, user_ws, type_name, platform, location):
        asset = _asset(db_session, type_name, 'x', location, 'Old', platform=platform)

        response = _reset(client, asset)

        assert response.status_code == 400
        assert response.json()['detail']['code'] == 'uc_reset_not_applicable'
        user_ws.tables.get.assert_not_called()

    def test_an_unknown_asset_is_not_found(self, client, user_ws):
        response = client.post(
            '/api/assets/00000000-0000-0000-0000-000000000000/description/reset-to-uc',
            headers=TOKEN)

        assert response.status_code == 404


class TestUcCommentPreview:
    def test_it_shows_both_texts(self, client, table, user_ws):
        user_ws.tables.get.return_value = _uc_info('From UC')

        response = client.get(f'/api/assets/{table.id}/description/uc-comment', headers=TOKEN)

        assert response.status_code == 200, response.text
        assert response.json() == {
            'asset_id': str(table.id), 'target': 'main.sales.orders', 'object_type': 'table',
            'description': 'Old', 'uc_comment': 'From UC', 'in_sync': False, 'table_type': None}

    def test_equal_texts_are_in_sync(self, client, table, user_ws):
        user_ws.tables.get.return_value = _uc_info('Old')

        response = client.get(f'/api/assets/{table.id}/description/uc-comment', headers=TOKEN)

        assert response.json()['in_sync'] is True

    def test_without_the_token_it_is_a_coded_403(self, client, table, user_ws):
        response = client.get(f'/api/assets/{table.id}/description/uc-comment')

        assert response.status_code == 403
        assert response.json()['detail']['code'] == 'user_token_required'
        user_ws.tables.get.assert_not_called()

    def test_a_table_without_select_is_a_coded_403(self, client, table, user_ws):
        user_ws.tables.get.side_effect = PermissionDenied('no')

        response = client.get(f'/api/assets/{table.id}/description/uc-comment', headers=TOKEN)

        assert response.status_code == 403
        assert response.json()['detail']['code'] == 'uc_reset_permission_denied'
