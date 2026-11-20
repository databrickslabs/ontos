"""Test the o3 migration (LLM_CHECK cache, usage, run counts, not_evaluated) through Alembic."""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

_NAME = 'o3_compliance_llm_check_cache'
_RUN_COLUMNS = {'llm_calls', 'llm_cache_hits', 'not_evaluated_count'}
_TABLES = {'compliance_llm_check_cache', 'compliance_llm_check_usage'}


@pytest.fixture
def migration():
    path = Path(__file__).resolve().parents[3] / 'alembic' / 'versions' / f'{_NAME}.py'
    spec = importlib.util.spec_from_file_location(_NAME, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _columns(conn, table):
    return {c['name'] for c in sa.inspect(conn).get_columns(table)}


def _apply(conn, step):
    with Operations.context(MigrationContext.configure(conn)):
        step()


def test_upgrade_adds_the_llm_check_tables_and_columns_and_downgrade_drops_them(
    tmp_path, migration,
):
    assert migration.down_revision == 'o2_step_execution_message'
    engine = create_engine(f"sqlite:///{tmp_path / 'o3.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE compliance_runs (id VARCHAR PRIMARY KEY)"))
        conn.execute(text(
            "CREATE TABLE compliance_results (id VARCHAR PRIMARY KEY, passed BOOLEAN)"
        ))
        conn.execute(text("INSERT INTO compliance_runs (id) VALUES ('r')"))
        conn.execute(text("INSERT INTO compliance_results (id, passed) VALUES ('x', 0)"))

        _apply(conn, migration.upgrade)
        assert _TABLES <= set(sa.inspect(conn).get_table_names())
        assert _RUN_COLUMNS <= _columns(conn, 'compliance_runs')
        assert {'response_model'} <= _columns(conn, 'compliance_llm_check_cache')
        # A result stored before the migration is evaluated, and a run's counts are unknown
        assert conn.execute(text("SELECT not_evaluated FROM compliance_results")).scalar() == 0
        assert conn.execute(text("SELECT llm_calls FROM compliance_runs")).scalar() is None

        _apply(conn, migration.downgrade)
        assert not _TABLES & set(sa.inspect(conn).get_table_names())
        assert not _RUN_COLUMNS & _columns(conn, 'compliance_runs')
        assert 'not_evaluated' not in _columns(conn, 'compliance_results')
        assert conn.execute(text("SELECT id FROM compliance_results")).scalar() == 'x'
