"""Saving an asset's description writes it to Unity Catalog when the setting is on (#1477)."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.errors import PermissionDenied
from databricks.sdk.service.sql import StatementState

from src.common.api_errors import UserTokenRequiredError
from src.common.config import Settings
from src.controller.uc_description_sync_manager import (
    CODE_EXISTING_COMMENT, CODE_NO_WAREHOUSE, CODE_NOT_FOUND, CODE_PERMISSION_DENIED,
    CODE_UNSUPPORTED_TEXT, CODE_USER_TOKEN_REQUIRED, UcDescriptionSyncManager, uc_comment_target,
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


def _ws(state=StatementState.SUCCEEDED, message=None, *, comment=None, table_type=None,
        columns=()):
    """A workspace client whose table has ``comment`` (and ``columns``) when read."""
    ws = MagicMock()
    error = SimpleNamespace(message=message) if message else None
    ws.statement_execution.execute_statement.return_value = SimpleNamespace(
        status=SimpleNamespace(state=state, error=error), statement_id='st-1')
    ws.tables.get.return_value = SimpleNamespace(
        comment=comment, table_type=table_type, columns=list(columns))
    return ws


def _statements(ws):
    return [c.kwargs['statement'] for c in ws.statement_execution.execute_statement.call_args_list]


def _sync(db, asset, ws, *, enabled=True, previous='Old text', sent=True, warehouse='wh-1'):
    """``(warning, state)`` of a save; the caller commits, as the routes do."""
    outcome = UcDescriptionSyncManager(_settings(enabled, warehouse)).sync_after_update(
        db, asset.id, description_sent=sent, previous_description=previous,
        user_client=lambda: ws,
    )
    db.flush()
    return outcome.warning, outcome.state


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
    ws = _ws(columns=[SimpleNamespace(name='order_id', comment=None)])

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

    outcome = UcDescriptionSyncManager(_settings()).sync_after_update(
        db_session, asset.id, description_sent=True, previous_description='Old text',
        user_client=no_token,
    )

    assert outcome.warning.code == CODE_USER_TOKEN_REQUIRED
    assert outcome.state.code == CODE_USER_TOKEN_REQUIRED


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


def test_with_the_setting_off_a_save_clears_an_old_mark(db_session):
    asset = _asset(db_session)
    _sync(db_session, asset, _ws(StatementState.FAILED, 'PERMISSION_DENIED'))
    ws = _ws()

    warning, state = _sync(db_session, asset, ws, enabled=False, previous='New text')

    assert (warning, state) == (None, None)
    ws.statement_execution.execute_statement.assert_not_called()
    db_session.refresh(asset)
    assert DESCRIPTION_SYNC_PROPERTY not in (asset.properties or {})


def test_a_comment_someone_else_wrote_is_kept_and_the_save_warns(db_session):
    asset = _asset(db_session)
    ws = _ws(comment='PII: CRM master, see runbook X')

    outcome = UcDescriptionSyncManager(_settings()).sync_after_update(
        db_session, asset.id, description_sent=True, previous_description=None,
        user_client=lambda: ws,
    )

    assert outcome.warning.code == CODE_EXISTING_COMMENT
    assert outcome.in_sync is False
    assert outcome.state.code == CODE_EXISTING_COMMENT
    ws.statement_execution.execute_statement.assert_not_called()
    assert outcome.audit == {'before': 'PII: CRM master, see runbook X', 'after': 'PII: CRM master, see runbook X', 'outcome': 'refused'}
    db_session.refresh(asset)
    assert asset.description == 'New text'


def test_a_column_comment_someone_else_wrote_is_kept(db_session):
    asset = _asset(db_session, type_name='Column', location='main.sales.orders.order_id')
    ws = _ws(columns=[SimpleNamespace(name='order_id', comment='Customer key')])

    warning, _ = _sync(db_session, asset, ws)

    assert warning.code == CODE_EXISTING_COMMENT
    ws.statement_execution.execute_statement.assert_not_called()


def test_the_comment_ontos_agreed_to_before_is_replaced(db_session):
    asset = _asset(db_session)
    ws = _ws(comment='Old text')

    warning, state = _sync(db_session, asset, ws, previous='Old text')

    assert (warning, state) == (None, None)
    assert _statements(ws) == ["COMMENT ON TABLE `main`.`sales`.`orders` IS 'New text'"]


def test_an_empty_comment_is_written(db_session):
    asset = _asset(db_session)
    ws = _ws(comment=None)

    warning, _ = _sync(db_session, asset, ws, previous=None)

    assert warning is None
    assert len(_statements(ws)) == 1


def test_a_comment_already_equal_to_the_description_is_not_written_again(db_session):
    asset = _asset(db_session)
    ws = _ws(comment='New text')

    outcome = UcDescriptionSyncManager(_settings()).sync_after_update(
        db_session, asset.id, description_sent=True, previous_description=None,
        user_client=lambda: ws,
    )

    assert outcome.in_sync is True and outcome.warning is None
    ws.statement_execution.execute_statement.assert_not_called()


def test_a_metric_view_is_not_written(db_session):
    asset = _asset(db_session)
    ws = _ws(table_type=SimpleNamespace(value='METRIC_VIEW'))

    warning, state = _sync(db_session, asset, ws)

    assert (warning, state) == (None, None)
    ws.statement_execution.execute_statement.assert_not_called()


def test_a_table_that_cannot_be_read_is_not_written(db_session):
    asset = _asset(db_session)
    ws = _ws()
    ws.tables.get.side_effect = PermissionDenied('no BROWSE')

    warning, state = _sync(db_session, asset, ws)

    assert warning.code == CODE_PERMISSION_DENIED
    assert state.code == CODE_PERMISSION_DENIED
    ws.statement_execution.execute_statement.assert_not_called()


def test_a_nul_character_is_a_warning_and_nothing_is_read_or_written(db_session):
    asset = _asset(db_session, description='Bad\x00text')
    ws = _ws()

    warning, _ = _sync(db_session, asset, ws)

    assert warning.code == CODE_UNSUPPORTED_TEXT
    ws.tables.get.assert_not_called()
    ws.statement_execution.execute_statement.assert_not_called()


def test_a_view_is_written_as_a_table_comment(db_session):
    asset = _asset(db_session, type_name='View', location='main.sales.orders_v')
    ws = _ws()

    _sync(db_session, asset, ws)

    assert _statements(ws) == ["COMMENT ON TABLE `main`.`sales`.`orders_v` IS 'New text'"]


def test_a_column_name_with_dots_is_its_whole_last_part(db_session):
    asset = _asset(db_session, type_name='Column', location='main.sales.orders.a.b')
    ws = _ws(columns=[SimpleNamespace(name='a.b', comment=None)])

    _sync(db_session, asset, ws)

    assert _statements(ws) == ["COMMENT ON COLUMN `main`.`sales`.`orders`.`a.b` IS 'New text'"]
