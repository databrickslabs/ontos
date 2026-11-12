"""Test the u4 migration (team member role overrides stored by role id) through Alembic."""
import importlib.util
import logging
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

_NAME = 'u4_team_override_role_id'


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


def _create_tables(conn):
    conn.execute(text("CREATE TABLE app_roles (id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL)"))
    conn.execute(text(
        "CREATE TABLE team_members (id VARCHAR PRIMARY KEY, team_id VARCHAR NOT NULL, "
        "member_type VARCHAR NOT NULL, member_identifier VARCHAR NOT NULL, app_role_override VARCHAR)"
    ))
    conn.execute(text(
        "INSERT INTO app_roles VALUES ('role-admin', 'Admin'), ('role-steward', 'Data Steward')"
    ))
    conn.execute(text(
        "INSERT INTO team_members VALUES "
        "('m-admin', 't1', 'group', 'admins', 'Admin'), "
        "('m-padded', 't1', 'user', 'a@example.com', '  Data Steward '), "
        "('m-unknown', 't1', 'user', 'b@example.com', 'Retired Role'), "
        "('m-none', 't1', 'user', 'c@example.com', NULL), "
        "('m-blank', 't1', 'user', 'd@example.com', '   ')"
    ))


def _ids(conn):
    return dict(conn.execute(text("SELECT id, app_role_override_id FROM team_members")).all())


def test_revision_chains_onto_the_development_head(migration):
    assert migration.revision == _NAME
    assert migration.down_revision == 's1_workflow_is_customized'
    assert len(migration.revision) <= 32


def test_upgrade_stores_role_ids_and_logs_names_that_match_no_role(tmp_path, migration, caplog):
    engine = create_engine(f"sqlite:///{tmp_path / 'u4.db'}")
    with engine.begin() as conn:
        _create_tables(conn)

        with caplog.at_level(logging.WARNING, logger='alembic.runtime.migration'):
            _apply(conn, migration.upgrade)

        assert _ids(conn) == {
            'm-admin': 'role-admin',
            'm-padded': 'role-steward',
            'm-unknown': None,
            'm-none': None,
            'm-blank': None,
        }
        assert 'Retired Role' in caplog.text
        assert 'Admin' not in caplog.text
        columns = {c['name'] for c in sa.inspect(conn).get_columns('team_members')}
        assert 'app_role_override' not in columns
        assert 'app_role_override_id' in columns
        # SQLite reflection skips expression indexes, so read the catalog.
        indexes = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'index'"))}
        assert 'ix_team_members_lower_identifier' in indexes


def test_renamed_role_keeps_its_overrides(tmp_path, migration):
    engine = create_engine(f"sqlite:///{tmp_path / 'u4-rename.db'}")
    with engine.begin() as conn:
        _create_tables(conn)
        _apply(conn, migration.upgrade)

        conn.execute(text("UPDATE app_roles SET name = 'Administrators' WHERE id = 'role-admin'"))

        name = conn.execute(text(
            "SELECT r.name FROM team_members m JOIN app_roles r ON r.id = m.app_role_override_id "
            "WHERE m.id = 'm-admin'"
        )).scalar()
        assert name == 'Administrators'


def test_downgrade_writes_the_current_role_names_back(tmp_path, migration):
    engine = create_engine(f"sqlite:///{tmp_path / 'u4-down.db'}")
    with engine.begin() as conn:
        _create_tables(conn)
        _apply(conn, migration.upgrade)
        _apply(conn, migration.downgrade)

        names = dict(conn.execute(text("SELECT id, app_role_override FROM team_members")).all())
        assert names == {
            'm-admin': 'Admin',
            'm-padded': 'Data Steward',
            'm-unknown': None,
            'm-none': None,
            'm-blank': None,
        }
        columns = {c['name'] for c in sa.inspect(conn).get_columns('team_members')}
        assert 'app_role_override_id' not in columns
