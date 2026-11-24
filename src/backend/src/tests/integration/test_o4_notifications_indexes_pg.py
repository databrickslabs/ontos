"""Local-Postgres test of the o4 notifications indexes migration (#1638, #1666 review).

``o4_notifications_indexes`` builds its indexes with ``CREATE INDEX CONCURRENTLY`` inside
Alembic's ``autocommit_block`` and must survive a retry after a failed build. SQLite cannot
exercise that, so this module runs the migration on Postgres and **auto-skips** when no
database is configured, so it is safe in CI.

To run it, point it at a throwaway Postgres via ``NOTIFICATIONS_TEST_PG_URL``::

    NOTIFICATIONS_TEST_PG_URL=postgresql+psycopg2://user:pw@localhost:5432/db \\
        hatch -e dev run pytest src/tests/integration/test_o4_notifications_indexes_pg.py
"""
import importlib.util
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from src.db_models.notifications import NotificationDb

_PG_URL = os.environ.get('NOTIFICATIONS_TEST_PG_URL')
_NAME = 'o4_notifications_indexes'
_ACTION = 'ix_notifications_action_type_read'
_CREATED = 'ix_notifications_created_at_id'
_STATE = (
    'SELECT c.oid, i.indisvalid, i.indisunique FROM pg_index i '
    'JOIN pg_class c ON c.oid = i.indexrelid WHERE c.oid = to_regclass(:name)'
)


@pytest.fixture(scope='module')
def migration():
    path = Path(__file__).resolve().parents[3] / 'alembic' / 'versions' / f'{_NAME}.py'
    spec = importlib.util.spec_from_file_location(_NAME, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=['transaction', 'autocommit'])
def engine(request):
    """An engine on a fresh, index-free notifications table in a throwaway schema.

    ``transaction`` is how the app migrates (``alembic upgrade head`` in a subprocess);
    ``autocommit`` is the dedicated AUTOCOMMIT engine ``alembic/env.py`` can also build.
    """
    if not _PG_URL:
        pytest.skip('NOTIFICATIONS_TEST_PG_URL not set: Postgres migration test skipped')
    schema = f'o4_it_{uuid.uuid4().hex[:8]}'
    admin = create_engine(_PG_URL, future=True)
    try:
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    except Exception as e:  # pragma: no cover - environment dependent
        admin.dispose()
        pytest.skip(f'Postgres not reachable at NOTIFICATIONS_TEST_PG_URL: {e}')
    options = {'isolation_level': 'AUTOCOMMIT'} if request.param == 'autocommit' else {}
    engine = create_engine(
        _PG_URL, future=True, connect_args={'options': f'-csearch_path={schema}'}, **options,
    )
    NotificationDb.__table__.create(bind=engine)
    with engine.begin() as conn:
        conn.execute(text(f'DROP INDEX {_ACTION}'))
        conn.execute(text(f'DROP INDEX {_CREATED}'))
        conn.execute(text(
            "INSERT INTO notifications (id, type, title, read, can_delete, action_type) "
            "SELECT g::text, 'info', 't', false, true, 'a' FROM generate_series(1, 50) g"
        ))
    engine.test_schema = schema
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _run(engine, step):
    with engine.connect() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            step()


def _state(engine, name):
    with engine.connect() as conn:
        row = conn.execute(text(_STATE), {'name': name}).first()
    return None if row is None else tuple(row)


def test_upgrade_downgrade_upgrade(migration, engine):
    _run(engine, migration.upgrade)
    assert _state(engine, _ACTION)[1] is True
    assert _state(engine, _CREATED)[1] is True

    _run(engine, migration.downgrade)
    assert _state(engine, _ACTION) is None
    assert _state(engine, _CREATED) is None

    _run(engine, migration.upgrade)
    assert _state(engine, _ACTION)[1] is True
    assert _state(engine, _CREATED)[1] is True


def test_a_valid_index_is_left_alone(migration, engine):
    _run(engine, migration.upgrade)
    before = _state(engine, _ACTION), _state(engine, _CREATED)

    _run(engine, migration.upgrade)

    assert (_state(engine, _ACTION), _state(engine, _CREATED)) == before


def _failing_build(engine, name):
    """A CONCURRENTLY build that fails on duplicates and leaves an INVALID index ``name``."""
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
        conn.execute(text(
            f'CREATE UNIQUE INDEX CONCURRENTLY {name} ON notifications (action_type)'
        ))


