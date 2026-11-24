"""Local-Postgres integration test for the notification list's SQL (#1526, #1527 review).

The unit and integration suites run on SQLite. ``NotificationRepository.get_addressed_to``
relies on ``replace``, ``LIKE``, ``lower`` and an ``ORDER BY ... LIMIT``; this module runs
that SQL, and the s3 migration that marks the read requests handled, on Postgres and
**auto-skips** when no database is configured, so it is safe in CI.

To run it, point it at a throwaway Postgres via ``NOTIFICATIONS_TEST_PG_URL``::

    NOTIFICATIONS_TEST_PG_URL=postgresql+psycopg2://user:pw@localhost:5432/db \\
        hatch -e dev run pytest src/tests/integration/test_notification_repository_pg.py
"""
import importlib.util
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.db_models.notifications import NotificationDb
from src.repositories.notification_repository import RecipientKeys, notification_repo

_PG_URL = os.environ.get("NOTIFICATIONS_TEST_PG_URL")
HISTORY = 5
ANA = RecipientKeys(identities=frozenset({'ana@example.com'}))
AFTER = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
OLD = datetime(2020, 1, 1, 12, 0, tzinfo=timezone.utc)
_MIGRATION = 's3_notif_read_requests_handled'


def _check_pg_or_skip():
    if not _PG_URL:
        pytest.skip("NOTIFICATIONS_TEST_PG_URL not set: Postgres notification test skipped")
    try:
        eng = create_engine(_PG_URL, future=True)
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
        eng.dispose()
    except Exception as e:  # pragma: no cover - environment dependent
        pytest.skip(f"Postgres not reachable at NOTIFICATIONS_TEST_PG_URL: {e}")


@pytest.fixture()
def pg_session():
    """A session on a fresh notifications table in a throwaway schema, dropped afterwards."""
    _check_pg_or_skip()
    schema = f"notif_it_{uuid.uuid4().hex[:8]}"
    admin = create_engine(_PG_URL, future=True)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        _PG_URL, future=True, connect_args={"options": f"-csearch_path={schema}"},
    )
    NotificationDb.__table__.create(bind=engine)
    db = sessionmaker(bind=engine, future=True)()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _row(**fields) -> dict:
    row = dict(
        id=str(uuid.uuid4()), type='info', title='Notification', created_at=AFTER,
        read=False, can_delete=True, recipient='ana@example.com', recipient_role_id=None,
        action_type=None, action_payload=None,
    )
    row.update(fields)
    return row


def _request(**fields) -> dict:
    return _row(**{
        'type': 'action_required', 'action_type': 'handle_role_request',
        'action_payload': json.dumps({'request_id': 'r-1'}), **fields,
    })


def _insert(db, rows):
    db.execute(NotificationDb.__table__.insert(), rows)
    db.flush()


def _history(count: int = HISTORY + 2) -> list:
    """Informational rows newer than every target row: more than the history holds."""
    start = AFTER + timedelta(days=1)
    return [_row(title=f'Later {i}', created_at=start + timedelta(minutes=i))
            for i in range(count)]


def _listed(db) -> list:
    return [n.id for n in notification_repo.get_addressed_to(db, keys=ANA, history_limit=HISTORY)]


def test_read_alone_never_decides_a_request(pg_session):
    _insert(pg_session, _history())
    rows = [_request(read=True, created_at=at) for at in (OLD, AFTER)]
    _insert(pg_session, rows)

    listed = _listed(pg_session)

    assert all(row['id'] in listed for row in rows)


def _migration():
    path = Path(__file__).resolve().parents[3] / 'alembic' / 'versions' / f'{_MIGRATION}.py'
    spec = importlib.util.spec_from_file_location(_MIGRATION, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migration_marks_the_read_requests_handled_on_postgres(pg_session):
    _insert(pg_session, _history())
    read_request = _request(read=True, created_at=OLD)
    unread_request = _request(created_at=OLD)
    read_approval = _request(read=True, action_type='workflow_approval', created_at=OLD,
                             action_payload=json.dumps({'execution_id': 'e-1'}))
    _insert(pg_session, [read_request, unread_request, read_approval])

    migration = _migration()
    migration._BATCH = 1  # keyset batches by id: one row per read, on Postgres too
    with Operations.context(MigrationContext.configure(pg_session.connection())):
        migration.upgrade()
    pg_session.flush()

    listed = _listed(pg_session)
    stored = pg_session.get(NotificationDb, read_request['id'])
    pg_session.refresh(stored)
    assert json.loads(stored.action_payload) == {'request_id': 'r-1', 'handled': True}
    assert read_request['id'] not in listed
    assert unread_request['id'] in listed
    assert read_approval['id'] in listed


def test_the_markers_match_whatever_the_json_spacing(pg_session):
    _insert(pg_session, _history())
    compact = _request(action_payload='{"request_id":"r-1","handled":true}')
    indented = _request(action_payload='{\n  "request_id": "r-1",\n\t"handled" : true\n}')
    delivered = _request(action_type='delivery_manual',
                         action_payload=json.dumps({'completed': True}))
    quoted = _request(action_payload=json.dumps({'reason': '"handled":true'}))
    _insert(pg_session, [compact, indented, delivered, quoted])

    listed = _listed(pg_session)

    assert compact['id'] not in listed
    assert indented['id'] not in listed
    assert delivered['id'] not in listed
    # The marker inside a string value is escaped, so the request is still pending
    assert quoted['id'] in listed


def test_a_recipient_with_stray_whitespace_matches(pg_session):
    rows = [_request(recipient=r) for r in ('\tana@example.com', 'ANA@example.com\r\n')]
    _insert(pg_session, rows + [_request(recipient='bob@example.com')])

    assert sorted(_listed(pg_session)) == sorted(row['id'] for row in rows)


def test_equal_timestamps_are_cut_and_ordered_by_id(pg_session):
    same = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    rows = [_row(id=f'n-{i:02d}', created_at=same) for i in range(HISTORY + 3)]
    _insert(pg_session, rows)

    assert _listed(pg_session) == sorted((r['id'] for r in rows), reverse=True)[:HISTORY]
