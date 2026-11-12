"""PUT /api/assets/{id} writes a table or column description to Unity Catalog (#1477).

The write runs as the user (their on-behalf-of client) when the admin setting
is on. A failed write still saves the asset, answers with a coded warning, and
the asset reads as not in sync with Unity Catalog.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.service.sql import StatementState

from src.app import app
from src.common.dependencies import get_settings
from src.db_models.assets import AssetDb, AssetTypeDb

TOKEN = {'x-forwarded-access-token': 'user-token', 'X-Forwarded-Email': 'user@example.com'}


def _type(db, name):
    found = db.query(AssetTypeDb).filter(AssetTypeDb.name == name).first()
    if found is None:
        found = AssetTypeDb(name=name, category='data')
        db.add(found)
        db.flush()
    return found


@pytest.fixture
def settings(test_settings):
    test_settings.UC_DESCRIPTION_WRITEBACK_ENABLED = True
    app.dependency_overrides[get_settings] = lambda: test_settings
    yield test_settings
    app.dependency_overrides.pop(get_settings, None)


@pytest.fixture
def table(db_session):
    row = AssetDb(name='orders', asset_type_id=_type(db_session, 'Table').id,
                  platform='databricks', location='main.sales.orders', description='Old',
                  properties={'owner': 'sales'})
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def column(db_session):
    row = AssetDb(name='order_id', asset_type_id=_type(db_session, 'Column').id,
                  platform='databricks', location='main.sales.orders.order_id')
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def user_ws(monkeypatch):
    """The user's (OBO) workspace client; the statement succeeds unless a test says otherwise."""
    from src.routes import assets_routes

    ws = MagicMock()
    ws.statement_execution.execute_statement.return_value = SimpleNamespace(
        status=SimpleNamespace(state=StatementState.SUCCEEDED, error=None), statement_id='st-1')
    monkeypatch.setattr(assets_routes, 'get_obo_workspace_client', lambda request: ws)
    return ws


def _fail_with(ws, message):
    ws.statement_execution.execute_statement.return_value = SimpleNamespace(
        status=SimpleNamespace(state=StatementState.FAILED,
                               error=SimpleNamespace(message=message)),
        statement_id='st-1')


def _statements(ws):
    return [c.kwargs['statement'] for c in ws.statement_execution.execute_statement.call_args_list]