def _break_build(engine, name):
    """Leave an INVALID index named ``name``, as an interrupted CONCURRENTLY build does."""
    with pytest.raises(Exception, match='could not create unique index'):
        _failing_build(engine, name)
    assert _state(engine, name)[1] is False


def test_an_invalid_index_is_rebuilt(migration, engine):
    _break_build(engine, _ACTION)
    broken_oid = _state(engine, _ACTION)[0]

    _run(engine, migration.upgrade)

    oid, valid, unique = _state(engine, _ACTION)
    assert valid is True and unique is False and oid != broken_oid
    assert _state(engine, _CREATED)[1] is True


def test_a_rerun_recovers_when_the_second_build_fails(migration, engine, monkeypatch):
    real = migration.op.create_index
    calls = []

    def second_build_fails(name, *args, **kwargs):
        calls.append(name)
        if len(calls) == 2:
            _failing_build(engine, name)
        return real(name, *args, **kwargs)

    monkeypatch.setattr(migration.op, 'create_index', second_build_fails)
    with pytest.raises(Exception, match='could not create unique index'):
        _run(engine, migration.upgrade)
    monkeypatch.undo()
    first = _state(engine, _ACTION)
    assert first[1] is True and _state(engine, _CREATED)[1] is False

    _run(engine, migration.upgrade)

    assert _state(engine, _ACTION) == first
    oid, valid, unique = _state(engine, _CREATED)
    assert valid is True and unique is False


def _env_py_config(engine, script_location):
    cfg = Config()
    cfg.set_main_option('script_location', str(script_location))
    cfg.attributes['engine'] = create_engine(_PG_URL, future=True)
    cfg.attributes['target_schema'] = engine.test_schema
    return cfg


@pytest.fixture
def autocommit_block_states(monkeypatch):
    """Record, at each ``autocommit_block()``, whether a transaction is open and Alembic's."""
    states = []
    real = MigrationContext.autocommit_block

    def spy(self):
        states.append((self.connection.in_transaction(), self._transaction is not None))
        return real(self)

    monkeypatch.setattr(MigrationContext, 'autocommit_block', spy)
    return states


def _assert_alembic_owned(states):
    """A transaction may be open, but it must be one Alembic began (``_transaction`` set)."""
    assert states
    assert all(owned for in_transaction, owned in states if in_transaction)


def test_it_runs_through_env_py_with_a_target_schema(migration, engine, autocommit_block_states):
    """``alembic/env.py`` sets the search_path on its AUTOCOMMIT engine before configuring.

    SQLAlchemy autobegins on that statement; if env.py left it open, Alembic's
    ``autocommit_block`` would hit an AssertionError. This drives the real env.py.
    """
    backend = Path(__file__).resolve().parents[3]
    cfg = _env_py_config(engine, backend / 'alembic')
    command.stamp(cfg, migration.down_revision)

    command.upgrade(cfg, 'head')

    _assert_alembic_owned(autocommit_block_states)
    assert _state(engine, _ACTION)[1] is True
    assert _state(engine, _CREATED)[1] is True
    with engine.connect() as conn:
        assert conn.execute(text('SELECT version_num FROM alembic_version')).scalar() == _NAME


def test_it_runs_through_env_py_after_other_pending_revisions(
    migration, engine, autocommit_block_states, tmp_path,
):
    """Same, on a database where two revisions run before o4 (the version table is read first)."""
    backend = Path(__file__).resolve().parents[3]
    script_dir = tmp_path / 'alembic'
    (script_dir / 'versions').mkdir(parents=True)
    for name in ('env.py', 'script.py.mako'):
        (script_dir / name).write_bytes((backend / 'alembic' / name).read_bytes())
    for name, parent in (('x1', None), ('x2', 'x1')):
        (script_dir / 'versions' / f'{name}.py').write_text(
            f"revision = {name!r}\ndown_revision = {parent!r}\n"
            "from alembic import op\n\n\ndef upgrade():\n    op.execute('SELECT 1')\n\n\n"
            "def downgrade():\n    pass\n"
        )
    source = (backend / 'alembic' / 'versions' / f'{_NAME}.py').read_text()
    (script_dir / 'versions' / f'{_NAME}.py').write_text(
        source.replace(repr(migration.down_revision), "'x2'")
    )

    command.upgrade(_env_py_config(engine, script_dir), 'head')

    _assert_alembic_owned(autocommit_block_states)
    assert _state(engine, _ACTION)[1] is True and _state(engine, _CREATED)[1] is True
    with engine.connect() as conn:
        assert conn.execute(text('SELECT version_num FROM alembic_version')).scalar() == _NAME
