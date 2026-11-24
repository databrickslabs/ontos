"""Test the b10 migration (warning columns on compliance runs) through Alembic."""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

_NAME = 'b10_compliance_run_warning_code'


@pytest.fixture
def migration():
    path = Path(__file__).resolve().parents[3] / 'alembic' / 'versions' / f'{_NAME}.py'
    spec = importlib.util.spec_from_file_location(_NAME, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _columns(conn):
    return {c['name'] for c in sa.inspect(conn).get_columns('compliance_runs')}


def _apply(conn, step):
    with Operations.context(MigrationContext.configure(conn)):
        step()


def test_upgrade_adds_the_warning_columns_and_downgrade_drops_them(tmp_path, migration):
    assert migration.down_revision == 'b9_lifecycle_deprecation_fields'
    engine = create_engine(f"sqlite:///{tmp_path / 'b10.db'}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE compliance_runs (id VARCHAR PRIMARY KEY, status VARCHAR, "
            "error_message TEXT, error_code VARCHAR, error_params TEXT)"
        ))
        conn.execute(text("INSERT INTO compliance_runs (id, status) VALUES ('r', 'succeeded')"))

        _apply(conn, migration.upgrade)
        assert {'warning_code', 'warning_params'} <= _columns(conn)
        conn.execute(text(
            "UPDATE compliance_runs SET warning_code = 'rule_trailing_input', "
            "warning_params = '{\"line\": 1}'"
        ))
        row = conn.execute(text(
            "SELECT error_code, warning_code, warning_params FROM compliance_runs"
        )).one()
        assert tuple(row) == (None, 'rule_trailing_input', '{"line": 1}')

        _apply(conn, migration.downgrade)
        assert not {'warning_code', 'warning_params'} & _columns(conn)
        assert conn.execute(text("SELECT id FROM compliance_runs")).scalar() == 'r'
