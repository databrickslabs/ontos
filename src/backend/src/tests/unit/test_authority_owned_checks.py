"""ARF 1.2.0 batch 2, commit 2: decision checks owned by the AR version (#859 review B7, S12).

Covers: no Compliance rows for inline checks and no duplication on save; the ARF
template registry; copy-from-Compliance with no live link; weight and order rules
(N5, N6); New Version copies the checks; the ak6 migration's data move, run through
the real upgrade() and downgrade() on SQLite.
"""
import asyncio
import importlib.util
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy import create_engine, text

from src.common.authority_check_templates import get_template, list_templates
from src.controller.authority_resolution_manager import (
    AuthorityInvalidError,
    AuthorityResolutionManager,
    STATUS_ACTIVE,
    VERDICT_APPROVED,
    VERDICT_DENIED,
)
from src.db_models.authority_resolution import AuthorityCriterionDb
from src.db_models.compliance import CompliancePolicyDb
from src.models.authority_resolution import AuthorityRelationCreate, AuthorityRelationUpdate, CriterionInput


def _count_arf_policies(db):
    return db.query(CompliancePolicyDb).filter(CompliancePolicyDb.category == "Authority Decision").count()


def _saved(mgr, db, **kwargs):
    rel = mgr.create_relation(db, AuthorityRelationCreate(name="Owned", **kwargs), current_user="author@x.com")
    db.commit()
    return rel


# ----------------------------------------------------------- ownership (B7, S12)

def test_inline_checks_create_no_compliance_rows(db_session):
    mgr = AuthorityResolutionManager()
    before = db_session.query(CompliancePolicyDb).count()
    rel = _saved(mgr, db_session, criteria=[
        CriterionInput(name="Authorized", rule="obj.actor_identity IN ['rsm-east']"),
        CriterionInput(name="Cap", rule="obj.value <= 0.15"),
    ])
    assert db_session.query(CompliancePolicyDb).count() == before
    assert _count_arf_policies(db_session) == 0
    assert [c.name for c in rel.criteria] == ["Authorized", "Cap"]


def test_saving_the_same_checks_again_does_not_duplicate_them(db_session):
    from src.models.authority_resolution import AuthorityRelationUpdate as Upd
    mgr = AuthorityResolutionManager()
    rel = _saved(mgr, db_session, criteria=[CriterionInput(name="Cap", rule="obj.value <= 0.15")])
    rule_list = [CriterionInput(name="Cap", rule="obj.value <= 0.15")]
    for _ in range(3):
        mgr.update_relation(db_session, rel.id, Upd(criteria=rule_list), current_user="author@x.com")
        db_session.commit()
    db_session.refresh(rel)
    assert len(rel.criteria) == 1
    assert _count_arf_policies(db_session) == 0


def test_a_compliance_edit_or_delete_does_not_change_the_ar(db_session):
    mgr = AuthorityResolutionManager()
    pid = str(uuid.uuid4())
    db_session.add(CompliancePolicyDb(id=pid, slug=f"cc-{pid[:8]}", name="Cap check",
                                      rule="ASSERT obj.value <= 0.15", category="Governance",
                                      severity="high", is_active=True))
    db_session.commit()
    rel = _saved(mgr, db_session, criteria=[CriterionInput(
        name="Cap check", rule="ASSERT obj.value <= 0.15", copied_from={"kind": "compliance", "label": "Cap check", "id": pid})])
    rel.status = STATUS_ACTIVE
    db_session.commit()

    # The Compliance check is loosened, and then deleted: the AR still applies its own copy.
    policy = db_session.get(CompliancePolicyDb, pid)
    policy.rule = "ASSERT obj.value <= 1000"
    db_session.commit()
    assert mgr.resolve(db_session, rel.id, {"value": 0.5}, record=False, require_active=False)["verdict"] == VERDICT_DENIED

    db_session.delete(policy)
    db_session.commit()
    criteria = mgr._load_criteria(db_session.get(type(rel), rel.id))
    assert [c.rule for c in criteria] == ["ASSERT obj.value <= 0.15"]


# ----------------------------------------------------------------- templates

def test_template_registry_has_the_three_plain_field_checks():
    keys = [t.key for t in list_templates()]
    assert keys == ["mfa_required", "no_sod_conflict", "no_self_grant"]
    for t in list_templates():
        assert t.rule.startswith("ASSERT obj.")
        assert get_template(t.key) is t
    assert get_template("nope") is None


