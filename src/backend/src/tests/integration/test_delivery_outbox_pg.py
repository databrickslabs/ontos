"""The delivery outbox on Postgres (#1688): row claims across app instances, the migration.

Each worker stands for an app instance: its own engine and connections on a
shared database, so ``SELECT ... FOR UPDATE SKIP LOCKED`` is the only thing that
keeps two of them from delivering the same row. SQLite has no row locks, so these
tests run only when ``SCHEDULER_TEST_PG_URL`` points at a Postgres database (they
work in a throwaway schema dropped afterwards) and are skipped otherwise::

    SCHEDULER_TEST_PG_URL=postgresql+psycopg2://user:pw@localhost:5432/db \\
        hatch -e dev run pytest src/tests/integration/test_delivery_outbox_pg.py
"""
import importlib.util
import os
import threading
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.common.database import Base
from src.controller.delivery_outbox_manager import DeliveryOutboxWorker
from src.controller.delivery_service import DeliveryResult, DeliveryResults
from src.db_models.data_products import DataProductDb
from src.db_models.delivery_outbox import DeliveryOutboxDb
from src.repositories.delivery_outbox_repository import delivery_outbox_repo

UTC = timezone.utc
_PG_URL = os.environ.get('SCHEDULER_TEST_PG_URL')

pytestmark = pytest.mark.skipif(not _PG_URL, reason='SCHEDULER_TEST_PG_URL not set')


@pytest.fixture
def schema():
    name = f'outbox_it_{uuid.uuid4().hex[:8]}'
    admin = create_engine(_PG_URL)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{name}"'))
    engines = []

    def instance():
        engine = create_engine(_PG_URL, connect_args={'options': f'-csearch_path={name}'})
        engines.append(engine)
        return sessionmaker(bind=engine, autoflush=False)

    try:
        yield instance
    finally:
        for engine in engines:
            engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{name}" CASCADE'))
        admin.dispose()


@pytest.fixture
def database(schema):
    sessions = schema()
    Base.metadata.create_all(sessions.kw['bind'])
    return schema, sessions


class _SlowService:
    """Delivers every mode after a short wait, counting the rows it delivered."""

    def __init__(self):
        self.lock = threading.Lock()
        self.delivered = Counter()

    def get_active_modes(self):
        return ['indirect']

    def deliver(self, payload, modes=None):
        time.sleep(0.05)
        with self.lock:
            self.delivered[payload.entity_id] += 1
        results = DeliveryResults()
        for mode in modes:
            results.add(DeliveryResult(
                success=True, mode=mode, change_type=payload.change_type,
                entity_type=payload.entity_type, entity_id=payload.entity_id,
            ))
        return results


def _rows(sessions, count):
    """``count`` products, each with a due pending row; the row ids."""
    db = sessions()
    try:
        past = datetime.now(UTC) - timedelta(minutes=5)
        ids = []
        for index in range(count):
            product = DataProductDb(
                id=str(uuid.uuid4()), name=f'P {index}', status='draft',
                version_family_id=str(uuid.uuid4()),
            )
            db.add(product)
            db.flush()
            ids.append(delivery_outbox_repo.add(
                db, entity_type='DataProduct', entity_id=product.id,
                change_type='product_create', mode='indirect', queued_by='a@b.com',
                next_attempt_at=past,
            ).id)
        db.commit()
        return ids
    finally:
        db.close()


def test_a_row_another_session_holds_is_skipped(database):
    _, sessions = database
    row_id = _rows(sessions, 1)[0]
    holder, other = sessions(), sessions()
    try:
        assert delivery_outbox_repo.claim_next_due(holder, datetime.now(UTC)).id == row_id
        assert delivery_outbox_repo.claim_next_due(other, datetime.now(UTC)) is None
        assert delivery_outbox_repo.claim(other, row_id) is None
        other.rollback()
        holder.rollback()  # the lock is released
        assert delivery_outbox_repo.claim(other, row_id).id == row_id
    finally:
        holder.close()
        other.close()


def test_two_instances_deliver_each_row_once(database, monkeypatch):
    schema, sessions = database
    row_ids = _rows(sessions, 8)
    service = _SlowService()
    monkeypatch.setattr('src.controller.delivery_service.get_delivery_service', lambda: service)
    instances = [schema(), schema()]
    barrier = threading.Barrier(len(instances))
    tried = []

    def run(instance_sessions):
        barrier.wait()
        tried.append(DeliveryOutboxWorker().run(instance_sessions, datetime.now(UTC)))

    threads = [threading.Thread(target=run, args=(s,)) for s in instances]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert sum(tried) == len(row_ids)
    assert all(tried), 'both instances took rows'
    assert set(service.delivered.values()) == {1}
    db = sessions()
    try:
        statuses = {row.status for row in db.query(DeliveryOutboxDb).all()}
    finally:
        db.close()
    assert statuses == {'delivered'}


def _migration():
    name = 'b13_delivery_outbox'
    path = Path(__file__).resolve().parents[3] / 'alembic' / 'versions' / f'{name}.py'
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migration_upgrades_downgrades_and_upgrades_again(schema):
    migration = _migration()
    engine = schema().kw['bind']

    def apply(step):
        with engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                step()

    def indexes():
        inspector = sa.inspect(engine)
        if 'delivery_outbox' not in inspector.get_table_names():
            return None
        return {index['name'] for index in inspector.get_indexes('delivery_outbox')}

    apply(migration.upgrade)
    created = indexes()
    apply(migration.upgrade)  # a retried upgrade
    assert indexes() == created == {
        'ix_delivery_outbox_status_next_attempt', 'ix_delivery_outbox_entity'}
    apply(migration.downgrade)
    assert indexes() is None
    apply(migration.upgrade)
    assert indexes() == created
