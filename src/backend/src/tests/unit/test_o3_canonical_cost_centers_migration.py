"""Migration o3 preserves legacy cost-center context while canonicalizing values."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

PATH = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "o3_canonical_cost_centers.py"


@pytest.fixture
def migration():
    spec = importlib.util.spec_from_file_location("o3_canonical_cost_centers", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def engine():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.connection.create_function(
            "initcap", 1, lambda value: value.title() if value is not None else None
        )
        conn.execute(
            text("""
                CREATE TABLE cost_items (
                    id TEXT PRIMARY KEY,
                    cost_center TEXT NOT NULL,
                    custom_center_name TEXT
                )
            """)
        )
    return engine


def _run_upgrade(migration, engine, monkeypatch):
    monkeypatch.setattr(migration.op, "create_check_constraint", lambda *args, **kwargs: None)
    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        migration.upgrade()


def _rows(engine):
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, cost_center, custom_center_name FROM cost_items ORDER BY id")
        )
        return [(row.id, row.cost_center, row.custom_center_name) for row in rows]


def test_upgrade_preserves_invalid_classification_and_custom_name(migration, engine, monkeypatch):
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO cost_items (id, cost_center, custom_center_name) VALUES
                    ('canonical', 'HR', 'People'),
                    ('spaced', ' storage ', NULL),
                    ('legacy', 'tools', NULL),
                    ('legacy-custom', 'tools', 'Licences')
            """)
        )

    _run_upgrade(migration, engine, monkeypatch)

    assert _rows(engine) == [
        ("canonical", "HR", "People"),
        ("legacy", "OTHER", "Tools"),
        ("legacy-custom", "OTHER", "Tools: Licences"),
        ("spaced", "STORAGE", None),
    ]

    _run_upgrade(migration, engine, monkeypatch)
    assert _rows(engine)[2] == ("legacy-custom", "OTHER", "Tools: Licences")


def test_upgrade_bounds_the_combined_custom_name(migration, engine, monkeypatch):
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO cost_items (id, cost_center, custom_center_name)
                VALUES ('legacy-long', 'tools', :custom_name)
            """),
            {"custom_name": "x" * 255},
        )

    _run_upgrade(migration, engine, monkeypatch)

    row = _rows(engine)[0]
    assert row[0:2] == ("legacy-long", "OTHER")
    assert row[2].startswith("Tools: ")
    assert len(row[2]) == 255
