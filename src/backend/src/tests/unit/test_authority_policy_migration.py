"""The Policy reference migrations: am1 (as shipped on the branch) then an1 (ARF 1.2.0).

am1 creates the lifecycle table; an1 reshapes it into references. The tests run both
on SQLite (the FK creation is stubbed: SQLite can't ALTER a constraint, and the FK is
exercised on Postgres) and check the data mapping, the dropped and added columns and
the downgrade.
"""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

VERSIONS = Path(__file__).resolve().parents[3] / "alembic" / "versions"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(Operations, "create_foreign_key", lambda self, *a, **k: None)
    eng = sa.create_engine("sqlite://")
    with eng.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE teams (id VARCHAR PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE authority_relations (id VARCHAR PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE authority_criteria (id VARCHAR PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE document_metadata (id VARCHAR PRIMARY KEY)")
    return eng


def _run(conn, module, direction: str) -> None:
    with Operations.context(MigrationContext.configure(conn)):
        getattr(module, direction)()


def _insert_old_rows(conn) -> None:
    """One row per old status, in the am1 shape."""
    day = "2024-01-01 00:00:00"
    rows = [
        ("draft-nodate", "draft", None, None),
        ("approved", "approved", day, None),
        ("superseded", "superseded", day, "2024-07-01 00:00:00"),
        ("withdrawn", "withdrawn", day, "2025-01-01 00:00:00"),
    ]
    for rid, status, start, end in rows:
        conn.execute(sa.text(
            "INSERT INTO authority_policies (id, policy_key, version, title, policy_type, status, "
            "effective_from, effective_to, created_by, created_at, updated_at, approved_by) "
            "VALUES (:id, :key, '1', :title, 'DOA', :status, :start, :end, 'alice', :ts, :ts, 'board')"
        ), {"id": rid, "key": rid.upper(), "title": rid, "status": status, "start": start, "end": end,
            "ts": "2023-12-01 00:00:00"})


def test_an1_is_a_single_additive_head_on_am1():
    an1 = _load("an1_authority_policy_references")
    am1 = _load("am1_authority_policies")
    assert an1.revision == "an1_authority_policy_references"
    assert an1.down_revision == am1.revision == "am1_authority_policies"


def test_the_row_mapping_keeps_the_window_whatever_the_status():
    an1 = _load("an1_authority_policy_references")
    start, end = datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert an1.map_policy_row({"effective_from": start, "effective_to": end, "status": "withdrawn"}) == {
        "valid_from": start, "valid_to": end}
    assert an1.map_policy_row({"effective_from": None, "effective_to": None, "status": "draft"}) == {
        "valid_from": None, "valid_to": None}


def test_the_restore_mapping_makes_each_reference_approved_with_its_window():
    an1 = _load("an1_authority_policy_references")
    created = datetime(2023, 12, 1, tzinfo=timezone.utc)
    row = {"valid_from": None, "valid_to": None, "created_by": "alice", "created_at": created}
    restored = an1.restore_policy_row(row)
    assert restored["status"] == "approved" and restored["approved_by"] == "alice"
    assert restored["approved_at"] == created and restored["effective_from"] is None


def test_upgrade_maps_every_old_status_to_a_reference_and_drops_the_lifecycle(engine):
    am1, an1 = _load("am1_authority_policies"), _load("an1_authority_policy_references")
    with engine.begin() as conn:
        _run(conn, am1, "upgrade")
        _insert_old_rows(conn)
        _run(conn, an1, "upgrade")
        insp = sa.inspect(conn)
        columns = {c["name"] for c in insp.get_columns("authority_policies")}
        assert {"url", "valid_from", "valid_to"} <= columns
        assert not columns & set(an1.LIFECYCLE_COLUMNS)
        assert "ix_authority_policies_status" not in {i["name"] for i in insp.get_indexes("authority_policies")}
        assert "content_sha256" not in {c["name"] for c in insp.get_columns("document_metadata")}
        dates = {r.id: (r.valid_from, r.valid_to) for r in conn.execute(
            sa.text("SELECT id, valid_from, valid_to FROM authority_policies"))}
    assert dates["draft-nodate"] == (None, None)
    assert dates["approved"][0].startswith("2024-01-01") and dates["approved"][1] is None
    assert dates["superseded"][1].startswith("2024-07-01")
    assert dates["withdrawn"][1].startswith("2025-01-01")


def test_downgrade_restores_the_lifecycle_columns(engine):
    am1, an1 = _load("am1_authority_policies"), _load("an1_authority_policy_references")
    with engine.begin() as conn:
        _run(conn, am1, "upgrade")
        _insert_old_rows(conn)
        _run(conn, an1, "upgrade")
        _run(conn, an1, "downgrade")
        columns = {c["name"] for c in sa.inspect(conn).get_columns("authority_policies")}
        assert set(an1.LIFECYCLE_COLUMNS) <= columns
        assert not {"url", "valid_from", "valid_to"} & columns
        assert "content_sha256" in {c["name"] for c in sa.inspect(conn).get_columns("document_metadata")}
        rows = conn.execute(sa.text(
            "SELECT id, status, approved_by, effective_from FROM authority_policies WHERE id = 'approved'")).one()
    assert (rows.status, rows.approved_by) == ("approved", "alice")
    assert rows.effective_from.startswith("2024-01-01")
