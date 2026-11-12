"""Test the b7 migration (a step result outlives its step) through Alembic.

SQLite can't alter or drop constraints in place, so the three operations the
migration uses for that (``drop_constraint``, ``create_foreign_key`` and
``alter_column``) go through Alembic's batch mode here, which rebuilds the table;
everything else (the column adds, the backfill, the reflection of the foreign
keys, the ``DELETE`` in ``downgrade``) is the migration's own code. The foreign
key name and the ``ON DELETE`` rule are real and checked from the reflected schema.
"""
import importlib.util
import tempfile
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import op as real_op
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import StaticPool

_TABLE = 'workflow_step_executions'
_FK = 'workflow_step_executions_step_id_fkey'
_CONVENTION = {'fk': 'fk_%(table_name)s_%(column_0_name)s'}


class _BatchOp:
    """``op`` with the constraint operations SQLite lacks done in batch mode."""

    def __getattr__(self, name):
        return getattr(real_op, name)

    def drop_constraint(self, name, table, type_=None):
        with real_op.batch_alter_table(table, naming_convention=_CONVENTION) as batch:
            batch.drop_constraint(name, type_=type_)

    def create_foreign_key(self, name, table, referent, local_cols, remote_cols, ondelete=None):
        with real_op.batch_alter_table(table) as batch:
            batch.create_foreign_key(name, referent, local_cols, remote_cols, ondelete=ondelete)

    def alter_column(self, table, column, existing_type=None, nullable=None):
        with real_op.batch_alter_table(table) as batch:
            batch.alter_column(column, existing_type=existing_type, nullable=nullable)


@pytest.fixture
def engine():
    db_file = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
    db_file.close()
    eng = create_engine(
        f'sqlite:///{db_file.name}',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )

    @event.listens_for(eng, 'connect')
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute('PRAGMA foreign_keys=ON')

    yield eng
    Path(db_file.name).unlink(missing_ok=True)


@pytest.fixture
def migration(monkeypatch):
    backend_dir = Path(__file__).resolve().parents[3]
    path = backend_dir / 'alembic' / 'versions' / 'b7_workflow_step_results_kept.py'
    assert path.exists(), f'Migration not found at {path}'
    spec = importlib.util.spec_from_file_location('b7_workflow_step_results_kept', path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, 'op', _BatchOp())
    return mod


def _pre_b7_schema(conn) -> None:
    conn.execute(text("CREATE TABLE workflow_executions (id TEXT PRIMARY KEY)"))
    conn.execute(text("""
        CREATE TABLE workflow_steps (
            id TEXT PRIMARY KEY, step_id VARCHAR(100) NOT NULL, name VARCHAR(255)
        )
    """))
    conn.execute(text(f"""
        CREATE TABLE {_TABLE} (
            id TEXT PRIMARY KEY,
            execution_id TEXT NOT NULL REFERENCES workflow_executions (id) ON DELETE CASCADE,
            step_id TEXT NOT NULL,
            passed BOOLEAN,
            CONSTRAINT {_FK} FOREIGN KEY (step_id) REFERENCES workflow_steps (id)
                ON DELETE CASCADE
        )
    """))
    conn.execute(text("INSERT INTO workflow_executions (id) VALUES ('e1')"))
    conn.execute(text("""
        INSERT INTO workflow_steps (id, step_id, name) VALUES
            ('s1', 'check', 'Check the data'), ('s2', 'approve', 'Approval')
    """))
    conn.execute(text(f"""
        INSERT INTO {_TABLE} (id, execution_id, step_id, passed) VALUES
            ('r1', 'e1', 's1', 1), ('r2', 'e1', 's2', 0)
    """))


def _run(engine, fn) -> None:
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            fn()


def _step_id_fk(conn):
    fks = [
        fk for fk in sa.inspect(conn).get_foreign_keys(_TABLE)
        if fk['constrained_columns'] == ['step_id']
    ]
    assert len(fks) == 1
    return fks[0]


def _columns(conn) -> dict:
    return {c['name']: c for c in sa.inspect(conn).get_columns(_TABLE)}


def test_upgrade_backfills_and_keeps_results_of_removed_steps(engine, migration):
    with engine.begin() as conn:
        _pre_b7_schema(conn)

    _run(engine, migration.upgrade)

    with engine.begin() as conn:
        rows = conn.execute(text(
            f"SELECT id, step_id, step_key, step_name FROM {_TABLE} ORDER BY id"
        )).fetchall()
        assert [tuple(r) for r in rows] == [
            ('r1', 's1', 'check', 'Check the data'),
            ('r2', 's2', 'approve', 'Approval'),
        ]
        assert _columns(conn)['step_id']['nullable'] is True
        fk = _step_id_fk(conn)
        assert fk['name'] == _FK
        assert fk['options']['ondelete'].upper() == 'SET NULL'

        # The observable effect: deleting a step keeps its result
        conn.execute(text("DELETE FROM workflow_steps WHERE id = 's1'"))
        kept = conn.execute(text(
            f"SELECT step_id, step_key, step_name FROM {_TABLE} WHERE id = 'r1'"
        )).one()
        assert tuple(kept) == (None, 'check', 'Check the data')


def test_a_second_upgrade_changes_nothing(engine, migration):
    with engine.begin() as conn:
        _pre_b7_schema(conn)
    _run(engine, migration.upgrade)
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE {_TABLE} SET step_name = 'Renamed' WHERE id = 'r1'"))
        conn.execute(text("DELETE FROM workflow_steps WHERE id = 's2'"))

    _run(engine, migration.upgrade)

    with engine.begin() as conn:
        rows = conn.execute(text(
            f"SELECT id, step_id, step_key, step_name FROM {_TABLE} ORDER BY id"
        )).fetchall()
        assert [tuple(r) for r in rows] == [
            ('r1', 's1', 'check', 'Renamed'),
            ('r2', None, 'approve', 'Approval'),
        ]
        fk = _step_id_fk(conn)
        assert fk['options']['ondelete'].upper() == 'SET NULL'
        assert _columns(conn)['step_id']['nullable'] is True


def test_downgrade_drops_removed_step_results_and_the_columns(engine, migration):
    with engine.begin() as conn:
        _pre_b7_schema(conn)
    _run(engine, migration.upgrade)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM workflow_steps WHERE id = 's1'"))

    _run(engine, migration.downgrade)

    with engine.begin() as conn:
        assert [r[0] for r in conn.execute(text(f"SELECT id FROM {_TABLE}"))] == ['r2']
        columns = _columns(conn)
        assert 'step_key' not in columns and 'step_name' not in columns
        assert columns['step_id']['nullable'] is False
        fk = _step_id_fk(conn)
        assert fk['options']['ondelete'].upper() == 'CASCADE'