def test_template_check_is_filled_by_the_server_and_gates_the_decision(db_session):
    mgr = AuthorityResolutionManager()
    rel = _saved(mgr, db_session, slug="tpl-mfa", criteria=[CriterionInput(template_key="mfa_required")])
    crit = mgr.to_read_dict(db_session, rel)["criteria"][0]
    assert crit["rule"] == "ASSERT obj.mfa_verified = True"
    assert crit["copied_from"] == {"kind": "template", "label": "MFA required", "key": "mfa_required"}
    assert crit["dimension"] == "policy"
    rel.status = STATUS_ACTIVE
    db_session.commit()
    assert mgr.resolve(db_session, "tpl-mfa", {"mfa_verified": True}, record=False)["verdict"] == VERDICT_APPROVED
    denied = mgr.resolve(db_session, "tpl-mfa", {"mfa_verified": False}, record=False)
    assert denied["verdict"] == VERDICT_DENIED
    assert "Multi-factor" in denied["reason"]


def test_no_self_grant_template_refuses_a_self_grant_and_a_missing_grantee(db_session):
    mgr = AuthorityResolutionManager()
    rel = _saved(mgr, db_session, slug="tpl-self", criteria=[CriterionInput(template_key="no_self_grant")])
    rel.status = STATUS_ACTIVE
    db_session.commit()
    assert mgr.resolve(db_session, "tpl-self", {"grantee": "b", "actor_identity": "a"},
                       record=False)["verdict"] == VERDICT_APPROVED
    assert mgr.resolve(db_session, "tpl-self", {"grantee": "a", "actor_identity": "a"},
                       record=False)["verdict"] == VERDICT_DENIED
    assert mgr.resolve(db_session, "tpl-self", {"actor_identity": "a"},
                       record=False)["verdict"] == VERDICT_DENIED


def test_unknown_template_is_refused(db_session):
    mgr = AuthorityResolutionManager()
    with pytest.raises(AuthorityInvalidError):
        _saved(mgr, db_session, criteria=[CriterionInput(template_key="made_up")])
    db_session.rollback()


def test_template_route_lists_the_registry():
    from src.routes.authority_resolution_routes import list_check_templates
    rows = asyncio.run(list_check_templates(_=True))
    assert [r["key"] for r in rows] == ["mfa_required", "no_sod_conflict", "no_self_grant"]
    assert all({"name", "rule", "failure_message", "dimension", "description"} <= set(r) for r in rows)


# ------------------------------------------------- copy from Compliance, provenance

def test_copied_from_compliance_is_stored_as_provenance_only(db_session):
    mgr = AuthorityResolutionManager()
    rel = _saved(mgr, db_session, criteria=[CriterionInput(
        name="Cap", rule="obj.value <= 0.15",
        copied_from={"kind": "compliance", "label": "Discount cap", "id": "pol-1"})])
    crit = mgr.to_read_dict(db_session, rel)["criteria"][0]
    assert crit["copied_from"] == {"kind": "compliance", "label": "Discount cap", "id": "pol-1"}
    assert "policy_id" not in crit and "category" not in crit


def test_migrated_provenance_from_the_ui_is_accepted_and_an_unknown_kind_is_not(db_session):
    """The UI echoes ak6's 'migrated' provenance back on save; that must not be a 400."""
    mgr = AuthorityResolutionManager()
    rel = _saved(mgr, db_session, criteria=[CriterionInput(
        name="x", rule="obj.value <= 1", copied_from={"kind": "migrated", "label": "x", "id": "p-1"})])
    assert mgr.to_read_dict(db_session, rel)["criteria"][0]["copied_from"]["kind"] == "migrated"
    with pytest.raises(AuthorityInvalidError):
        _saved(mgr, db_session, criteria=[CriterionInput(
            name="y", rule="obj.value <= 1", copied_from={"kind": "bogus", "label": "y"})])
    db_session.rollback()


# -------------------------------------------------------------- write rules

def test_a_check_needs_a_rule(db_session):
    mgr = AuthorityResolutionManager()
    with pytest.raises(AuthorityInvalidError, match="needs a rule"):
        _saved(mgr, db_session, criteria=[CriterionInput(name="empty")])
    db_session.rollback()


def test_the_old_policy_link_is_no_longer_accepted_as_a_check(db_session):
    """A payload with only the removed policy_id has no rule, so it is refused, not dropped."""
    mgr = AuthorityResolutionManager()
    with pytest.raises(AuthorityInvalidError, match="needs a rule"):
        _saved(mgr, db_session, criteria=[CriterionInput.model_validate({"policy_id": str(uuid.uuid4())})])
    db_session.rollback()


@pytest.mark.parametrize("weight", [0, 0.0, 2.5])
def test_weights_zero_and_positive_are_kept(db_session, weight):
    mgr = AuthorityResolutionManager()
    rel = _saved(mgr, db_session, criteria=[CriterionInput(name="w", rule="obj.value <= 1", weight=weight)])
    assert rel.criteria[0].weight == float(weight)


