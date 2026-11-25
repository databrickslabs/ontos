"""Test the r3 migration (ODCS round-trip columns) through Alembic, on SQLite.

The upgrade adds the columns and moves the stored column descriptions from
`transform_description` (where the import put them) to `description`; the
downgrade moves them back and drops the columns.
"""
import importlib.util
import tempfile
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

_PROPERTIES = 'data_contract_schema_properties'
_NEW_COLUMNS = {
    _PROPERTIES: {'physical_name', 'description', 'tags'},
    'data_contract_servers': {'roles_json', 'custom_properties_json'},
    'data_contract_pricing': {'stable_id'},
    'data_contract_role_properties': {'stable_id'},
    'data_contract_schema_object_relationships': {'stable_id'},
    'data_contract_schema_property_relationships': {'stable_id'},
}


@pytest.fixture
def engine():
    db_file = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
    db_file.close()
    eng = create_engine(f'sqlite:///{db_file.name}', poolclass=StaticPool,
                        connect_args={'check_same_thread': False})
    yield eng
    Path(db_file.name).unlink(missing_ok=True)


@pytest.fixture
def migration():
    backend_dir = Path(__file__).resolve().parents[3]
    path = backend_dir / 'alembic' / 'versions' / 'r3_odcs_roundtrip_fields.py'
    spec = importlib.util.spec_from_file_location('r3_odcs_roundtrip_fields', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pre_r3_schema(conn) -> None:
    conn.execute(text(f"""
        CREATE TABLE {_PROPERTIES} (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, transform_description TEXT)
    """))
    for table in _NEW_COLUMNS:
        if table != _PROPERTIES:
            conn.execute(text(f"CREATE TABLE {table} (id TEXT PRIMARY KEY)"))
    conn.execute(text(f"""
        INSERT INTO {_PROPERTIES} (id, name, transform_description) VALUES
        ('p1', 'order_id', 'The order number'), ('p2', 'amount', NULL)
    """))


def _run(engine, fn) -> None:
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            fn()


def _columns(conn, table) -> set:
    return {c['name'] for c in sa.inspect(conn).get_columns(table)}


def _rows(conn):
    return conn.execute(text(
        f"SELECT id, description, transform_description FROM {_PROPERTIES} ORDER BY id"
    )).all()


@pytest.fixture
def upgraded(engine, migration):
    with engine.begin() as conn:
        _pre_r3_schema(conn)
    _run(engine, migration.upgrade)
    return engine


def test_upgrade_adds_the_columns(upgraded):
    with upgraded.connect() as conn:
        for table, columns in _NEW_COLUMNS.items():
            assert columns <= _columns(conn, table), table


def test_upgrade_moves_the_descriptions(upgraded):
    with upgraded.connect() as conn:
        assert _rows(conn) == [('p1', 'The order number', None), ('p2', None, None)]


def test_downgrade_moves_them_back_and_drops_the_columns(upgraded, migration):
    _run(upgraded, migration.downgrade)

    with upgraded.connect() as conn:
        rows = conn.execute(text(
            f"SELECT id, transform_description FROM {_PROPERTIES} ORDER BY id")).all()
        assert rows == [('p1', 'The order number'), ('p2', None)]
        for table, columns in _NEW_COLUMNS.items():
            assert not columns & _columns(conn, table), table


def test_downgrade_keeps_a_transform_description_without_description(upgraded, migration):
    with upgraded.begin() as conn:
        conn.execute(text(
            f"UPDATE {_PROPERTIES} SET transform_description = 'Copied' WHERE id = 'p2'"))

    _run(upgraded, migration.downgrade)

    with upgraded.connect() as conn:
        rows = conn.execute(text(
            f"SELECT id, transform_description FROM {_PROPERTIES} ORDER BY id")).all()
        assert rows == [('p1', 'The order number'), ('p2', 'Copied')]
