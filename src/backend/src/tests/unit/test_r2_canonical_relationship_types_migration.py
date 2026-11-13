"""Migration r2 rewrites stored relationship types to ontology local names."""
import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

PATH = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "r2_canonical_relationship_types.py"
NOW = datetime(2026, 11, 11, 12, 0, 0)


@pytest.fixture
def migration():
    spec = importlib.util.spec_from_file_location("r2_canonical_relationship_types", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE entity_relationships (
                id TEXT PRIMARY KEY, source_type TEXT NOT NULL, source_id TEXT NOT NULL,
                target_type TEXT NOT NULL, target_id TEXT NOT NULL, relationship_type TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                UNIQUE (source_type, source_id, target_type, target_id, relationship_type)
            )
        """))
    return engine


def _seed(engine, *rows):
    with engine.begin() as conn:
        for rid, src, sid, tgt, tid, rel, age_days in rows:
            conn.execute(text(
                "INSERT INTO entity_relationships VALUES (:id, :s, :sid, :t, :tid, :rel, :at)"
            ), {"id": rid, "s": src, "sid": sid, "t": tgt, "tid": tid, "rel": rel,
                "at": NOW - timedelta(days=age_days)})


def _run(engine, fn):
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            fn()


def _rows(engine):
    with engine.connect() as conn:
        return {r.id: (r.source_type, r.target_type) for r in conn.execute(
            text("SELECT id, source_type, target_type FROM entity_relationships"))}


def test_upgrade_canonicalizes_and_merges(migration, engine):
    _seed(
        engine,
        # The same link in both spellings: the oldest one stays.
        ("old-label", "Logical Entity", "le1", "Logical Attribute", "la1", "hasLogicalAttribute", 2),
        ("new-local", "LogicalEntity", "le1", "LogicalAttribute", "la1", "hasLogicalAttribute", 1),
        ("label", "Metric View", "mv1", "Column", "c1", "hasColumn", 0),
        ("ontos-iri", "http://ontos.app/ontology#Table", "t1", "DataContract", "dc1", "implementsContract", 0),
        ("foreign-iri", "Table", "t2", "https://example.com/ns#Thing", "x1", "hasSemanticConcept", 0),
        ("untouched", "Table", "t3", "Column", "c3", "hasColumn", 0),
    )

    assert migration.down_revision == "s1_workflow_is_customized"
    _run(engine, migration.upgrade)

    assert _rows(engine) == {
        "old-label": ("LogicalEntity", "LogicalAttribute"),
        "label": ("MetricView", "Column"),
        "ontos-iri": ("Table", "DataContract"),
        "foreign-iri": ("Table", "https://example.com/ns#Thing"),
        "untouched": ("Table", "Column"),
    }

    _run(engine, migration.upgrade)  # a second run changes nothing
    assert len(_rows(engine)) == 5


def test_two_label_spellings_of_one_link_merge_into_one_row(migration, engine):
    _seed(
        engine,
        ("a", "Logical Entity", "le1", "Logical Attribute", "la1", "hasLogicalAttribute", 3),
        ("b", "Logical  Entity", "le1", "Logical Attribute", "la1", "hasLogicalAttribute", 1),
    )

    _run(engine, migration.upgrade)

    assert _rows(engine) == {"a": ("LogicalEntity", "LogicalAttribute")}
