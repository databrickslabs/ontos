"""Migration o4 indexes notifications for the #1527 queries (#1638)."""
import importlib.util
import io
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateIndex

from src.db_models.notifications import NotificationDb

_NAME = 'o4_notifications_indexes'
_EXPECTED = {
    'ix_notifications_action_type_read': ['action_type', 'read'],
    'ix_notifications_created_at_id': ['created_at', 'id'],
}


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
    with engine.begin() as conn:
        for name in _EXPECTED:
            conn.exec_driver_sql(f'DROP INDEX {name}')
    return engine


def _indexes(engine) -> dict:
    return {i['name']: i['column_names'] for i in inspect(engine).get_indexes('notifications')}


def _run(engine, step):
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            step()


def test_it_sits_on_the_current_head(migration):
    assert migration.down_revision == 'o3_canonical_cost_centers'


def test_upgrade_creates_the_indexes_and_downgrade_drops_them(migration, engine):
    assert not set(_EXPECTED) & set(_indexes(engine))

    _run(engine, migration.upgrade)
    found = _indexes(engine)
    assert {name: found[name] for name in _EXPECTED} == _EXPECTED

    _run(engine, migration.downgrade)
    assert not set(_EXPECTED) & set(_indexes(engine))


def test_both_steps_can_be_retried(migration, engine):
    _run(engine, migration.upgrade)
    _run(engine, migration.upgrade)
    assert set(_EXPECTED) <= set(_indexes(engine))

    _run(engine, migration.downgrade)
    _run(engine, migration.downgrade)
    assert not set(_EXPECTED) & set(_indexes(engine))


def _postgres_script(step) -> str:
    out = io.StringIO()
    context = MigrationContext.configure(
        dialect_name='postgresql', opts={'as_sql': True, 'output_buffer': out},
    )
    with Operations.context(context):
        step()
    return out.getvalue()


def test_postgres_builds_concurrently_outside_a_transaction(migration):
    script = _postgres_script(migration.upgrade)

    assert ('CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_notifications_action_type_read '
            'ON notifications (action_type, read);') in script
    assert ('CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_notifications_created_at_id '
            'ON notifications (created_at, id);') in script
    # each statement is preceded by a COMMIT: CONCURRENTLY cannot run in a transaction block
    for name in _EXPECTED:
        before = script.split(f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {name}')[0]
        assert before.rstrip().endswith('COMMIT;')


def test_postgres_downgrade_drops_concurrently_and_idempotently(migration):
    script = _postgres_script(migration.downgrade)

    for name in _EXPECTED:
        assert f'DROP INDEX CONCURRENTLY IF EXISTS {name};' in script


def test_the_model_metadata_declares_the_same_indexes():
    declared = {i.name: [c.name for c in i.columns] for i in NotificationDb.__table__.indexes}
    assert {name: declared[name] for name in _EXPECTED} == _EXPECTED


def test_the_model_indexes_compile_to_postgres_ddl():
    ddl = {
        i.name: str(CreateIndex(i).compile(dialect=postgresql.dialect()))
        for i in NotificationDb.__table__.indexes if i.name in _EXPECTED
    }
    assert 'ON notifications (action_type, read)' in ddl['ix_notifications_action_type_read']
    assert 'ON notifications (created_at, id)' in ddl['ix_notifications_created_at_id']
