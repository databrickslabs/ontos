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


def test_a_run_whose_lock_connection_was_terminated_finishes_normally(admin, lock_name, capsys):
    engine = create_engine(_PG_URL)
    try:
        with job.single_flight(engine) as acquired:
            assert acquired is True
            with admin.begin() as conn:
                conn.execute(text("""
                    SELECT pg_terminate_backend(l.pid) FROM pg_locks l
                    WHERE l.locktype = 'advisory' AND l.granted AND l.objsubid = 1
                      AND ((l.classid::bigint << 32) | l.objid::bigint) = hashtext(:name)::bigint
                """), {'name': lock_name})
        # Reaching here: the unlock error did not mask the run
        assert 'lock was lost' in capsys.readouterr().out
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


def _objects(name, tag, tables=_TABLES, object_type='TABLE'):
    return {name: [job.DiscoveredObject(object_type, t, {tag: ''}) for t in tables]}


def _stats(**counts):
    return {'created': 0, 'updated': 0, 'unchanged': 0, 'skipped': 0, 'errors': 0, **counts}


def _import_all(engine, strategy='skip', tables=_TABLES):
    return (
        job.create_products(engine, _objects('sales', 'p', tables), strategy, None, None),
        job.create_contracts(engine, _objects('orders', 'c', tables), strategy, None, None),
        job.create_domains(engine, _objects('finance', 'd', ['main.finance'], 'SCHEMA'),
                           strategy, created_by='job'),
    )


def test_every_insert_satisfies_the_not_null_columns(pg):
    # Postgres enforces NOT NULL on raw SQL: an omitted column is an error row
    assert _import_all(pg) == (_stats(created=1),) * 3
    with pg.connect() as conn:
        counts = {t: conn.execute(text(f'SELECT COUNT(*) FROM {t}')).scalar() for t in (
            'data_products', 'data_product_output_ports', 'data_contracts',
            'data_contract_schema_objects', 'data_domains', 'uc_bulk_import_sources')}
    assert counts == {
        'data_products': 1, 'data_product_output_ports': 2, 'data_contracts': 1,
        'data_contract_schema_objects': 2, 'data_domains': 1, 'uc_bulk_import_sources': 4,
    }


def test_timestamps_are_stored_as_timestamptz_in_utc(pg):
    before = datetime.now(timezone.utc)
    _import_all(pg)
    after = datetime.now(timezone.utc)

    with pg.connect() as conn:
        types = dict(conn.execute(text("""
            SELECT table_name || '.' || column_name, data_type FROM information_schema.columns
            WHERE table_schema = current_schema() AND column_name IN ('created_at', 'updated_at')
              AND table_name IN ('data_products', 'data_contracts', 'data_domains',
                                 'uc_bulk_import_sources')
        """)).all())
        stamps = [conn.execute(text(f'SELECT created_at FROM {t}')).scalar() for t in (
            'data_products', 'data_contracts', 'data_domains', 'uc_bulk_import_sources')]
    assert set(types.values()) == {'timestamp with time zone'} and len(types) == 7
    assert all(before - timedelta(seconds=1) <= s <= after + timedelta(seconds=1)
               for s in stamps)


def test_imported_drafts_are_listed_for_admins_only(pg):
    from pathlib import Path
    from src.controller.data_contracts_manager import DataContractsManager
    from src.controller.data_products_manager import DataProductsManager

    _import_all(pg)
    with Session(pg) as db:
        products = DataProductsManager(db=db)
        assert [p.name for p in products.list_products(is_admin=True)] == ['sales']
        assert products.list_products(
            is_admin=False, caller_email='analyst@example.com',
            caller_team_ids=[], caller_project_ids=[]) == []
        contracts = DataContractsManager(data_dir=Path('/tmp'))
        assert [c.name for c in contracts.list_contracts_from_db(db, is_admin=True)] == ['orders']
        assert contracts.list_contracts_from_db(
            db, is_admin=False, caller_email='analyst@example.com', caller_team_ids=set()) == []


def test_update_matches_the_newest_version_and_keeps_deleted_ports_deleted(pg):
    job.create_products(pg, _objects('sales', 'p', _TABLES[:1]), 'skip', None, None)
    with pg.begin() as conn:
        # A newer draft version of the product (its own row, same family and name)
        conn.execute(text("""
            INSERT INTO data_products (id, api_version, kind, status, name, version,
                max_level_inheritance, version_family_id, published, publication_scope,
                created_at, updated_at)
            SELECT 'v2', api_version, kind, 'draft', name, '2.0.0', max_level_inheritance,
                version_family_id, published, publication_scope, :later, :later
            FROM data_products
        """), {'later': datetime.now(timezone.utc) + timedelta(days=1)})

    assert job.create_products(pg, _objects('sales', 'p'), 'update', None, None) == \
        _stats(updated=1)
    with pg.connect() as conn:
        # The first table was imported into the family: not added to v2 again
        assert conn.execute(text(
            "SELECT asset_identifier FROM data_product_output_ports WHERE product_id = 'v2'"
        )).scalars().all() == [_TABLES[1]]

    with pg.begin() as conn:
        conn.execute(text('DELETE FROM data_product_output_ports'))
    assert job.create_products(pg, _objects('sales', 'p'), 'update', None, None) == \
        _stats(unchanged=1)
    with pg.connect() as conn:
        assert conn.execute(text('SELECT COUNT(*) FROM data_product_output_ports')).scalar() == 0
