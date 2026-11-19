"""UC Bulk Import against a real Postgres (#1469).

The unit tests run the job on SQLite, which has no advisory locks, no
``timestamptz`` and a looser NOT NULL story for raw SQL. This module runs the
job's SQL on Postgres and **auto-skips** when none is reachable, so it is safe
in CI. Point it at a throwaway database (a local one or a Lakebase branch)::

    UC_BULK_IMPORT_TEST_PG_URL=postgresql+psycopg2://user:pw@localhost:5432/db \\
        hatch -e dev run pytest src/tests/integration/test_uc_bulk_import_pg.py

``SEARCH_TEST_PG_URL`` (see ``test_search_repository_pg.py``) works too. Each
test builds the app's tables with ``create_all`` in its own schema and drops
the schema afterwards.
"""
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.common.database import Base
import src.db_models  # noqa: F401  (registers every table on Base.metadata)

_pyspark_sql = ModuleType('pyspark.sql')
_pyspark_sql.SparkSession = MagicMock()
with patch.dict(sys.modules, {'pyspark': ModuleType('pyspark'), 'pyspark.sql': _pyspark_sql}):
    import src.workflows.uc_bulk_import.uc_bulk_import as job

_PG_URL = os.environ.get('UC_BULK_IMPORT_TEST_PG_URL') or os.environ.get('SEARCH_TEST_PG_URL')
_TABLES = ['main.sales.orders', 'main.sales.customers']


def _check_pg_or_skip():
    if not _PG_URL:
        pytest.skip('UC_BULK_IMPORT_TEST_PG_URL not set: Postgres test skipped')
    try:
        eng = create_engine(_PG_URL)
        with eng.connect() as c:
            c.execute(text('SELECT 1'))
        eng.dispose()
    except Exception as e:  # pragma: no cover - environment dependent
        pytest.skip(f'Postgres not reachable: {e}')


@pytest.fixture()
def admin():
    _check_pg_or_skip()
    eng = create_engine(_PG_URL)
    yield eng
    eng.dispose()


@pytest.fixture()
def pg(admin):
    """An engine whose connections use a fresh schema holding the app's tables."""
    schema = f'uc_import_it_{uuid.uuid4().hex[:8]}'
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(_PG_URL, connect_args={'options': f'-csearch_path={schema}'})
    try:
        Base.metadata.create_all(bind=engine)
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


@pytest.fixture()
def lock_name(monkeypatch):
    # Advisory locks are database-wide: a name per test keeps parallel runs apart
    name = f'ontos.uc_bulk_import.test.{uuid.uuid4().hex}'
    monkeypatch.setattr(job, 'IMPORT_LOCK_NAME', name)
    return name


def _lock_holder_states(admin, name):
    """pg_stat_activity state of each session holding the advisory lock ``name``."""
    with admin.connect() as conn:
        return conn.execute(text("""
            SELECT a.state FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid
            WHERE l.locktype = 'advisory' AND l.granted AND l.objsubid = 1
              AND ((l.classid::bigint << 32) | l.objid::bigint) = hashtext(:name)::bigint
        """), {'name': name}).scalars().all()


def test_the_lock_is_held_outside_a_transaction(admin, lock_name):
    engine = create_engine(_PG_URL)
    try:
        with job.single_flight(engine) as acquired:
            assert acquired is True
            # In a transaction, idle_in_transaction_session_timeout (or a
            # transaction-mode pooler) could end the session and drop the lock.
            assert _lock_holder_states(admin, lock_name) == ['idle']
        assert _lock_holder_states(admin, lock_name) == []
    finally:
        engine.dispose()


def test_an_overlapping_run_does_not_get_the_lock(admin, lock_name):
    first, second = create_engine(_PG_URL), create_engine(_PG_URL)
    try:
        with job.single_flight(first) as acquired:
            assert acquired is True
            with job.single_flight(second) as overlapping:
                assert overlapping is False
        # Released when the first run ends
        with job.single_flight(second) as acquired_later:
            assert acquired_later is True
    finally:
        first.dispose()
        second.dispose()
