"""Test the o4 migration (library documents uploaded without is_shared) through Alembic."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

_NAME = 'o4_shared_library_documents'


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


def test_upgrade_flags_only_documents_in_the_shared_folder(tmp_path, migration):
    assert migration.down_revision == 'o3_canonical_cost_centers'
    engine = create_engine(f"sqlite:///{tmp_path / 'o4.db'}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE document_metadata (id VARCHAR PRIMARY KEY, entity_id VARCHAR, "
            "is_shared BOOLEAN, storage_path VARCHAR)"
        ))
        conn.execute(text(
            "INSERT INTO document_metadata VALUES "
            "('uploaded', '__shared__', 0, '/Volumes/c/s/v/uploads/__shared__/a.pdf'), "
            "('library', '__shared__', 1, '/Volumes/c/s/v/uploads/__shared__/b.pdf'), "
            "('entity_route', '__shared__', 0, '/Volumes/c/s/v/uploads/data_domain/__shared__/c.pdf'), "
            "('own', 'asset-uuid', 0, '/Volumes/c/s/v/uploads/asset/asset-uuid/d.pdf')"
        ))

        _apply(conn, migration.upgrade)

        rows = dict(conn.execute(text("SELECT id, is_shared FROM document_metadata")).all())
        assert {k: bool(v) for k, v in rows.items()} == {
            'uploaded': True, 'library': True, 'entity_route': False, 'own': False,
        }