@pytest.mark.parametrize("weight", [-1, float("nan"), float("inf")])
def test_weights_must_be_finite_and_non_negative(weight):
    with pytest.raises(ValidationError):
        CriterionInput(name="w", rule="obj.value <= 1", weight=weight)


def test_manager_also_refuses_a_bad_weight_in_a_dict_payload(db_session):
    """The manager is the second line: a dict payload skips the pydantic model."""
    mgr = AuthorityResolutionManager()
    with pytest.raises(AuthorityInvalidError):
        mgr.create_relation(db_session, {"name": "w", "criteria": [
            {"name": "w", "rule": "obj.value <= 1", "weight": -2}]})
    db_session.rollback()


def test_order_defaults_to_the_position_and_an_explicit_order_is_kept(db_session):
    mgr = AuthorityResolutionManager()
    rel = _saved(mgr, db_session, criteria=[
        CriterionInput(name="a", rule="obj.value <= 1"),
        CriterionInput(name="b", rule="obj.value <= 2", order=7),
        CriterionInput(name="c", rule="obj.value <= 3"),
    ])
    # Read back in display order: a (0), c (2), b (7).
    assert [(c["name"], c["order"]) for c in mgr.to_read_dict(db_session, rel)["criteria"]] == [
        ("a", 0), ("c", 2), ("b", 7)]


def test_new_version_copies_the_checks_with_their_provenance(db_session):
    mgr = AuthorityResolutionManager()
    src = _saved(mgr, db_session, criteria=[
        CriterionInput(name="Cap", rule="obj.value <= 0.15", weight=0.0,
                       copied_from={"kind": "compliance", "label": "Discount cap"}),
        CriterionInput(template_key="mfa_required", enabled=False),
    ])
    v2 = mgr.create_new_version(db_session, src.id, "2.0.0", current_user="lars@x.com")
    db_session.commit()
    copied = mgr.to_read_dict(db_session, v2)["criteria"]
    assert [(c["name"], c["rule"], c["weight"], c["enabled"]) for c in copied] == [
        ("Cap", "ASSERT obj.value <= 0.15", 0.0, True),
        ("MFA required", "ASSERT obj.mfa_verified = True", 1.0, False),
    ]
    assert copied[0]["copied_from"]["label"] == "Discount cap"
    assert copied[1]["copied_from"]["kind"] == "template"
    # The source still has its own rows: each version owns its checks.
    assert len(mgr.to_read_dict(db_session, src)["criteria"]) == 2


# ----------------------------------------------------- ak6 migration (data move)

def _load_migration(name):
    path = Path(__file__).resolve().parents[3] / "alembic" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ak6_chains_on_ak5():
    migration = _load_migration("ak6_authority_check_ownership")
    assert migration.revision == "ak6_authority_check_ownership"
    assert migration.down_revision == "ak5_authority_definition_tracking"


def _old_schema(conn):
    """The tables as they were before ak6 (only the columns the migration reads)."""
    conn.execute(text("""CREATE TABLE compliance_policies (
        id TEXT PRIMARY KEY, slug TEXT UNIQUE, name TEXT NOT NULL, description TEXT,
        failure_message TEXT, rule TEXT NOT NULL, category TEXT, severity TEXT,
        is_active BOOLEAN NOT NULL, created_at TEXT, updated_at TEXT)"""))
    conn.execute(text("""CREATE TABLE authority_criteria (
        id TEXT PRIMARY KEY, relation_id TEXT NOT NULL,
        compliance_policy_id TEXT NOT NULL REFERENCES compliance_policies(id) ON DELETE CASCADE,
        direction TEXT NOT NULL, weight REAL NOT NULL, dimension TEXT NOT NULL DEFAULT 'people',
        display_order INTEGER NOT NULL, enabled BOOLEAN NOT NULL, created_at TEXT)"""))
    conn.execute(text("CREATE INDEX ix_authority_criteria_compliance_policy_id ON authority_criteria (compliance_policy_id)"))
    conn.execute(text("CREATE INDEX ix_authority_criteria_relation_id ON authority_criteria (relation_id)"))
    conn.execute(text("CREATE TABLE maturity_gates (id TEXT PRIMARY KEY, compliance_policy_id TEXT)"))
    conn.execute(text("CREATE TABLE compliance_runs (id TEXT PRIMARY KEY, policy_id TEXT NOT NULL)"))


