"""Migration s3 gives the read request notifications the ``handled`` marker (#1527 review).

Older builds recorded a decided request only as ``read``; the classifier now decides a
request by the marker alone, so the upgrade marks those rows, and leaves approvals, unread
rows and rows already marked as they are.
"""
import importlib.util
import json
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.db_models.notifications import NotificationDb

_NAME = 's3_notifications_read_requests_handled'
OLD = datetime(2020, 1, 1, 12, 0, 0)


@pytest.fixture
def migration():
    path = Path(__file__).resolve().parents[3] / 'alembic' / 'versions' / f'{_NAME}.py'
    spec = importlib.util.spec_from_file_location(_NAME, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def engine():
    engine = create_engine(
        'sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False},
    )
    NotificationDb.__table__.create(bind=engine)
    return engine


def _row(key: str, **fields) -> dict:
    row = dict(
        id=key, type='action_required', title=key, created_at=OLD, read=True,
        can_delete=True, recipient='ana@example.com', recipient_role_id=None,
        action_type='handle_role_request',
        action_payload=json.dumps({'request_id': str(uuid.uuid4())}),
    )
    row.update(fields)
    return row


def _seed(engine, rows):
    with engine.begin() as conn:
        conn.execute(NotificationDb.__table__.insert(), rows)


def _payloads(engine) -> dict:
    with engine.connect() as conn:
        return dict(conn.execute(text('SELECT id, action_payload FROM notifications')).all())


def _run(engine, step):
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            step()


def test_it_sits_on_the_document_markdown_import_head(migration):
    assert migration.down_revision == 's2_document_markdown_import'


def test_upgrade_marks_only_the_read_requests_handled(migration, engine):
    rows = [
        _row('read-request', action_payload=json.dumps({'request_id': 'r-1'})),
        _row('read-delivery', action_type='delivery_manual',
             action_payload=json.dumps({'change_type': 'grant'})),
        _row('read-no-payload', action_type='handle_job_enable_request', action_payload=None),
        _row('read-not-json', action_payload='not json'),
        _row('unread-request', read=False),
        _row('read-approval', action_type='workflow_approval',
             action_payload=json.dumps({'execution_id': 'e-1', 'step_id': 'approve'})),
        _row('unread-approval', action_type='workflow_approval', read=False),
        _row('read-info', type='info', action_type='agreement_completed'),
        _row('read-no-action-type', action_type=None),
        _row('already-handled', action_payload='{"request_id": "r-2", "handled" : true}'),
        _row('already-completed', action_type='delivery_manual',
             action_payload=json.dumps({'completed': True})),
    ]
    _seed(engine, rows)
    before = _payloads(engine)

    _run(engine, migration.upgrade)

    after = _payloads(engine)
    assert json.loads(after['read-request']) == {'request_id': 'r-1', 'handled': True}
    assert json.loads(after['read-delivery']) == {'change_type': 'grant', 'handled': True}
    assert json.loads(after['read-no-payload']) == {'handled': True}
    assert json.loads(after['read-not-json']) == {
        'legacy_action_payload': 'not json', 'handled': True,
    }
    untouched = {'unread-request', 'read-approval', 'unread-approval', 'read-info',
                 'read-no-action-type', 'already-handled', 'already-completed'}
    assert {key: after[key] for key in untouched} == {key: before[key] for key in untouched}


def test_the_marked_rows_are_decided_for_the_classifier(migration, engine):
    """End to end on SQLite: a read request is pending before the upgrade, decided after."""
    from sqlalchemy.orm import sessionmaker
    from src.repositories.notification_repository import RecipientKeys, notification_repo

    _seed(engine, [_row('read-request'), _row('unread-request', read=False),
                   _row('read-approval', action_type='workflow_approval')])
    keys = RecipientKeys(identities=frozenset({'ana@example.com'}))

    def pending():
        with sessionmaker(bind=engine)() as db:
            return {n.id for n in notification_repo.get_addressed_to(
                db, keys=keys, history_limit=0)}

    assert pending() == {'read-request', 'unread-request', 'read-approval'}
    _run(engine, migration.upgrade)
    assert pending() == {'unread-request', 'read-approval'}


def test_upgrade_is_idempotent_and_downgrade_keeps_the_marker(migration, engine):
    _seed(engine, [_row('read-request', action_payload=json.dumps({'request_id': 'r-1'}))])

    _run(engine, migration.upgrade)
    once = _payloads(engine)
    _run(engine, migration.upgrade)
    assert _payloads(engine) == once

    _run(engine, migration.downgrade)
    assert _payloads(engine) == once
