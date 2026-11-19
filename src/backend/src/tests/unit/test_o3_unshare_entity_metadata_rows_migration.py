"""Test the o3 migration (is_shared cleared on rows stored on an entity) through Alembic."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

_NAME = 'o3_unshare_entity_metadata_rows'
_TABLES = ('rich_text_metadata', 'link_metadata', 'document_metadata')


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


def test_upgrade_clears_the_flag_only_on_rows_stored_on_an_entity(tmp_path, migration):
    assert migration.down_revision == 'o2_step_execution_message'
    engine = create_engine(f"sqlite:///{tmp_path / 'o3.db'}")
    with engine.begin() as conn:
        for table in _TABLES:
            conn.execute(text(
                f"CREATE TABLE {table} (id VARCHAR PRIMARY KEY, entity_id VARCHAR, "
                "is_shared BOOLEAN)"
            ))
            conn.execute(text(
                f"INSERT INTO {table} VALUES ('library', '__shared__', 1), "
                "('legacy', 'asset-uuid', 1), ('own', 'asset-uuid', 0)"
            ))

        _apply(conn, migration.upgrade)

        for table in _TABLES:
            rows = dict(conn.execute(text(f"SELECT id, is_shared FROM {table}")).all())
            assert {k: bool(v) for k, v in rows.items()} == {
                'library': True, 'legacy': False, 'own': False,
            }, table

        _apply(conn, migration.downgrade)
        rows = dict(conn.execute(text("SELECT id, is_shared FROM rich_text_metadata")).all())
        assert {k: bool(v) for k, v in rows.items()} == {
            'library': True, 'legacy': False, 'own': False,
        }
