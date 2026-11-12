"""Test the t1 migration (backfill contract tag assignments from ODCS tag rows) through Alembic."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

_NAME = 't1_contract_tag_backfill'


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


def _schema(conn, with_default_namespace=True):
    conn.execute(text("CREATE TABLE data_contract_tags (id VARCHAR PRIMARY KEY, contract_id VARCHAR, name VARCHAR)"))
    conn.execute(text(
        "CREATE TABLE tag_namespaces (id VARCHAR PRIMARY KEY, name VARCHAR UNIQUE, description VARCHAR, created_by VARCHAR)"
    ))
    conn.execute(text(
        "CREATE TABLE tags (id VARCHAR PRIMARY KEY, name VARCHAR, status VARCHAR, namespace_id VARCHAR, created_by VARCHAR)"
    ))
    conn.execute(text(
        "CREATE TABLE entity_tag_associations (id VARCHAR PRIMARY KEY, tag_id VARCHAR, entity_id VARCHAR, "
        "entity_type VARCHAR, assigned_value VARCHAR, assigned_by VARCHAR)"
    ))
    conn.execute(text("INSERT INTO tag_namespaces VALUES ('ns-gov', 'governance', NULL, 'seed')"))
    if with_default_namespace:
        conn.execute(text("INSERT INTO tag_namespaces VALUES ('ns-default', 'default', NULL, 'seed')"))


def _assignments(conn):
    return sorted(conn.execute(text(
        "SELECT a.entity_id, n.name, t.name, a.assigned_value, a.assigned_by FROM entity_tag_associations a "
        "JOIN tags t ON t.id = a.tag_id JOIN tag_namespaces n ON n.id = t.namespace_id "
        "WHERE a.entity_type = 'data_contract'"
    )).all())


def test_upgrade_assigns_the_odcs_tags(tmp_path, migration):
    assert migration.down_revision == 's1_workflow_is_customized'
    assert len(migration.revision) <= 32  # alembic_version.version_num is varchar(32) on Postgres
    engine = create_engine(f"sqlite:///{tmp_path / 't1.db'}")
    with engine.begin() as conn:
        _schema(conn)
        conn.execute(text("INSERT INTO tags VALUES ('t-pii', 'pii', 'active', 'ns-default', 'seed')"))
        # c2 already has pii with a value set on the page: it stays as it is.
        conn.execute(text(
            "INSERT INTO entity_tag_associations VALUES ('a1', 't-pii', 'c2', 'data_contract', 'high', 'alice')"
        ))
        conn.execute(text(
            "INSERT INTO data_contract_tags VALUES "
            "('r1', 'c1', 'pii'), ('r2', 'c1', 'finance'), ('r3', 'c1', 'governance/restricted'), "
            "('r4', 'c1', 'nowhere/x'), ('r5', 'c2', 'pii'), ('r6', 'c2', '  '), ('r7', 'c1', 'pii')"
        ))

        _apply(conn, migration.upgrade)

        assert _assignments(conn) == [
            ('c1', 'default', 'finance', None, 'system'),
            ('c1', 'default', 'pii', None, 'system'),
            ('c1', 'governance', 'restricted', None, 'system'),
            ('c2', 'default', 'pii', 'high', 'alice'),
        ]
        # The existing tag is reused; finance and restricted are created.
        assert conn.execute(text("SELECT COUNT(*) FROM tags WHERE name = 'pii'")).scalar() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM data_contract_tags")).scalar() == 7

        _apply(conn, migration.upgrade)  # re-running changes nothing
        assert len(_assignments(conn)) == 4


def test_upgrade_creates_a_missing_default_namespace(tmp_path, migration):
    engine = create_engine(f"sqlite:///{tmp_path / 't1b.db'}")
    with engine.begin() as conn:
        _schema(conn, with_default_namespace=False)
        conn.execute(text("INSERT INTO data_contract_tags VALUES ('r1', 'c1', 'pii')"))

        _apply(conn, migration.upgrade)

        assert _assignments(conn) == [('c1', 'default', 'pii', None, 'system')]


def test_upgrade_without_the_tables_does_nothing(tmp_path, migration):
    engine = create_engine(f"sqlite:///{tmp_path / 't1c.db'}")
    with engine.begin() as conn:
        _apply(conn, migration.upgrade)
        _apply(conn, migration.downgrade)
