"""Saving an asset's description writes it to Unity Catalog when the setting is on (#1477)."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.service.sql import StatementState

from src.common.api_errors import UserTokenRequiredError
from src.common.config import Settings
from src.controller.uc_description_sync_manager import (
    CODE_NO_WAREHOUSE, CODE_NOT_FOUND, CODE_PERMISSION_DENIED, CODE_USER_TOKEN_REQUIRED,
    UcDescriptionSyncManager, uc_comment_target,
)
from src.db_models.assets import AssetDb, AssetTypeDb
from src.models.assets import DESCRIPTION_SYNC_PROPERTY


def _settings(enabled=True, warehouse='wh-1'):
    settings = MagicMock(spec=Settings)
    settings.UC_DESCRIPTION_WRITEBACK_ENABLED = enabled
    settings.DATABRICKS_WAREHOUSE_ID = warehouse
    return settings


def _type(db, name):
    found = db.query(AssetTypeDb).filter(AssetTypeDb.name == name).first()
    if found is None:
        found = AssetTypeDb(name=name, category='data')
        db.add(found)
        db.flush()
    return found


def _asset(db, type_name='Table', location='main.sales.orders', platform='databricks',
           description='New text', properties=None):
    row = AssetDb(name=location.split('.')[-1], asset_type_id=_type(db, type_name).id,
                  platform=platform, location=location, description=description,
                  properties=properties)
    db.add(row)
    db.flush()
    db.refresh(row)
    return row


def _ws(state=StatementState.SUCCEEDED, message=None):
    ws = MagicMock()
    error = SimpleNamespace(message=message) if message else None
    ws.statement_execution.execute_statement.return_value = SimpleNamespace(
        status=SimpleNamespace(state=state, error=error), statement_id='st-1')
    return ws


def _statements(ws):
    return [c.kwargs['statement'] for c in ws.statement_execution.execute_statement.call_args_list]


def _sync(db, asset, ws, *, enabled=True, previous='Old text', sent=True, warehouse='wh-1'):
    return UcDescriptionSyncManager(_settings(enabled, warehouse)).sync_after_update(
        db, asset.id, description_sent=sent, previous_description=previous,
        user_client=lambda: ws,
    )


def test_with_the_setting_off_nothing_is_written(db_session):
    asset = _asset(db_session)
    ws = _ws()

    warning, state = _sync(db_session, asset, ws, enabled=False)

    assert (warning, state) == (None, None)
    ws.statement_execution.execute_statement.assert_not_called()


def test_a_table_description_becomes_its_comment(db_session):
    asset = _asset(db_session)
    ws = _ws()

    warning, state = _sync(db_session, asset, ws)

    assert (warning, state) == (None, None)
    assert _statements(ws) == ["COMMENT ON TABLE `main`.`sales`.`orders` IS 'New text'"]


def test_a_column_description_becomes_its_column_comment(db_session):
    asset = _asset(db_session, type_name='Column', location='main.sales.orders.order_id')
    ws = _ws()

    _sync(db_session, asset, ws)

    assert _statements(ws) == [
        "COMMENT ON COLUMN `main`.`sales`.`orders`.`order_id` IS 'New text'"]


def test_a_permission_denied_write_keeps_the_save_and_marks_the_asset(db_session):
    asset = _asset(db_session, properties={'owner': 'sales'})
    ws = _ws(StatementState.FAILED, '[INSUFFICIENT_PERMISSIONS] User does not have MODIFY')

    warning, state = _sync(db_session, asset, ws)

    assert warning.code == CODE_PERMISSION_DENIED
    assert warning.params == {'object': 'main.sales.orders'}
    assert state.code == CODE_PERMISSION_DENIED and state.status == 'out_of_sync'
    db_session.refresh(asset)
    assert asset.description == 'New text'
    assert asset.properties['owner'] == 'sales'
    assert asset.properties[DESCRIPTION_SYNC_PROPERTY]['code'] == CODE_PERMISSION_DENIED


def test_a_missing_object_is_a_not_found_warning(db_session):
    asset = _asset(db_session)
    ws = _ws(StatementState.FAILED, '[TABLE_OR_VIEW_NOT_FOUND] cannot be found')

    warning, state = _sync(db_session, asset, ws)

    assert warning.code == CODE_NOT_FOUND
    assert state.code == CODE_NOT_FOUND


def test_saving_again_after_a_failure_retries_and_clears_the_mark(db_session):
    asset = _asset(db_session)
    _sync(db_session, asset, _ws(StatementState.FAILED, 'PERMISSION_DENIED'))
    ws = _ws()

    # The same text again: written, since the asset is out of sync
    warning, state = _sync(db_session, asset, ws, previous='New text')

    assert (warning, state) == (None, None)
    assert len(_statements(ws)) == 1
    db_session.refresh(asset)
    assert DESCRIPTION_SYNC_PROPERTY not in (asset.properties or {})


def test_an_unchanged_description_is_not_written(db_session):
    asset = _asset(db_session)
    ws = _ws()

    _sync(db_session, asset, ws, previous='New text')
    _sync(db_session, asset, ws, sent=False)

    ws.statement_execution.execute_statement.assert_not_called()


def test_without_the_user_token_nothing_is_written_as_the_app(db_session):
    asset = _asset(db_session)

    def no_token():
        raise UserTokenRequiredError('no token')

    warning, state = UcDescriptionSyncManager(_settings()).sync_after_update(
        db_session, asset.id, description_sent=True, previous_description='Old text',
        user_client=no_token,
    )

    assert warning.code == CODE_USER_TOKEN_REQUIRED
    assert state.code == CODE_USER_TOKEN_REQUIRED


def test_without_a_warehouse_it_warns(db_session):
    asset = _asset(db_session)
    ws = _ws()

    warning, _ = _sync(db_session, asset, ws, warehouse='')

    assert warning.code == CODE_NO_WAREHOUSE
    ws.statement_execution.execute_statement.assert_not_called()


@pytest.mark.parametrize('type_name, location, platform', [
    ('Table', 'main.sales.orders', 'snowflake'),
    ('Table', 'not-a-three-part-name', 'databricks'),
    ('Column', 'main.sales.orders', 'databricks'),
    ('Dashboard', 'main.sales.orders', 'databricks'),
])
def test_other_assets_are_not_written(db_session, type_name, location, platform):
    asset = _asset(db_session, type_name=type_name, location=location, platform=platform)
    ws = _ws()

    assert _sync(db_session, asset, ws) == (None, None)
    ws.statement_execution.execute_statement.assert_not_called()


def test_a_databricks_platform_is_matched_in_any_case(db_session):
    asset = _asset(db_session, type_name='View', platform='Databricks')

    assert uc_comment_target(asset) == ('main.sales.orders', None)
