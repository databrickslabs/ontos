"""Test the s1 migration (process_workflows.is_customized) through Alembic."""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

_NAME = 's1_workflow_is_customized'


@pytest.fixture
def migration():
    path = Path(__file__).resolve().parents[3] / 'alembic' / 'versions' / f'{_NAME}.py'
    spec = importlib.util.spec_from_file_location(_NAME, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _apply(conn, step):
    with Operations.context(MigrationContext.configure(conn)):
        step()


def test_upgrade_backfills_user_edited_defaults_and_downgrade_drops_the_column(tmp_path, migration):
    assert migration.down_revision == 'o1_merge_r1_c7'
    engine = create_engine(f"sqlite:///{tmp_path / 's1.db'}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE process_workflows (id VARCHAR PRIMARY KEY, is_default BOOLEAN, updated_by VARCHAR)"
        ))
        conn.execute(text(
            "INSERT INTO process_workflows VALUES "
            "('edited', 1, 'admin@example.com'), ('seeded', 1, 'system'), ('reset', 1, NULL), "
            "('blank', 1, ''), ('custom', 0, 'admin@example.com')"
        ))

        _apply(conn, migration.upgrade)
        rows = dict(conn.execute(text("SELECT id, is_customized FROM process_workflows")).all())
        assert {k: bool(v) for k, v in rows.items()} == {
            'edited': True, 'seeded': False, 'reset': False, 'blank': False, 'custom': False,
        }

        _apply(conn, migration.downgrade)
        assert 'is_customized' not in {c['name'] for c in sa.inspect(conn).get_columns('process_workflows')}