def _policy(conn, pid, name, category, slug, rule="ASSERT obj.value <= 1", message=None):
    conn.execute(text("""INSERT INTO compliance_policies (id, slug, name, failure_message, rule, category,
        severity, is_active, created_at, updated_at) VALUES (:id, :slug, :name, :msg, :rule, :cat,
        'high', 1, '2026-01-01', '2026-01-01')"""),
        {"id": pid, "slug": slug, "name": name, "msg": message, "rule": rule, "cat": category})


def _criterion(conn, cid, relation_id, policy_id, order=0):
    conn.execute(text("""INSERT INTO authority_criteria (id, relation_id, compliance_policy_id, direction,
        weight, dimension, display_order, enabled, created_at) VALUES (:id, :rel, :pid, 'neutral', 1.0,
        'people', :ord, 1, '2026-01-01')"""), {"id": cid, "rel": relation_id, "pid": policy_id, "ord": order})


def _run(engine, step):
    migration = _load_migration("ak6_authority_check_ownership")
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            getattr(migration, step)()


def test_ak6_upgrade_moves_rules_drops_the_link_and_deletes_only_orphans():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        _old_schema(conn)
        _policy(conn, "p-linked", "Discount cap", "Authority Decision", "ar-criterion-aaaaaaaaaaaa",
                rule="ASSERT obj.value <= 0.15", message="Too high.")
        _policy(conn, "p-gated", "Gated", "Authority Decision", "ar-criterion-bbbbbbbbbbbb")
        _policy(conn, "p-run", "Ran", "Authority Decision", "ar-criterion-cccccccccccc")
        _policy(conn, "p-orphan", "Orphan", "Authority Decision", "ar-criterion-dddddddddddd")
        _policy(conn, "p-user", "User wrote it", "Authority Decision", "risk-check-1")
        _policy(conn, "p-gov", "Governance", "Governance", "gov-1")
        _criterion(conn, "c-1", "ar-1", "p-linked")
        conn.execute(text("INSERT INTO maturity_gates VALUES ('g-1', 'p-gated')"))
        conn.execute(text("INSERT INTO compliance_runs VALUES ('r-1', 'p-run')"))
    _run(engine, "upgrade")

    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(authority_criteria)")).fetchall()}
        assert "compliance_policy_id" not in cols
        assert {"name", "rule", "failure_message", "copied_from"} <= cols
        row = conn.execute(text("SELECT name, rule, failure_message, copied_from FROM authority_criteria")).one()
        assert row[0] == "Discount cap"
        assert row[1] == "ASSERT obj.value <= 0.15"
        assert row[2] == "Too high."
        assert '"kind": "migrated"' in row[3] and '"id": "p-linked"' in row[3]
        remaining = {r[0] for r in conn.execute(text("SELECT id FROM compliance_policies")).fetchall()}
    # The orphan ARF policy is gone; the linked-before, gated, run-referenced, user-written and
    # non-ARF policies stay. The linked one is removed too: its rule now lives on the check.
    assert remaining == {"p-gated", "p-run", "p-user", "p-gov"}


def test_ak6_copy_is_a_function_the_upgrade_calls_and_it_reports_the_count():
    migration = _load_migration("ak6_authority_check_ownership")
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        _old_schema(conn)
        for ddl in ("name TEXT", "rule TEXT", "failure_message TEXT", "copied_from TEXT"):
            conn.execute(text(f"ALTER TABLE authority_criteria ADD COLUMN {ddl}"))
        _policy(conn, "p-1", "One", "Authority Decision", "ar-criterion-111111111111")
        _policy(conn, "p-2", "Two", "Authority Decision", "ar-criterion-222222222222")
        _criterion(conn, "c-1", "ar-1", "p-1")
        _criterion(conn, "c-2", "ar-1", "p-2", order=1)
        assert migration.copy_rules_from_policies(conn) == 2
        assert conn.execute(text("SELECT COUNT(*) FROM authority_criteria WHERE rule IS NOT NULL")).scalar() == 2


def test_ak6_downgrade_restores_one_linked_policy_per_check():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        _old_schema(conn)
        _policy(conn, "p-1", "Cap", "Authority Decision", "ar-criterion-333333333333", rule="ASSERT obj.value <= 1")
        _criterion(conn, "c-1", "ar-1", "p-1")
    _run(engine, "upgrade")
    _run(engine, "downgrade")
    with engine.connect() as conn:
        rows = conn.execute(text("""SELECT p.name, c.compliance_policy_id, p.rule, p.category
            FROM authority_criteria c JOIN compliance_policies p ON p.id = c.compliance_policy_id""")).fetchall()
    assert len(rows) == 1
    name, policy_id, rule, category = rows[0]
    assert (name, rule, category) == ("Cap", "ASSERT obj.value <= 1", "Authority Decision")
    assert policy_id
