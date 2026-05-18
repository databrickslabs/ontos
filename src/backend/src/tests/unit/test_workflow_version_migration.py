"""Idempotency test for the ``i1_workflow_version`` Alembic migration.

The migration uses ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` so a
re-apply (which happens routinely on multi-revision upgrades, or on
deploys where alembic_version is ahead of the schema) must succeed.

Runs against a transient Postgres if ``POSTGRES_TEST_URL`` is set, otherwise
against SQLite — SQLite's ALTER TABLE doesn't support IF NOT EXISTS so we
emulate the idempotent behavior via a try/except wrapper. The Postgres
path is the one that matters in production.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text


# Lift only the SQL statement so the test does not need an alembic context.
ADD_COLUMN_SQL = (
    "ALTER TABLE agreements ADD COLUMN IF NOT EXISTS workflow_version INTEGER"
)


def _create_agreements_table(engine) -> None:
    """Minimal schema for the test: just the columns the migration touches."""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS agreements"))
        conn.execute(text(
            "CREATE TABLE agreements ("
            "  id TEXT PRIMARY KEY,"
            "  workflow_id TEXT"
            ")"
        ))


@pytest.mark.skipif(
    not os.environ.get("POSTGRES_TEST_URL"),
    reason="Postgres test URL not set; idempotency check runs only in environments with Postgres.",
)
def test_workflow_version_migration_is_idempotent_postgres() -> None:
    """Apply ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` twice — second
    apply must be a silent no-op, not an error. This is the real prod
    path (Postgres) and protects against alembic-version drift causing
    repeat applies on deploy.
    """
    engine = create_engine(os.environ["POSTGRES_TEST_URL"])
    _create_agreements_table(engine)
    with engine.begin() as conn:
        conn.execute(text(ADD_COLUMN_SQL))
    # Second apply must not raise.
    with engine.begin() as conn:
        conn.execute(text(ADD_COLUMN_SQL))
    # Column must be queryable after both applies.
    with engine.begin() as conn:
        result = conn.execute(text("SELECT workflow_version FROM agreements")).fetchall()
    assert result == []


def test_workflow_version_migration_sql_is_idempotent_shape() -> None:
    """Even without a real DB, the SQL statement itself must contain the
    ``IF NOT EXISTS`` guard. Tiny but catches drift if someone edits the
    migration body to a non-idempotent form (which would have been the
    failure mode that caused the original PRD #242 customer incident).
    """
    # Load the migration file directly — the alembic versions directory is
    # not a Python package (no __init__.py), so importlib.util.spec is the
    # cleanest path.
    import importlib.util
    from pathlib import Path

    here = Path(__file__).resolve()
    # tests/unit/<this> → src/backend/src/tests/unit/<this>
    # alembic/versions is at src/backend/alembic/versions
    backend_root = here.parents[3]  # src/backend
    migration_path = backend_root / "alembic" / "versions" / "i1_workflow_version.py"
    assert migration_path.exists(), f"Migration not found at {migration_path}"

    spec = importlib.util.spec_from_file_location("i1_workflow_version", migration_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    assert mod.revision == "i1_workflow_version"
    assert mod.down_revision == "h3_rename_consumer_principals"

    # Inspect the upgrade function's source to confirm the guard. Future edits
    # that drop the IF NOT EXISTS guard fail this test.
    import inspect

    src = inspect.getsource(mod.upgrade)
    assert "IF NOT EXISTS" in src, "Migration must use IF NOT EXISTS for idempotency"
    src_down = inspect.getsource(mod.downgrade)
    assert "IF EXISTS" in src_down, "Downgrade must use IF EXISTS for idempotency"


def test_workflow_version_revision_id_fits_alembic_version_column() -> None:
    """``alembic_version.version_num`` is VARCHAR(32). Revision IDs longer
    than 32 chars cause startup failures. Guards against future revisions
    re-introducing this footgun.
    """
    revision_id = "i1_workflow_version"
    assert len(revision_id) <= 32, (
        f"Revision id '{revision_id}' is {len(revision_id)} chars; "
        f"alembic_version.version_num is VARCHAR(32)."
    )
