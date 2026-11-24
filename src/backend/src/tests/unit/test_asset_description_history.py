"""The description history: what is logged, and that it is never committed or swallowed here."""
import json
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from src.controller import asset_description_history as history
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.change_log import ChangeLogDb


def _asset(db, type_name='Table', description='Old', location='main.sales.orders'):
    found = db.query(AssetTypeDb).filter(AssetTypeDb.name == type_name).first()
    if found is None:
        found = AssetTypeDb(name=type_name, category='data')
        db.add(found)
        db.flush()
    row = AssetDb(name=location.split('.')[-1], asset_type_id=found.id, platform='databricks',
                  location=location, description=description)
    db.add(row)
    db.flush()
    db.refresh(row)
    return row


def _entries(db, asset):
    rows = db.query(ChangeLogDb).filter(ChangeLogDb.entity_id == str(asset.id)).all()
    return [(r.action, r.username, json.loads(r.details_json)) for r in rows]


def test_a_change_is_one_entry_with_before_after_and_source(db_session):
    asset = _asset(db_session)

    assert history.record_description_change(
        db_session, asset, before='Old', after='New', source=history.SOURCE_UC_RESET,
        username='a@b.c', extra={'uc_comment': 'New'})

    [(action, username, details)] = _entries(db_session, asset)
    assert (action, username) == ('description_changed', 'a@b.c')
    assert details == {
        'name': 'orders', 'object_type': 'table', 'location': 'main.sales.orders',
        'before': 'Old', 'after': 'New', 'source': 'uc_reset', 'uc_comment': 'New'}


@pytest.mark.parametrize('before,after', [('Same', 'Same'), (None, ''), ('', None)])
def test_an_unchanged_description_is_not_logged(db_session, before, after):
    asset = _asset(db_session)

    assert not history.record_description_change(
        db_session, asset, before=before, after=after, source='manual', username='u')

    assert _entries(db_session, asset) == []


def test_an_emptied_description_is_logged_as_none(db_session):
    asset = _asset(db_session)

    history.record_description_change(
        db_session, asset, before='Old', after='', source='manual', username='u')

    assert _entries(db_session, asset)[0][2]['after'] is None


def test_only_tables_views_and_columns_are_tracked(db_session):
    dashboard = _asset(db_session, 'Dashboard')

    assert not history.record_description_change(
        db_session, dashboard, before='a', after='b', source='manual', username='u')
    assert history.is_tracked_type('View') and history.is_tracked_type(' column ')
    assert not history.is_tracked_type('Metric View') and not history.is_tracked_type(None)


def test_the_entry_is_flushed_but_not_committed(db_session, monkeypatch):
    asset = _asset(db_session)
    commit = MagicMock()
    monkeypatch.setattr(Session, 'commit', commit)

    history.record_description_change(
        db_session, asset, before='a', after='b', source='manual', username='u')

    commit.assert_not_called()
    assert len(_entries(db_session, asset)) == 1


def test_a_failure_to_write_the_entry_is_raised(db_session, monkeypatch):
    asset = _asset(db_session)

    def failing(*args, **kwargs):
        raise RuntimeError('change log down')

    monkeypatch.setattr(history.change_log_manager, 'log_change_with_details', failing)

    with pytest.raises(RuntimeError):
        history.record_description_change(
            db_session, asset, before='a', after='b', source='manual', username='u')


def test_the_source_of_a_change_comes_from_its_context(db_session):
    asset = _asset(db_session)

    history.record_description_change(
        db_session, asset, before='a', after='b', source=history.current_description_source(),
        username='u')
    with history.description_source(history.SOURCE_RESTORE, restored_from='e1'):
        assert history.current_description_source() == 'restore'
        history.record_description_change(
            db_session, asset, before='b', after='c', source=history.current_description_source(),
            username='u')
    assert history.current_description_source() == 'manual'

    [first, second] = [d for _a, _u, d in _entries(db_session, asset)]
    assert first['source'] == 'manual' and 'restored_from' not in first
    assert (second['source'], second['restored_from']) == ('restore', 'e1')


def test_the_context_is_restored_after_an_error():
    with pytest.raises(RuntimeError):
        with history.description_source('uc_reset'):
            raise RuntimeError('boom')

    assert history.current_description_source() == 'manual'


def test_the_history_of_an_asset_is_paged_and_scoped(db_session):
    from datetime import datetime, timedelta, timezone

    asset = _asset(db_session)
    other = _asset(db_session, location='main.sales.items')
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index, target in enumerate((asset, asset, asset, other)):
        entry = history.change_log_manager.log_change_with_details(
            db_session, entity_type='asset', entity_id=str(target.id),
            action='description_changed', username='u', details={'after': str(index)},
            commit=False)
        entry.timestamp = base + timedelta(seconds=index)
    db_session.flush()

    total, page = history.list_description_history(db_session, asset.id, skip=1, limit=1)

    assert total == 3 and [e.details['after'] for e in page] == ['1']
    assert history.get_description_entry(db_session, asset.id, page[0].id) is not None
    assert history.get_description_entry(db_session, other.id, page[0].id) is None
