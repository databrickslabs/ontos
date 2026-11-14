"""Test the u3 migration (assets.tags onto entity_tag_associations) through Alembic."""
import importlib.util
import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

_NAME = 's4_asset_tags_shared_store'


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


def _create_schema(conn):
    conn.execute(text("CREATE TABLE assets (id VARCHAR PRIMARY KEY, tags JSON)"))
    conn.execute(text(
        "CREATE TABLE tag_namespaces (id VARCHAR PRIMARY KEY, name VARCHAR UNIQUE, "
        "description VARCHAR, created_by VARCHAR)"
    ))
    conn.execute(text(
        "CREATE TABLE tags (id VARCHAR PRIMARY KEY, name VARCHAR, status VARCHAR, "
        "namespace_id VARCHAR REFERENCES tag_namespaces(id), created_by VARCHAR)"
    ))
    conn.execute(text(
        "CREATE TABLE entity_tag_associations (id VARCHAR PRIMARY KEY, tag_id VARCHAR, "
        "entity_id VARCHAR, entity_type VARCHAR, assigned_value VARCHAR, assigned_by VARCHAR, "
        "UNIQUE (tag_id, entity_id, entity_type))"
    ))


def _assigned(conn, entity_id):
    """(namespace, tag name) of every tag on an asset."""
    return {(ns, name) for ns, name in conn.execute(text(
        "SELECT ns.name, t.name FROM entity_tag_associations eta "
        "JOIN tags t ON t.id = eta.tag_id JOIN tag_namespaces ns ON ns.id = t.namespace_id "
        "WHERE eta.entity_type = 'asset' AND eta.entity_id = :id"
    ), {'id': entity_id}).all()}


def test_upgrade_moves_entries_onto_associations_and_drops_the_column(tmp_path, migration):
    assert migration.down_revision == 'r2_canonical_relationship_types'
    engine = create_engine(f"sqlite:///{tmp_path / 'u3.db'}")
    with engine.begin() as conn:
        _create_schema(conn)
        conn.execute(text("INSERT INTO tag_namespaces VALUES ('ns-gov', 'governance', '', 'system')"))
        conn.execute(text("INSERT INTO tag_namespaces VALUES ('ns-default', 'default', '', 'system')"))
        conn.execute(text("INSERT INTO tags VALUES ('t-pii', 'pii', 'active', 'ns-default', 'system')"))
        conn.execute(text("INSERT INTO tags VALUES ('t-classified', 'classified', 'active', 'ns-gov', 'system')"))
        conn.execute(
            text("INSERT INTO assets VALUES ('a1', :tags), ('a2', :empty), ('a3', NULL)"),
            {'tags': json.dumps(['pii', 'governance/classified', 'nosuch/x', 'pii', '  ', 'pii/']),
             'empty': json.dumps([])},
        )

        _apply(conn, migration.upgrade)

        assert _assigned(conn, 'a1') == {
            ('default', 'pii'), ('governance', 'classified'), ('default', 'nosuch/x'), ('default', 'pii/'),
        }
        assert _assigned(conn, 'a2') == set()
        assert _assigned(conn, 'a3') == set()
        # The existing 'pii' tag is matched, not duplicated
        assert conn.execute(text("SELECT COUNT(*) FROM tags WHERE name = 'pii'")).scalar() == 1
        assert 'tags' not in {c['name'] for c in sa.inspect(conn).get_columns('assets')}


def test_upgrade_creates_the_default_namespace_when_it_is_missing(tmp_path, migration):
    engine = create_engine(f"sqlite:///{tmp_path / 'u3b.db'}")
    with engine.begin() as conn:
        _create_schema(conn)
        conn.execute(text("INSERT INTO assets VALUES ('a1', :tags)"), {'tags': json.dumps(['lookup'])})

        _apply(conn, migration.upgrade)

        assert _assigned(conn, 'a1') == {('default', 'lookup')}


def test_downgrade_restores_the_column_from_the_associations(tmp_path, migration):
    engine = create_engine(f"sqlite:///{tmp_path / 'u3c.db'}")
    with engine.begin() as conn:
        _create_schema(conn)
        conn.execute(text("INSERT INTO assets VALUES ('a1', :tags), ('a2', NULL)"),
                     {'tags': json.dumps(['pii', 'governance/classified'])})
        _apply(conn, migration.upgrade)
        assert 'tags' not in {c['name'] for c in sa.inspect(conn).get_columns('assets')}

        _apply(conn, migration.downgrade)

        assert 'tags' in {c['name'] for c in sa.inspect(conn).get_columns('assets')}
        restored = {
            aid: json.loads(raw) if isinstance(raw, str) else raw
            for aid, raw in conn.execute(text("SELECT id, tags FROM assets")).all()
        }
        assert sorted(restored['a1']) == ['governance/classified', 'pii']
        assert restored['a2'] == []
