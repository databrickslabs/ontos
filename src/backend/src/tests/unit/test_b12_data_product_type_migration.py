"""Test the b12 migration that moves productType custom properties onto
data_products.product_type_id, by running its upgrade()/downgrade() on SQLite."""

import importlib.util
import re
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.pool import StaticPool

from src.models.data_product_types import KEY_PATTERN
from src.repositories.data_product_types_repository import (
    normalize_type_key as app_normalize_type_key,
)

_PATH = (
    Path(__file__).resolve().parents[3]
    / "alembic"
    / "versions"
    / "b12_product_type_from_props.py"
)


@pytest.fixture(scope="module")
def migration():
    spec = importlib.util.spec_from_file_location("b12_product_type_from_props", _PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def engine(tmp_path, migration):
    engine = sa.create_engine(
        f"sqlite:///{tmp_path / 'b12.db'}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(sa.text(
            "CREATE TABLE data_product_types (id CHAR(32) PRIMARY KEY, key TEXT UNIQUE NOT NULL,"
            " label TEXT NOT NULL, description TEXT, sort_order INTEGER NOT NULL,"
            " is_active BOOLEAN NOT NULL, is_default BOOLEAN NOT NULL, is_imported BOOLEAN NOT NULL)"
        ))
        conn.execute(sa.text(
            "CREATE TABLE data_products (id TEXT PRIMARY KEY, product_type_id CHAR(32))"
        ))
        conn.execute(sa.text(
            "CREATE TABLE data_product_custom_properties (id TEXT PRIMARY KEY,"
            " product_id TEXT NOT NULL, property TEXT NOT NULL, value TEXT)"
        ))
        # The five types b11 seeds
        for order, key in enumerate(
            ["source-aligned", "aggregate", "consumer-aligned", "source", "sink"], start=1
        ):
            conn.execute(migration.data_product_types.insert().values(
                id=uuid4(), key=key, label=key.title(), sort_order=order,
                is_active=True, is_default=order == 1, is_imported=False,
            ))
    return engine


def _run(engine, fn):
    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        fn()


def _add_product(conn, migration, product_id, *values, type_key=None):
    type_id = None
    if type_key:
        type_id = conn.execute(
            sa.select(migration.data_product_types.c.id)
            .where(migration.data_product_types.c.key == type_key)
        ).scalar_one()
    conn.execute(migration.data_products.insert().values(id=product_id, product_type_id=type_id))
    for i, value in enumerate(values):
        conn.execute(migration.custom_properties.insert().values(
            id=f"{product_id}-cp{i}", product_id=product_id, property="productType", value=value,
        ))


def _types_by_product(conn, migration):
    p, t = migration.data_products, migration.data_product_types
    return dict(conn.execute(
        sa.select(p.c.id, t.c.key).select_from(p.outerjoin(t, p.c.product_type_id == t.c.id))
    ).all())


def _product_type_props(conn):
    return conn.execute(sa.text(
        "SELECT product_id, value FROM data_product_custom_properties"
        " WHERE property = 'productType' ORDER BY product_id"
    )).all()


@pytest.mark.parametrize(
    ("raw", "key"),
    [
        ("source-aligned", "source-aligned"),
        ("sourceAligned", "source-aligned"),
        ("ConsumerAligned", "consumer-aligned"),
        ("SOURCE_ALIGNED", "source-aligned"),
        ("  Source Aligned ", "source-aligned"),
        ('"aggregate"', "aggregate"),
        ("sink", "sink"),
        ("Golden Record!", "golden-record"),
        ("Café", "cafe"),
        ("Données", "donnees"),
        ("", None),
        ("   ", None),
        ('""', None),
        (None, None),
    ],
)
def test_normalize_type_key(migration, raw, key):
    assert migration.normalize_type_key(raw) == key


@pytest.mark.parametrize(
    ("raw", "stem"),
    [("データ製品", "type"), ("!!!", "type"), ("Data 製品", "data")],
)
def test_normalize_type_key_hashes_values_without_an_ascii_form(migration, raw, stem):
    key = migration.normalize_type_key(raw)
    assert re.fullmatch(rf"{stem}-[0-9a-f]{{8}}", key)
    assert re.fullmatch(KEY_PATTERN, key)
    assert migration.normalize_type_key(raw) == key


def test_normalize_type_key_keeps_distinct_values_apart(migration):
    values = ["データ製品", "データ", "!!!", "!!", "Data 製品", "Data"]
    keys = [migration.normalize_type_key(v) for v in values]
    assert len(set(keys)) == len(keys)


@pytest.mark.parametrize(
    "raw",
    ["sourceAligned", "Café", "Données", "データ製品", "!!!", "Data 製品", '"sink"', "", None],
)
def test_normalize_type_key_matches_the_app(migration, raw):
    assert migration.normalize_type_key(raw) == app_normalize_type_key(raw)


