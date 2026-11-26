"""Resetting several descriptions at once is one transaction: an unexpected failure rolls every
field back and is a coded error, never a half-applied reset."""
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from src.common.uc_comments import TableComments
from src.controller.uc_description_drift_manager import (
    ResetFailedError, UcDescriptionDriftManager,
)
from src.controller.uc_description_reset_manager import ResetOutcome, UcDescriptionResetManager
from src.models.asset_description import DescriptionResetResult, ResetFieldRequest

TABLE = 'main.sales.orders'


def _asset(location):
    return SimpleNamespace(
        id=uuid4(), location=location, platform='databricks', description='x',
        asset_type=SimpleNamespace(name='Column' if location != TABLE else 'Table'),
        properties=None)


def _manager(assets, fail_on):
    reset = MagicMock(spec=UcDescriptionResetManager)
    by_id = {a.id: a for a in assets}
    reset.get_asset.return_value = assets[0]
    reset.target_of.side_effect = lambda a: (
        (TABLE, None) if a.location == TABLE else (TABLE, a.location.rsplit('.', 1)[1]))
    reset.read_table.return_value = TableComments(
        comment='T (UC)', columns={'a': 'A (UC)', 'b': 'B (UC)'}, table_type=None)
    reset.lock.side_effect = lambda db, asset_id: by_id[asset_id]
    calls = []

    def apply(db, asset, label, uc_comment, **kwargs):
        calls.append(asset.id)
        if len(calls) == fail_on:
            raise RuntimeError('boom: internal detail')
        return ResetOutcome(DescriptionResetResult(
            asset_id=asset.id, target=label, changed=True), {})

    reset.apply_comment.side_effect = apply
    return UcDescriptionDriftManager(reset), reset


def test_an_unexpected_failure_rolls_back_every_field_and_is_coded():
    assets = [_asset(TABLE), _asset(f'{TABLE}.a'), _asset(f'{TABLE}.b')]
    manager, _reset = _manager(assets, fail_on=2)
    db = MagicMock()

    with pytest.raises(ResetFailedError) as raised:
        manager.reset_many(
            db, assets[0].id, [ResetFieldRequest(asset_id=a.id) for a in assets],
            user_client=lambda: MagicMock(), username='u')

    assert raised.value.code == 'uc_reset_failed' and raised.value.http_status == 500
    assert 'boom' not in str(raised.value)
    db.rollback.assert_called_once()
    db.commit.assert_not_called()


def test_the_fields_are_flushed_not_committed_by_the_manager():
    assets = [_asset(TABLE), _asset(f'{TABLE}.a')]
    manager, reset = _manager(assets, fail_on=0)
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []

    result = manager.reset_many(
        db, assets[0].id, [ResetFieldRequest(asset_id=a.id) for a in assets],
        user_client=lambda: MagicMock(), username='u')

    assert result.changed == 2
    db.commit.assert_not_called()
    db.rollback.assert_not_called()
    assert all(c.kwargs['snapshot'] is False for c in reset.apply_comment.call_args_list)
