"""The Policy reference migration (am1, ARF 1.2.0) creates the slim table and nothing else.

am1 was rewritten in place for batch 5 (it never shipped), so this test runs its
upgrade against SQLite and checks the shape the models expect: no approval,
lifecycle or document columns, the link-out and validity columns present, and the
AR and check columns it adds.
"""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def _load_am1():
    path = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "am1_authority_policies.py"
    spec = importlib.util.spec_from_file_location("am1_authority_policies", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def upgraded(monkeypatch):
    # SQLite can't ALTER a constraint; the FK itself is exercised on Postgres. Everything
    # else in the revision runs for real.
    monkeypatch.setattr(Operations, "create_foreign_key", lambda self, *a, **k: None)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE teams (id VARCHAR PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE authority_relations (id VARCHAR PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE authority_criteria (id VARCHAR PRIMARY KEY)")
        with Operations.context(MigrationContext.configure(conn)):
            _load_am1().upgrade()
        yield conn


def test_revision_chain_and_head():
    am1 = _load_am1()
    assert am1.revision == "am1_authority_policies"
    assert am1.down_revision == "al1_authority_scoped_context"


def test_the_reference_table_has_only_the_metadata_columns(upgraded):
    columns = {c["name"] for c in sa.inspect(upgraded).get_columns("authority_policies")}
    assert columns == {
        "id", "policy_key", "version", "version_family_id", "parent_policy_id", "change_summary",
        "title", "summary", "owner_team_id", "url", "valid_from", "valid_to", "clauses",
        "created_by", "created_at", "updated_at",
    }
    retired = {"status", "approved_by", "approved_at", "approval_evidence_document_id",
               "withdrawn_reason", "effective_from", "effective_to", "policy_type", "jurisdiction"}
    assert not (columns & retired)


def test_the_ar_and_check_columns_are_added(upgraded):
    ar = {c["name"] for c in sa.inspect(upgraded).get_columns("authority_relations")}
    check = {c["name"] for c in sa.inspect(upgraded).get_columns("authority_criteria")}
    assert {"authority_policy_id", "policy_clause_refs"} <= ar
    assert "policy_clause_ref" in check