def _put(client, asset, description, headers=TOKEN):
    response = client.put(f'/api/assets/{asset.id}', json={'description': description},
                          headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


class TestDescriptionWriteback:
    def test_a_table_description_is_written_as_the_user(self, client, settings, table, user_ws):
        body = _put(client, table, 'Orders placed online')

        assert _statements(user_ws) == [
            "COMMENT ON TABLE `main`.`sales`.`orders` IS 'Orders placed online'"]
        assert user_ws.statement_execution.execute_statement.call_args.kwargs[
            'warehouse_id'] == settings.DATABRICKS_WAREHOUSE_ID
        assert body['warnings'] == []
        assert body['description_sync'] is None

    def test_a_column_description_is_written(self, client, settings, column, user_ws):
        _put(client, column, 'Order key')

        assert _statements(user_ws) == [
            "COMMENT ON COLUMN `main`.`sales`.`orders`.`order_id` IS 'Order key'"]

    def test_permission_denied_saves_and_warns(self, client, settings, table, user_ws):
        _fail_with(user_ws, '[INSUFFICIENT_PERMISSIONS] User does not have MODIFY on Table')

        body = _put(client, table, 'Orders placed online')

        assert body['description'] == 'Orders placed online'
        [warning] = body['warnings']
        assert warning['code'] == 'uc_description_permission_denied'
        assert warning['params'] == {'object': 'main.sales.orders'}
        assert body['description_sync']['code'] == 'uc_description_permission_denied'
        read = client.get(f'/api/assets/{table.id}').json()
        assert read['description'] == 'Orders placed online'
        assert read['description_sync']['status'] == 'out_of_sync'
        assert read['properties'] == {'owner': 'sales'}

    def test_a_missing_object_saves_and_warns(self, client, settings, table, user_ws):
        _fail_with(user_ws, '[TABLE_OR_VIEW_NOT_FOUND] The table cannot be found')

        body = _put(client, table, 'Orders placed online')

        assert body['warnings'][0]['code'] == 'uc_description_object_not_found'

    def test_a_later_successful_save_clears_the_warning(self, client, settings, table, user_ws):
        _fail_with(user_ws, 'PERMISSION_DENIED')
        _put(client, table, 'Orders placed online')
        user_ws.statement_execution.execute_statement.return_value = SimpleNamespace(
            status=SimpleNamespace(state=StatementState.SUCCEEDED, error=None),
            statement_id='st-2')

        body = _put(client, table, 'Orders placed online')

        assert body['warnings'] == [] and body['description_sync'] is None
        assert client.get(f'/api/assets/{table.id}').json()['description_sync'] is None

    def test_without_the_user_token_nothing_is_written(self, client, settings, table, user_ws):
        body = _put(client, table, 'Orders placed online', headers={})

        assert body['warnings'][0]['code'] == 'uc_description_user_token_required'
        user_ws.statement_execution.execute_statement.assert_not_called()

    def test_with_the_setting_off_nothing_is_written(self, client, settings, table, user_ws):
        settings.UC_DESCRIPTION_WRITEBACK_ENABLED = False

        body = _put(client, table, 'Orders placed online')

        assert body['warnings'] == [] and body['description_sync'] is None
        user_ws.statement_execution.execute_statement.assert_not_called()

    def test_with_the_setting_off_an_old_mark_is_not_shown(self, client, settings, table,
                                                            user_ws):
        _fail_with(user_ws, 'PERMISSION_DENIED')
        _put(client, table, 'Orders placed online')
        settings.UC_DESCRIPTION_WRITEBACK_ENABLED = False

        assert client.get(f'/api/assets/{table.id}').json()['description_sync'] is None


def _import_csv(client, csv_text, headers=TOKEN):
    response = client.post(
        '/api/assets/bulk/import', headers=headers,
        files={'file': ('assets.csv', csv_text.encode('utf-8'), 'text/csv')},
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestBulkImportWriteback:
    CSV = ('name,asset_type,platform,location,description\n'
           'orders,Table,databricks,main.sales.orders,Orders placed online\n'
           'notes,Table,snowflake,db.s.notes,Not in Unity Catalog\n')

    def test_imported_descriptions_are_written_as_the_user(self, client, settings, table,
                                                          user_ws):
        body = _import_csv(client, self.CSV)

        assert body['updated'] == 1 and body['created'] == 1 and body['errors'] == 0
        assert _statements(user_ws) == [
            "COMMENT ON TABLE `main`.`sales`.`orders` IS 'Orders placed online'"]
        assert all(item['warnings'] == [] for item in body['items'])

    def test_a_failed_write_is_a_row_warning_not_an_error(self, client, settings, table,
                                                         user_ws):
        _fail_with(user_ws, '[INSUFFICIENT_PERMISSIONS] User does not have MODIFY')

        body = _import_csv(client, self.CSV)

        assert body['errors'] == 0 and body['warnings'] == 1
        row = next(i for i in body['items'] if i['name'] == 'orders')
        assert row['action'] == 'update'
        assert [w['code'] for w in row['warnings']] == ['uc_description_permission_denied']
        read = client.get(f'/api/assets/{table.id}').json()
        assert read['description'] == 'Orders placed online'
        assert read['description_sync']['code'] == 'uc_description_permission_denied'

    def test_with_the_setting_off_the_import_writes_nothing(self, client, settings, table,
                                                           user_ws):
        settings.UC_DESCRIPTION_WRITEBACK_ENABLED = False

        body = _import_csv(client, self.CSV)

        assert body['errors'] == 0 and body['warnings'] == 0
        user_ws.statement_execution.execute_statement.assert_not_called()

    def test_an_empty_description_cell_keeps_the_uc_comment(self, client, settings, table,
                                                            user_ws):
        _import_csv(client, 'name,asset_type,platform,location,description\n'
                            'orders,Table,databricks,main.sales.orders,\n')

        user_ws.statement_execution.execute_statement.assert_not_called()

    def test_a_failing_write_step_never_fails_the_row(self, client, settings, table, user_ws,
                                                      monkeypatch):
        from src.controller.uc_description_sync_manager import UcDescriptionSyncManager

        def boom(*args, **kwargs):
            raise RuntimeError('unexpected')

        monkeypatch.setattr(UcDescriptionSyncManager, 'sync_after_update', boom)

        body = _import_csv(client, self.CSV)

        assert body['errors'] == 0 and body['warnings'] == 0
        assert client.get(f'/api/assets/{table.id}').json()['description'] == \
            'Orders placed online'

    def test_an_imported_column_description_updates_the_table_snapshot(
            self, client, settings, db_session, user_ws):
        table = AssetDb(name='orders', asset_type_id=_type(db_session, 'Table').id,
                        platform='databricks', location='main.sales.orders',
                        properties={'schema': {'columns': [
                            {'name': 'order_id', 'description': 'Old'}]}})
        db_session.add(table)
        db_session.flush()

        _import_csv(client, 'name,asset_type,platform,location,description\n'
                            'order_id,Column,databricks,main.sales.orders.order_id,Order key\n')

        db_session.refresh(table)
        assert table.properties['schema']['columns'][0]['description'] == 'Order key'