def test_upgrade_moves_values_onto_the_fk_and_drops_the_rows(engine, migration):
    with engine.begin() as conn:
        _add_product(conn, migration, "p-kebab", "aggregate")
        _add_product(conn, migration, "p-camel", "sourceAligned")
        _add_product(conn, migration, "p-json", '"consumerAligned"')
        _add_product(conn, migration, "p-empty", "")
        _add_product(conn, migration, "p-none")
        conn.execute(migration.custom_properties.insert().values(
            id="other", product_id="p-kebab", property="owner", value="team-a",
        ))

    _run(engine, migration.upgrade)

    with engine.connect() as conn:
        assert _types_by_product(conn, migration) == {
            "p-kebab": "aggregate",
            "p-camel": "source-aligned",
            "p-json": "consumer-aligned",
            "p-empty": None,
            "p-none": None,
        }
        assert _product_type_props(conn) == []
        # Other custom properties are untouched
        assert conn.execute(sa.text(
            "SELECT property FROM data_product_custom_properties"
        )).scalars().all() == ["owner"]


def test_upgrade_creates_an_imported_type_for_unknown_values(engine, migration):
    with engine.begin() as conn:
        _add_product(conn, migration, "p1", "Golden Record")
        _add_product(conn, migration, "p2", "goldenRecord")

    _run(engine, migration.upgrade)

    with engine.connect() as conn:
        assert _types_by_product(conn, migration) == {"p1": "golden-record", "p2": "golden-record"}
        created = conn.execute(
            sa.select(migration.data_product_types)
            .where(migration.data_product_types.c.key == "golden-record")
        ).mappings().one()
        assert created["label"] == "Golden Record"
        assert created["is_imported"] and created["is_active"] and not created["is_default"]
        assert created["sort_order"] == 6


def test_upgrade_keeps_values_without_an_ascii_form(engine, migration):
    values = {"p-ja": "データ製品", "p-sym": "!!!", "p-mixed": "Data 製品", "p-data": "Data",
              "p-cafe": "Café", "p-caf": "Caf"}
    with engine.begin() as conn:
        for product_id, value in values.items():
            _add_product(conn, migration, product_id, value)

    _run(engine, migration.upgrade)

    with engine.connect() as conn:
        types = _types_by_product(conn, migration)
        assert all(types[p] is not None for p in values)
        # No two different values share a type
        assert len(set(types.values())) == len(values)
        assert types["p-cafe"] == "cafe" and types["p-caf"] == "caf"
        t = migration.data_product_types
        labels = dict(conn.execute(sa.select(t.c.key, t.c.label)).all())
        assert {labels[types[p]] for p in values} == set(values.values())
        assert _product_type_props(conn) == []


def test_downgrade_writes_back_the_original_text_of_imported_types(engine, migration):
    with engine.begin() as conn:
        _add_product(conn, migration, "p-ja", "データ製品")
        _add_product(conn, migration, "p-golden", "Golden Record")
        _add_product(conn, migration, "p-seeded", "sourceAligned")

    _run(engine, migration.upgrade)
    _run(engine, migration.downgrade)

    with engine.connect() as conn:
        assert _product_type_props(conn) == [
            ("p-golden", "Golden Record"), ("p-ja", "データ製品"), ("p-seeded", "source-aligned"),
        ]


def test_upgrade_keeps_an_existing_fk_and_uses_the_first_usable_value(engine, migration):
    with engine.begin() as conn:
        _add_product(conn, migration, "p-typed", "sink", type_key="aggregate")
        _add_product(conn, migration, "p-many", "", "source", "sink")

    _run(engine, migration.upgrade)

    with engine.connect() as conn:
        assert _types_by_product(conn, migration) == {"p-typed": "aggregate", "p-many": "source"}
        assert _product_type_props(conn) == []


def test_upgrade_twice_is_a_no_op(engine, migration):
    with engine.begin() as conn:
        _add_product(conn, migration, "p1", "Golden Record")

    _run(engine, migration.upgrade)
    _run(engine, migration.upgrade)

    with engine.connect() as conn:
        assert _types_by_product(conn, migration) == {"p1": "golden-record"}
        assert conn.execute(sa.text("SELECT COUNT(*) FROM data_product_types")).scalar() == 6


def test_downgrade_restores_the_custom_properties(engine, migration):
    with engine.begin() as conn:
        _add_product(conn, migration, "p-camel", "sourceAligned")
        _add_product(conn, migration, "p-none")
        # Written by the app after the upgrade: keeps its own value on downgrade
        _add_product(conn, migration, "p-new", type_key="sink")

    _run(engine, migration.upgrade)
    with engine.begin() as conn:
        conn.execute(migration.custom_properties.insert().values(
            id="p-new-cp", product_id="p-new", property="productType", value="sink",
        ))

    _run(engine, migration.downgrade)

    with engine.connect() as conn:
        assert _product_type_props(conn) == [("p-camel", "source-aligned"), ("p-new", "sink")]
        assert set(_types_by_product(conn, migration).values()) == {None}
