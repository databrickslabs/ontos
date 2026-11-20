"""Test the s2 migration (imported Markdown documents) through Alembic."""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

_NAME = 's2_document_markdown_import'


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


def _insert(conn, doc_id, source_path, entity_id='d1'):
    conn.execute(text(
        "INSERT INTO document_metadata (id, entity_type, entity_id, source_path) "
        "VALUES (:id, 'data_domain', :entity_id, :source_path)"
    ), {'id': doc_id, 'entity_id': entity_id, 'source_path': source_path})


def test_one_imported_document_per_file_and_entity(tmp_path, migration):
    assert migration.down_revision == 'c8_workflow_scheduler_claims'
    engine = create_engine(f"sqlite:///{tmp_path / 's2.db'}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE document_metadata (id VARCHAR PRIMARY KEY, entity_type VARCHAR, "
            "entity_id VARCHAR)"
        ))
        _apply(conn, migration.upgrade)
        _insert(conn, 'a', '/Volumes/c/s/v/a.md')
        _insert(conn, 'b', '/Volumes/c/s/v/a.md', entity_id='d2')  # another entity
        _insert(conn, 'u1', None)  # uploads have no source: never unique
        _insert(conn, 'u2', None)
        with pytest.raises(sa.exc.IntegrityError):
            with conn.begin_nested():
                _insert(conn, 'dup', '/Volumes/c/s/v/a.md')

        # The text once per file version
        def store(digest):
            conn.execute(text(
                "INSERT INTO imported_markdown_files (source_path, content_hash, content_text) "
                "VALUES ('/Volumes/c/s/v/a.md', :digest, 'body')"), {'digest': digest})
        store('h')
        store('h2')  # another version of the same file
        with pytest.raises(sa.exc.IntegrityError):
            with conn.begin_nested():
                store('h')
        columns = {c['name'] for c in sa.inspect(conn).get_columns('document_metadata')}
        assert 'content_text' not in columns

        _apply(conn, migration.downgrade)
        columns = {c['name'] for c in sa.inspect(conn).get_columns('document_metadata')}
        assert not columns & {'source_path', 'content_hash'}
        assert 'imported_markdown_files' not in sa.inspect(conn).get_table_names()
