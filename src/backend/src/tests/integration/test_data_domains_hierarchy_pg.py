"""Domain parent changes from two sessions at once, on a real Postgres (#1667).

The parent check reads the ancestor chain before the write. Without a lock,
two reciprocal moves (A under B, B under A) would both pass the check and
store a loop. ``DataDomainRepository.lock_hierarchy`` takes a transaction
advisory lock first; these tests hold it in one session and check that the
other one waits, then sees the committed link.

SQLite has no advisory locks (the lock is a no-op there), so this module
**auto-skips** without Postgres. CI sets ``UC_BULK_IMPORT_TEST_PG_URL``;
locally point ``DOMAIN_HIERARCHY_TEST_PG_URL`` (or one of the other
``*_TEST_PG_URL`` variables) at a throwaway database. Each test builds the
app's tables in its own schema and drops it afterwards.
"""
import os
import threading
import time
import uuid
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.common.database import Base
import src.db_models  # noqa: F401  (registers every table on Base.metadata)
import src.repositories.data_domain_repository as domain_repo_module
from src.controller.data_domains_manager import DataDomainManager, DomainParentCycleError
from src.db_models.data_domains import DataDomain
from src.models.data_domains import DataDomainCreate, DataDomainUpdate
from src.repositories.data_domain_repository import data_domain_repo

_PG_URL = (
    os.environ.get('DOMAIN_HIERARCHY_TEST_PG_URL')
    or os.environ.get('UC_BULK_IMPORT_TEST_PG_URL')
    or os.environ.get('SCHEDULER_TEST_PG_URL')
    or os.environ.get('SEARCH_TEST_PG_URL')
)
_WAIT_S = 10


def _check_pg_or_skip():
    if not _PG_URL:
        pytest.skip('No *_TEST_PG_URL set: the advisory lock only exists on Postgres')
    try:
        eng = create_engine(_PG_URL)
        with eng.connect() as c:
            c.execute(text('SELECT 1'))
        eng.dispose()
    except Exception as e:  # pragma: no cover - environment dependent
        pytest.skip(f'Postgres not reachable: {e}')


@pytest.fixture()
def pg():
    """An engine whose connections use a fresh schema holding the app's tables."""
    _check_pg_or_skip()
    admin = create_engine(_PG_URL)
    schema = f'domain_hier_it_{uuid.uuid4().hex[:8]}'
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
        admin.dispose()


@pytest.fixture(autouse=True)
def lock_key(monkeypatch):
    # Advisory locks are database-wide: a key per test keeps parallel runs apart
    key = 7_000_000_000 + uuid.uuid4().int % 1_000_000_000
    monkeypatch.setattr(domain_repo_module, 'HIERARCHY_LOCK_KEY', key)
    return key


def _roots(engine, *names):
    with Session(bind=engine) as db:
        ids = []
        for name in names:
            domain = DataDomain(id=str(uuid.uuid4()), name=name, created_by='t@example.com')
            db.add(domain)
            ids.append(domain.id)
        db.commit()
    return ids


def _parent_of(engine, domain_id):
    with Session(bind=engine) as db:
        return db.query(DataDomain.parent_id).filter(DataDomain.id == domain_id).scalar()


def _wait_until_blocked(engine, pid):
    """Wait until backend ``pid`` waits for an advisory lock; False on timeout."""
    deadline = time.monotonic() + _WAIT_S
    with engine.connect() as conn:
        while time.monotonic() < deadline:
            waiting = conn.execute(text(
                "SELECT count(*) FROM pg_locks "
                "WHERE locktype = 'advisory' AND NOT granted AND pid = :pid"
            ), {'pid': pid}).scalar()
            if waiting:
                return True
            conn.rollback()
            time.sleep(0.05)
    return False


def _in_thread(fn):
    """Run ``fn`` in a thread; the returned dict gets ``result`` or ``error``."""
    out = {}

    def run():
        try:
            out['result'] = fn()
        except Exception as e:  # noqa: BLE001 - the test inspects it
            out['error'] = e

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, out


def _pid(db):
    return db.execute(text('SELECT pg_backend_pid()')).scalar()


def test_reciprocal_moves_one_wins_the_other_is_refused(pg):
    """A under B and B under A at the same time: exactly one is stored."""
    a_id, b_id = _roots(pg, 'A', 'B')
    manager = DataDomainManager(repository=data_domain_repo)
    first, second = Session(bind=pg), Session(bind=pg)
    try:
        # First session moves A under B and keeps its transaction (and the lock) open
        manager.update_domain(first, UUID(a_id), DataDomainUpdate(parent_id=UUID(b_id)), 'u1')
        second_pid = _pid(second)

        thread, out = _in_thread(lambda: manager.update_domain(
            second, UUID(b_id), DataDomainUpdate(parent_id=UUID(a_id)), 'u2'))
        assert _wait_until_blocked(pg, second_pid), 'the second move did not wait for the lock'

        first.commit()
        thread.join(_WAIT_S)
        assert not thread.is_alive()
        assert isinstance(out.get('error'), DomainParentCycleError), out
        assert out['error'].code == 'domain_parent_cycle'
        second.rollback()
    finally:
        first.close()
        second.close()

    assert _parent_of(pg, a_id) == b_id
    assert _parent_of(pg, b_id) is None


def test_lock_is_released_by_rollback_and_covers_create_with_parent(pg):
    """A create with a parent waits for the lock too, and a rollback releases it."""
    (root_id,) = _roots(pg, 'Root')
    manager = DataDomainManager(repository=data_domain_repo)
    holder, creator = Session(bind=pg), Session(bind=pg)
    try:
        data_domain_repo.lock_hierarchy(holder)
        creator_pid = _pid(creator)

        thread, out = _in_thread(lambda: manager.create_domain(
            creator, DataDomainCreate(name='Child', parent_id=UUID(root_id)), 'u2'))
        assert _wait_until_blocked(pg, creator_pid), 'the create did not wait for the lock'

        holder.rollback()
        thread.join(_WAIT_S)
        assert not thread.is_alive()
        assert 'error' not in out, out
        creator.commit()
    finally:
        holder.close()
        creator.close()

    with Session(bind=pg) as db:
        child = db.query(DataDomain).filter(DataDomain.name == 'Child').one()
        assert child.parent_id == root_id


def test_lock_is_a_noop_on_sqlite():
    """SQLite runs one writer at a time and has no advisory locks: nothing is sent."""
    engine = create_engine('sqlite://')
    with Session(bind=engine) as db:
        data_domain_repo.lock_hierarchy(db)
        assert not db.in_transaction()
