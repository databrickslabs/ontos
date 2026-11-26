"""Drift of the descriptions of a table and its columns from Unity Catalog, and reset of the
selected ones in one request.

Unity Catalog is read as the user, on demand, with one ``tables.get`` for the table and all its
columns. The baseline (what Unity Catalog held when Ontos last saw it) is an internal property.
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.errors import PermissionDenied
from databricks.sdk.service.sql import StatementState

from src.app import app
from src.common.dependencies import get_settings
from src.controller.uc_description_baseline import baseline_of, make_baseline
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.change_log import ChangeLogDb
from src.models.assets import DESCRIPTION_BASELINE_PROPERTY
from src.tests.uc_comment_fakes import reads_back_comment_writes

TOKEN = {'x-forwarded-access-token': 'user-token', 'X-Forwarded-Email': 'user@example.com'}
TABLE = 'main.sales.orders'


def _type(db, name):
    found = db.query(AssetTypeDb).filter(AssetTypeDb.name == name).first()
    if found is None:
        found = AssetTypeDb(name=name, category='data')
        db.add(found)
        db.flush()
    return found


def _asset(db, type_name, location, description, baseline=None, platform='databricks'):
    properties = {DESCRIPTION_BASELINE_PROPERTY: make_baseline(baseline)} if baseline else None
    row = AssetDb(name=location.split('.')[-1], asset_type_id=_type(db, type_name).id,
                  platform=platform, location=location, description=description,
                  properties=properties)
    db.add(row)
    db.flush()
    return row


def _info(comment, columns, table_type=None):
    return SimpleNamespace(
        table_type=table_type, comment=comment,
        columns=[SimpleNamespace(name=n, comment=c) for n, c in columns.items()])


@pytest.fixture
def user_ws(monkeypatch):
    from src.routes import assets_routes

    ws = MagicMock()
    ws.tables.get.return_value = _info(None, {})
    monkeypatch.setattr(assets_routes, 'get_obo_workspace_client', lambda request: ws)
    return ws


@pytest.fixture
def writeback_on(test_settings):
    test_settings.UC_DESCRIPTION_WRITEBACK_ENABLED = True
    app.dependency_overrides[get_settings] = lambda: test_settings
    yield test_settings
    app.dependency_overrides.pop(get_settings, None)


@pytest.fixture
def tree(db_session):
    """A table with two Column assets; ``baseline`` is what UC held when Ontos last saw it."""
    table = _asset(db_session, 'Table', TABLE, 'Orders (Ontos)', baseline='Orders (UC)')
    key = _asset(db_session, 'Column', f'{TABLE}.order_id', 'Key (Ontos)', baseline='Key (UC)')
    note = _asset(db_session, 'Column', f'{TABLE}.note', 'Note (Ontos)')
    return SimpleNamespace(table=table, key=key, note=note)


def _drift(client, asset, headers=TOKEN):
    return client.get(f'/api/assets/{asset.id}/description/drift', headers=headers)


def _fields(response):
    return {f['name']: f for f in response.json()['fields']}


class TestDrift:
    def test_one_read_compares_the_table_and_its_columns(self, client, tree, user_ws):
        user_ws.tables.get.return_value = _info(
            'Orders (UC)', {'order_id': 'Key (UC)', 'note': 'Note (UC)', 'extra': 'x'})

        response = _drift(client, tree.table)

        assert response.status_code == 200, response.text
        user_ws.tables.get.assert_called_once_with(full_name=TABLE)
        body = response.json()
        assert body['target'] == TABLE and len(body['fields']) == 3
        fields = _fields(response)
        assert fields['orders']['object_type'] == 'table'
        assert (fields['orders']['differs'], fields['orders']['changed_in_uc']) == (True, False)
        assert fields['orders']['baseline_known'] is True
        assert fields['order_id']['uc_comment'] == 'Key (UC)'
        # No baseline recorded: it can differ, but a change in Unity Catalog can't be told
        assert (fields['note']['differs'], fields['note']['baseline_known'],
                fields['note']['changed_in_uc']) == (True, False, False)

    def test_a_comment_changed_in_unity_catalog_since_the_baseline_is_flagged(
            self, client, tree, user_ws):
        user_ws.tables.get.return_value = _info(
            'Orders (rewritten in UC)', {'order_id': 'Key (UC)', 'note': None})

        fields = _fields(_drift(client, tree.table))

        assert fields['orders']['changed_in_uc'] is True
        assert fields['orders']['baseline_text'] == 'Orders (UC)'
        assert fields['order_id']['changed_in_uc'] is False

    def test_a_comment_changed_in_unity_catalog_is_settled_by_matching_the_text(
            self, client, db_session, user_ws):
        # UC changed since the baseline, then the user edited the Ontos text to the new comment
        # (write-back off: the baseline stays old): nothing is left to flag, compare or reset
        table = _asset(db_session, 'Table', TABLE, 'Orders (new UC)', baseline='Orders (old UC)')
        user_ws.tables.get.return_value = _info('Orders (new UC)', {})

        field = _fields(_drift(client, table))['orders']

        assert (field['differs'], field['changed_in_uc']) == (False, False)

    def test_the_next_change_in_unity_catalog_is_flagged_again_after_settling(
            self, client, db_session, user_ws):
        table = _asset(db_session, 'Table', TABLE, 'Orders (new UC)', baseline='Orders (old UC)')
        user_ws.tables.get.return_value = _info('Orders (newer UC)', {})

        field = _fields(_drift(client, table))['orders']

        assert (field['differs'], field['changed_in_uc']) == (True, True)

    def test_matching_texts_do_not_differ(self, client, db_session, user_ws):
        table = _asset(db_session, 'Table', TABLE, 'Same', baseline='Same')
        user_ws.tables.get.return_value = _info('Same \r\n', {})

        field = _fields(_drift(client, table))['orders']

        assert (field['differs'], field['changed_in_uc']) == (False, False)

    def test_a_column_asset_is_compared_alone_with_one_read_of_its_table(
            self, client, tree, user_ws):
        user_ws.tables.get.return_value = _info('T', {'order_id': 'Key (UC changed)'})

        response = _drift(client, tree.key)

        assert response.status_code == 200, response.text
        user_ws.tables.get.assert_called_once_with(full_name=TABLE)
        [field] = response.json()['fields']
        assert field['object_type'] == 'column' and field['changed_in_uc'] is True

    def test_a_column_that_is_gone_from_unity_catalog_is_reported_not_compared(
            self, client, tree, user_ws):
        user_ws.tables.get.return_value = _info('Orders (UC)', {'order_id': 'Key (UC)'})

        field = _fields(_drift(client, tree.table))['note']

        assert field['missing_in_uc'] is True
        assert (field['differs'], field['changed_in_uc']) == (False, False)

    def test_only_the_columns_of_this_table_are_listed(self, client, db_session, tree, user_ws):
        _asset(db_session, 'Column', 'main.sales.orders_archive.id', 'Other table')
        _asset(db_session, 'Column', 'main.sales.orders.x', 'Other platform', platform='snowflake')
        user_ws.tables.get.return_value = _info('T', {})

        names = set(_fields(_drift(client, tree.table)))

        assert names == {'orders', 'order_id', 'note'}

    def test_without_the_user_token_unity_catalog_is_not_read(self, client, tree, user_ws):
        response = _drift(client, tree.table, headers={'X-Forwarded-Email': 'user@example.com'})

        assert response.status_code == 403
        assert response.json()['detail']['code'] == 'user_token_required'
        user_ws.tables.get.assert_not_called()

    def test_a_table_without_select_is_a_coded_403(self, client, tree, user_ws):
        user_ws.tables.get.side_effect = PermissionDenied('no')

        response = _drift(client, tree.table)

        assert response.status_code == 403
        assert response.json()['detail']['code'] == 'uc_reset_permission_denied'

    def test_a_metric_view_is_refused(self, client, tree, user_ws):
        user_ws.tables.get.return_value = _info('x', {}, table_type='METRIC_VIEW')

        response = _drift(client, tree.table)

        assert response.status_code == 409
        assert response.json()['detail']['code'] == 'uc_reset_metric_view'

    def test_a_metric_view_asset_is_refused_without_reading(self, client, db_session, user_ws):
        asset = _asset(db_session, 'Metric View', 'main.sales.mv', 'x')

        assert _drift(client, asset).status_code == 409
        user_ws.tables.get.assert_not_called()

    def test_the_baseline_is_never_sent_to_clients(self, client, tree):
        properties = client.get(f'/api/assets/{tree.table.id}').json()['properties']

        assert properties is None or DESCRIPTION_BASELINE_PROPERTY not in properties


class TestResetSelected:
    def _post(self, client, asset, fields, headers=TOKEN):
        return client.post(f'/api/assets/{asset.id}/description/reset-selected',
                           json={'fields': fields}, headers=headers)

    def test_the_selected_fields_are_reset_with_one_read(
            self, client, db_session, tree, user_ws):
        user_ws.tables.get.return_value = _info(
            'Orders (UC)', {'order_id': 'Key (UC)', 'note': 'Note (UC)'})

        response = self._post(client, tree.table, [
            {'asset_id': str(tree.table.id)}, {'asset_id': str(tree.key.id)}])

        assert response.status_code == 200, response.text
        body = response.json()
        assert (body['changed'], body['failed']) == (2, 0)
        user_ws.tables.get.assert_called_once_with(full_name=TABLE)
        assert client.get(f'/api/assets/{tree.table.id}').json()['description'] == 'Orders (UC)'
        assert client.get(f'/api/assets/{tree.key.id}').json()['description'] == 'Key (UC)'
        # What was not selected is left alone
        assert client.get(f'/api/assets/{tree.note.id}').json()['description'] == 'Note (Ontos)'
        sources = {
            e.entity_id: json.loads(e.details_json)['source']
            for e in db_session.query(ChangeLogDb).filter(
                ChangeLogDb.action == 'description_changed')}
        assert sources[str(tree.table.id)] == sources[str(tree.key.id)] == 'uc_reset'

    def test_a_reset_records_the_comment_as_the_new_baseline(
            self, client, db_session, tree, user_ws):
        user_ws.tables.get.return_value = _info('Orders (UC v2)', {'order_id': 'Key (UC)'})

        assert self._post(client, tree.table, [{'asset_id': str(tree.table.id)}]).status_code == 200

        db_session.refresh(tree.table)
        assert baseline_of(tree.table.properties)['text'] == 'Orders (UC v2)'

    def test_the_table_snapshot_follows_a_reset_column(self, client, db_session, user_ws):
        table = _asset(db_session, 'Table', TABLE, 'T')
        table.properties = {'schema': {'columns': [{'name': 'order_id', 'description': 'old'}]}}
        column = _asset(db_session, 'Column', f'{TABLE}.order_id', 'old')
        user_ws.tables.get.return_value = _info('T', {'order_id': 'Key (UC)'})

        self._post(client, table, [{'asset_id': str(column.id)}])

        db_session.refresh(table)
        assert table.properties['schema']['columns'][0]['description'] == 'Key (UC)'

    def test_a_field_whose_comment_changed_since_it_was_shown_fails_alone(
            self, client, tree, user_ws):
        user_ws.tables.get.return_value = _info(
            'Orders (UC)', {'order_id': 'Key (UC changed again)'})

        body = self._post(client, tree.table, [
            {'asset_id': str(tree.table.id), 'expected_uc_comment': 'Orders (UC)'},
            {'asset_id': str(tree.key.id), 'expected_uc_comment': 'Key (UC)'},
        ]).json()

        ok, refused = body['results']
        assert ok['changed'] is True and ok['error'] is None
        assert refused['changed'] is False and refused['error']['code'] == 'uc_reset_uc_changed'
        assert (body['changed'], body['failed']) == (1, 1)

    def test_an_empty_comment_changes_nothing_and_warns(self, client, tree, user_ws):
        user_ws.tables.get.return_value = _info('Orders (UC)', {'order_id': None})

        [result] = self._post(client, tree.table, [{'asset_id': str(tree.key.id)}]).json()[
            'results']

        assert result['changed'] is False and result['error'] is None
        assert [w['code'] for w in result['warnings']] == ['uc_description_empty']

    def test_a_column_gone_from_unity_catalog_fails_alone(self, client, tree, user_ws):
        user_ws.tables.get.return_value = _info('Orders (UC)', {'order_id': 'Key (UC)'})

        results = self._post(client, tree.table, [
            {'asset_id': str(tree.note.id)}, {'asset_id': str(tree.key.id)}]).json()['results']

        assert results[0]['error']['code'] == 'uc_reset_object_not_found'
        assert results[1]['changed'] is True

    def test_an_asset_outside_the_table_is_refused_for_that_field(
            self, client, db_session, tree, user_ws):
        stranger = _asset(db_session, 'Column', 'main.sales.items.id', 'x')
        user_ws.tables.get.return_value = _info('Orders (UC)', {})

        [result] = self._post(client, tree.table, [{'asset_id': str(stranger.id)}]).json()[
            'results']

        assert result['error']['code'] == 'uc_reset_field_not_in_table'
        assert result['changed'] is False

    def test_without_the_user_token_nothing_is_read(self, client, tree, user_ws):
        response = self._post(client, tree.table, [{'asset_id': str(tree.table.id)}],
                              headers={'X-Forwarded-Email': 'user@example.com'})

        assert response.status_code == 403
        user_ws.tables.get.assert_not_called()

    def test_everything_the_dialog_lists_can_be_sent_at_once(self, client, tree, user_ws):
        # The table and the most columns a comparison lists (1000): "Select all" on a wide table
        from uuid import uuid4

        user_ws.tables.get.return_value = _info('Orders (UC)', {})
        fields = [{'asset_id': str(tree.table.id)}] + [
            {'asset_id': str(uuid4())} for _ in range(1000)]
        assert len(fields) == 1001

        response = self._post(client, tree.table, fields)

        assert response.status_code == 200, response.text
        assert len(response.json()['results']) == 1001

    def test_one_commit_and_one_maturity_task_for_all_the_fields(
            self, client, tree, user_ws, monkeypatch):
        from src.routes import assets_routes

        scheduled = []
        monkeypatch.setattr(
            assets_routes, '_schedule_maturity_evaluation',
            lambda db, tasks, request, asset_id, email: (scheduled.append(asset_id), db.commit()))
        user_ws.tables.get.return_value = _info(
            'Orders (UC)', {'order_id': 'Key (UC)', 'note': 'Note (UC)'})

        body = self._post(client, tree.table, [
            {'asset_id': str(a.id)} for a in (tree.table, tree.key, tree.note)]).json()

        assert body['changed'] == 3
        assert scheduled == [tree.table.id]

    def test_nothing_is_committed_before_the_one_commit_of_the_request(
            self, client, tree, user_ws, monkeypatch):
        from sqlalchemy.orm import Session
        from src.routes import assets_routes

        commits = []
        real_commit = Session.commit
        monkeypatch.setattr(
            Session, 'commit', lambda self: (commits.append(1), real_commit(self))[1])
        seen = []
        monkeypatch.setattr(
            assets_routes, '_schedule_maturity_evaluation',
            lambda db, tasks, request, asset_id, email: (seen.append(len(commits)), db.commit()))
        user_ws.tables.get.return_value = _info(
            'Orders (UC)', {'order_id': 'Key (UC)', 'note': 'Note (UC)'})

        body = self._post(client, tree.table, [
            {'asset_id': str(a.id)} for a in (tree.table, tree.key, tree.note)]).json()

        assert body['changed'] == 3
        assert seen == [0]

    def test_a_failure_commits_nothing_of_the_fields_before_it(
            self, client, tree, user_ws, monkeypatch):
        from sqlalchemy.orm import Session
        from src.controller.assets_manager import AssetsManager

        commits = []
        real_commit = Session.commit
        monkeypatch.setattr(
            Session, 'commit', lambda self: (commits.append(1), real_commit(self))[1])
        real = AssetsManager.update_asset
        calls = []

        def failing(self, db, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                before_failure.append(len(commits))
                raise RuntimeError('boom')
            return real(self, db, **kwargs)

        before_failure = []
        monkeypatch.setattr(AssetsManager, 'update_asset', failing)
        user_ws.tables.get.return_value = _info(
            'Orders (UC)', {'order_id': 'Key (UC)', 'note': 'Note (UC)'})

        response = self._post(client, tree.table, [
            {'asset_id': str(tree.table.id)}, {'asset_id': str(tree.key.id)}])

        assert response.status_code == 500
        # The first field was not committed on its own (the audit entry commits later)
        assert before_failure == [0]

    def test_an_unexpected_failure_is_a_coded_error_without_its_text(
            self, client, tree, user_ws, monkeypatch):
        from src.controller.assets_manager import AssetsManager

        real = AssetsManager.update_asset
        calls = []

        def failing(self, db, **kwargs):
            calls.append(kwargs['asset_id'])
            if len(calls) == 2:
                raise RuntimeError('boom: internal detail')
            return real(self, db, **kwargs)

        monkeypatch.setattr(AssetsManager, 'update_asset', failing)
        user_ws.tables.get.return_value = _info(
            'Orders (UC)', {'order_id': 'Key (UC)', 'note': 'Note (UC)'})

        response = self._post(client, tree.table, [
            {'asset_id': str(tree.table.id)}, {'asset_id': str(tree.key.id)}])

        assert response.status_code == 500
        detail = response.json()['detail']
        assert detail['code'] == 'uc_reset_failed'
        assert 'boom' not in response.text

    def test_more_than_the_dialog_can_list_is_refused(self, client, tree, user_ws):
        from uuid import uuid4

        fields = [{'asset_id': str(uuid4())} for _ in range(1002)]

        assert self._post(client, tree.table, fields).status_code == 422

    def test_no_fields_is_a_validation_error(self, client, tree, user_ws):
        assert self._post(client, tree.table, []).status_code == 422

    def test_it_writes_nothing_to_unity_catalog(self, client, writeback_on, tree, user_ws):
        user_ws.tables.get.return_value = _info('Orders (UC)', {'order_id': 'Key (UC)'})

        self._post(client, tree.table, [{'asset_id': str(tree.table.id)}])

        user_ws.statement_execution.execute_statement.assert_not_called()


class TestBaselineAtWriteBack:
    @pytest.fixture
    def ws(self, monkeypatch):
        from src.routes import assets_routes

        ws = MagicMock()
        ws.statement_execution.execute_statement.return_value = SimpleNamespace(
            status=SimpleNamespace(state=StatementState.SUCCEEDED, error=None),
            statement_id='st-1')
        ws.tables.get.return_value = _info(None, {})
        reads_back_comment_writes(ws)
        monkeypatch.setattr(assets_routes, 'get_obo_workspace_client', lambda request: ws)
        return ws

    def test_a_write_back_records_the_comment_it_left_in_unity_catalog(
            self, client, db_session, writeback_on, ws):
        table = _asset(db_session, 'Table', TABLE, 'v0')

        response = client.put(f'/api/assets/{table.id}', json={'description': 'v1'},
                              headers=TOKEN)

        assert response.status_code == 200, response.text
        db_session.refresh(table)
        assert baseline_of(table.properties)['text'] == 'v1'

    def test_a_refused_write_back_records_nothing(
            self, client, db_session, writeback_on, ws):
        table = _asset(db_session, 'Table', TABLE, 'v0')
        ws.tables.get.side_effect = None
        ws.tables.get.return_value = _info('Written in UC', {})

        response = client.put(f'/api/assets/{table.id}', json={'description': 'v1'},
                              headers=TOKEN)

        assert response.json()['warnings'][0]['code'] == 'uc_description_existing_comment'
        db_session.refresh(table)
        assert baseline_of(table.properties) is None
