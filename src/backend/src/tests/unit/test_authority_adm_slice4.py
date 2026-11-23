"""ARF 1.2.0 slice 4 (#1294): the shared ADM schema is the only evidence source.

Covers: no arbitrary evidence table, Admin-only and conformance-checked per-AR overrides,
the conformance check and the shipped DDL, the as-of read and the deterministic sample, the
statement polling, the signed DNA-Coefficient with one decision row per sampled row and the
ceiling gating on the magnitude, VERIFIED-only identity, resolve-time facts (unknown when
absent, not spoofable, recorded in provenance), the recompute job (retired skipped, cron
honoured, Admin-only), and the ao1 migration up and down.

The ADM reads go through ``AuthorityResolutionManager._adm_query`` (or the workspace client
for the statement poller), so no warehouse is needed.
"""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from src.common import adm
from src.common import authority_resolution_dna as dna
from src.common import authority_rule as arule
from src.common.adm_sql import AdmQueryError, run_query
from src.common.features import FeatureAccessLevel
from src.controller import authority_adm_manager as adm_mod
from src.controller.authority_adm_manager import AdmNonconformantError, AuthorityAdmManager
from src.controller.authority_resolution_manager import (
    AuthorityInvalidError,
    AuthorityPermissionError,
    AuthorityResolutionManager,
    STATUS_ACTIVE,
    STATUS_NEEDS_REVIEW,
    STATUS_RETIRED,
    _AdmSample,
)
from src.db_models.app_settings import AppSettingDb
from src.db_models.authority_resolution import AuthorityDecisionDb, AuthorityRelationDb
from src.models.authority_resolution import (
    AuthorityRelationCreate,
    AuthorityRelationUpdate,
    CriterionInput,
    EvidenceSlice,
)

SCHEMA = "demo.arf_adm"
NOW = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
SLICE = EvidenceSlice(action_codes=["approve"])
PASS_CHECK = CriterionInput(name="Not blocked", rule="ASSERT TRUE")
BACKEND_SRC = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------- helpers

def _conformant_columns():
    """``(table, column, data_type)`` rows exactly as information_schema reports the pinned subset."""
    return [
        (table, column, {"DECIMAL": "DECIMAL(20,4)", "INT": "INT", "BOOLEAN": "BOOLEAN",
                         "TIMESTAMP": "TIMESTAMP", "STRING": "STRING"}[logical])
        for table, spec in adm.TABLES.items() for column, logical in spec
    ]


def _manager(monkeypatch, *, conformant=True, observed=None, rows_by_table=None):
    """A manager whose ADM reads are faked. ``observed`` answers the sample read; the rest by table."""
    mgr = AuthorityResolutionManager()
    calls = []
    rows_by_table = rows_by_table or {}

    def fake_query(self, sql):
        calls.append(sql)
        if "observed_decision_provenance" in sql:
            return list(observed or [])
        for table, rows in rows_by_table.items():
            if f"`{table}`" in sql:
                return list(rows)
        return []

    monkeypatch.setattr(AuthorityResolutionManager, "_adm_query", fake_query)

    def fake_conformance(self, schema_fqn):
        cols = _conformant_columns() if conformant else _conformant_columns()[:-1]
        return adm.conformance_report(cols, schema_fqn=schema_fqn)

    monkeypatch.setattr(AuthorityAdmManager, "conformance", fake_conformance)
    mgr._calls = calls  # the SQL the test recorded
    return mgr


def _set_shared_schema(db, schema=SCHEMA):
    db.add(AppSettingDb(key=adm_mod.SHARED_SCHEMA_SETTING, value=schema))
    db.commit()


def _ar(mgr, db, slug, *, caller_is_admin=True, **kwargs):
    kwargs.setdefault("criteria", [PASS_CHECK])
    kwargs.setdefault("evidence_slice", SLICE)
    rel = mgr.create_relation(db, AuthorityRelationCreate(name=slug, slug=slug, **kwargs),
                              caller_is_admin=caller_is_admin)
    db.commit()
    return rel


def _obs(i, *, actor="ent-director", ctx='{"value": "12%", "escalated": false}', action="approve"):
    return {
        "observation_id": f"obs-{i}", "business_decision_id": f"bd-{i}", "action_code": action,
        "object_ref": "dp:promo-1", "actor_entity_id": actor, "actor_role": "APPROVER",
        "event_at": NOW - timedelta(days=i), "approval_evidence_id": f"ev-{i}", "context": ctx,
        "observation_status": "REPORTED",
    }


# ------------------------------------------------- 1. no arbitrary evidence table

def test_the_evidence_binding_fields_are_gone_from_the_request_model():
    assert "evidence_binding" not in AuthorityRelationCreate.__fields__
    assert "evidence_sources" not in AuthorityRelationCreate.__fields__
    assert "evidence_slice" in AuthorityRelationCreate.__fields__


def test_a_table_named_in_the_payload_is_ignored_and_never_stored(db_session, monkeypatch):
    mgr = _manager(monkeypatch)
    payload = AuthorityRelationCreate.parse_obj({
        "name": "Injected", "criteria": [PASS_CHECK.dict()],
        "evidence_binding": {"source_table_fqn": "hr.payroll.salaries", "column_map": {}},
    })
    rel = mgr.create_relation(db_session, payload)
    db_session.commit()
    assert rel.evidence_slice is None
    assert not hasattr(AuthorityRelationDb, "evidence_binding")


def test_the_evidence_read_touches_only_the_shared_schema(db_session, monkeypatch):
    mgr = _manager(monkeypatch, observed=[_obs(1), _obs(2)])
    _set_shared_schema(db_session)
    rel = _ar(mgr, db_session, "only-shared")
    sample = mgr._collect_evidence(db_session, rel, None)
    assert mgr._calls, "the read must run"
    for sql in mgr._calls:
        assert f"`demo`.`arf_adm`." in sql, sql[:120]
        assert "hr.payroll" not in sql
    assert len(sample.rows) == 2


def test_no_schema_configured_fails_closed_with_a_code(db_session, monkeypatch):
    mgr = _manager(monkeypatch)
    rel = _ar(mgr, db_session, "no-schema")
    with pytest.raises(adm.AdmError) as exc:
        mgr._collect_evidence(db_session, rel, None)
    assert exc.value.code == adm_mod.ADM_NOT_CONFIGURED
    assert mgr._calls == []


def test_an_ar_without_action_codes_cannot_read(db_session, monkeypatch):
    mgr = _manager(monkeypatch)
    _set_shared_schema(db_session)
    rel = _ar(mgr, db_session, "no-slice", evidence_slice=None)
    with pytest.raises(adm.AdmError) as exc:
        mgr._collect_evidence(db_session, rel, None)
    assert exc.value.code == "evidence_slice_empty"


def test_a_failed_read_records_a_generic_failure_on_the_run(db_session, monkeypatch):
    mgr = _manager(monkeypatch)
    _set_shared_schema(db_session)
    rel = _ar(mgr, db_session, "read-fails")

    def boom(self, sql):
        raise AdmQueryError("The ADM statement failed.", state="failed")

    monkeypatch.setattr(AuthorityResolutionManager, "_adm_query", boom)
    with pytest.raises(AdmQueryError):
        mgr.compute_dnaco(db_session, rel.id)
    db_session.commit()
    from src.repositories.authority_resolution_repository import authority_dna_run_repo
    run = authority_dna_run_repo.list_for_relation(db_session, relation_id=rel.id)[0]
    assert run.status == "failed"
    assert run.error_message == "The ADM statement failed."   # a coded, server-text-free message


# ------------------------------------------------------------- 2. the override

def test_a_non_admin_cannot_set_an_override_on_create(db_session, monkeypatch):
    mgr = _manager(monkeypatch)
    with pytest.raises(AuthorityPermissionError) as exc:
        _ar(mgr, db_session, "ovr-create", caller_is_admin=False, adm_schema_override="other.adm")
    assert exc.value.params["field"] == "adm_schema_override"


def test_a_non_admin_cannot_change_an_override_on_update(db_session, monkeypatch):
    mgr = _manager(monkeypatch)
    rel = _ar(mgr, db_session, "ovr-update")
    with pytest.raises(AuthorityPermissionError):
        mgr.update_relation(db_session, rel.id,
                            AuthorityRelationUpdate(adm_schema_override="other.adm"), caller_is_admin=False)


def test_an_admin_override_must_conform(db_session, monkeypatch):
    mgr = _manager(monkeypatch, conformant=False)
    with pytest.raises(AdmNonconformantError) as exc:
        _ar(mgr, db_session, "ovr-bad", adm_schema_override="other.adm")
    assert exc.value.code == adm_mod.ADM_NONCONFORMANT
    assert exc.value.report["status"] == "nonconformant"
    assert exc.value.report["findings"], "the refusal lists what to fix"


def test_a_conformant_override_is_stored_and_is_a_definition_change(db_session, monkeypatch):
    mgr = _manager(monkeypatch)
    rel = _ar(mgr, db_session, "ovr-ok", caller_is_admin=True)
    before = mgr.definition_hash(db_session, rel)
    mgr.update_relation(db_session, rel.id,
                        AuthorityRelationUpdate(adm_schema_override="other.adm_v2"), caller_is_admin=True)
    db_session.commit()
    rel = mgr.get_relation(db_session, rel.id)
    assert rel.adm_schema_override == "other.adm_v2"
    assert mgr.definition_hash(db_session, rel) != before


def test_the_override_wins_over_the_shared_schema(db_session, monkeypatch):
    mgr = _manager(monkeypatch, observed=[_obs(1)])
    _set_shared_schema(db_session)
    rel = _ar(mgr, db_session, "ovr-wins", caller_is_admin=True, adm_schema_override="lab.adm_test")
    assert mgr.effective_schema(db_session, rel) == "lab.adm_test"
    mgr._collect_evidence(db_session, rel, None)
    assert all("`lab`.`adm_test`" in sql for sql in mgr._calls)


# ------------------------------------------------------------- 3. conformance

def test_conformance_passes_with_extra_columns_and_fails_on_a_missing_or_mistyped_one():
    extra = _conformant_columns() + [("roles", "scratch_col", "STRING")]
    assert adm.conformance_report(extra)["status"] == "conformant"

    cols = [c for c in _conformant_columns() if not (c[0] == "entitlements" and c[1] == "claim_status")]
    cols = [(t, c, "INT" if (t, c) == ("roles", "valid_from") else dt) for t, c, dt in cols]
    report = adm.conformance_report(cols)
    codes = {(f["code"], f.get("table"), f.get("column")) for f in report["findings"]}
    assert report["status"] == "nonconformant"
    assert ("missing_column", "entitlements", "claim_status") in codes
    assert ("type_mismatch", "roles", "valid_from") in codes


def test_a_missing_table_is_a_finding():
    report = adm.conformance_report([c for c in _conformant_columns() if c[0] != "delegation_chains"])
    assert {"code": "missing_table", "table": "delegation_chains"} in report["findings"]


def test_normalise_uc_type_maps_parameterised_and_aliased_types():
    assert adm.normalise_uc_type("DECIMAL(20,4)") == adm.DECIMAL
    assert adm.normalise_uc_type("TIMESTAMP_NTZ") == adm.TIMESTAMP
    assert adm.normalise_uc_type("bigint") == adm.INT
    assert adm.normalise_uc_type("ARRAY<STRING>") == "ARRAY<STRING>"


def test_the_shipped_ddl_is_the_pinned_spec():
    shipped = (BACKEND_SRC / "data" / "adm" / "adm_v0_4_ddl.sql").read_text()
    assert shipped == adm.render_ddl("__CATALOG__", "__SCHEMA__")
    for table in adm.TABLES:
        assert f"`{table}`" in shipped


def test_the_demo_seed_creates_exactly_the_pinned_tables():
    import re
    seed = (BACKEND_SRC / "data" / "adm" / "adm_demo_seed.sql").read_text()
    created = set(re.findall(r"CREATE TABLE IF NOT EXISTS `demo`\.`arf_adm`\.`(\w+)`", seed))
    assert created == set(adm.TABLES)


def test_the_ddl_endpoint_text_is_idempotent_ddl():
    text = AuthorityAdmManager().ddl("lab.adm_test")
    assert "CREATE SCHEMA IF NOT EXISTS `lab`.`adm_test`" in text
    assert text.count("CREATE TABLE IF NOT EXISTS") == len(adm.TABLES)


def test_schema_identifiers_are_validated():
    with pytest.raises(adm.AdmError) as exc:
        adm.parse_schema_fqn("a.b.c")
    assert exc.value.code == "adm_schema_invalid"
    with pytest.raises(adm.AdmError):
        adm.parse_schema_fqn("cat.sch`; DROP TABLE x")
    assert adm.parse_schema_fqn("") is None


# ------------------------------------------------- 4. as-of read, sample, SQL

def test_the_observed_read_is_as_of_the_snapshot_and_seeded_and_capped():
    seed = adm.sample_seed("ar-1", "1.0.0", NOW - timedelta(days=90), NOW)
    sql = adm.observed_sample_sql(
        SCHEMA, action_codes=["approve"], object_refs=[], window_start=NOW - timedelta(days=90), window_end=NOW,
        as_of=NOW, seed=seed, sample_size=500,
    )
    assert "`demo`.`arf_adm`.`observed_decision_provenance`" in sql
    assert "recorded_at <= CAST(" in sql                  # system time as of the snapshot
    assert "superseded_at" not in sql                      # ADM 6.5 carries no superseded_at
    assert "dna_contribution_flag = true" in sql
    assert f"ORDER BY xxhash64('{seed}', observation_id), observation_id LIMIT 500" in sql
    assert "action_code IN ('approve')" in sql


def test_the_identity_read_is_verified_only_and_valid_at_the_snapshot():
    sql = adm.identity_links_sql(SCHEMA, as_of=NOW)
    assert "verification_status = 'VERIFIED'" in sql
    assert "valid_from <= CAST(" in sql
    assert "valid_to IS NULL OR valid_to >" in sql
    assert "superseded_at IS NULL OR superseded_at >" in sql


def test_a_row_is_valid_on_the_half_open_interval_only():
    clause = adm.as_of_clause("entitlements", at=NOW, valid_at=NOW)
    assert "valid_from <=" in clause and "valid_to IS NULL OR valid_to >" in clause
    assert adm.in_validity(NOW - timedelta(days=1), NOW, NOW) is False      # ends at NOW: [start, end)
    assert adm.in_validity(NOW, None, NOW) is True
    assert adm.in_validity(None, None, NOW) is False


def test_the_same_inputs_give_the_same_seed_and_text_and_other_inputs_do_not():
    start, end = NOW - timedelta(days=90), NOW
    seed = adm.sample_seed("ar-1", "1.0.0", start, end)
    assert seed == adm.sample_seed("ar-1", "1.0.0", start, end)
    assert seed != adm.sample_seed("ar-1", "1.1.0", start, end)
    assert seed != adm.sample_seed("ar-1", "1.0.0", start, end - timedelta(days=1))
    sql_a = adm.observed_sample_sql(SCHEMA, action_codes=["approve"], object_refs=[], window_start=start,
                                    window_end=end, as_of=NOW, seed=seed, sample_size=50)
    sql_b = adm.observed_sample_sql(SCHEMA, action_codes=["approve"], object_refs=[], window_start=start,
                                    window_end=end, as_of=NOW, seed=seed, sample_size=50)
    assert sql_a == sql_b


def test_the_sample_rows_are_reproducible_for_the_same_run(db_session, monkeypatch):
    mgr = _manager(monkeypatch, observed=[_obs(i) for i in range(1, 6)])
    _set_shared_schema(db_session)
    rel = _ar(mgr, db_session, "repro")
    run = SimpleNamespace(started_at=NOW)
    first = mgr._collect_evidence(db_session, rel, run)
    second = mgr._collect_evidence(db_session, rel, run)
    assert first.rows == second.rows
    assert first.basis == second.basis
    assert first.basis["seed"] == adm.sample_seed(rel.id, rel.version,
                                                  NOW.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=90),
                                                  NOW.replace(hour=0, minute=0, second=0, microsecond=0))


def test_run_query_polls_until_succeeded_and_types_the_rows():
    sleeps = []

    class Stmt:
        def __init__(self):
            self.polls = 0

        def execute_statement(self, **kw):
            return SimpleNamespace(statement_id="s1", status=SimpleNamespace(state="PENDING"))

        def get_statement(self, sid):
            self.polls += 1
            if self.polls == 1:
                return SimpleNamespace(statement_id=sid, status=SimpleNamespace(state="RUNNING"))
            cols = [SimpleNamespace(name="share", type_name=SimpleNamespace(value="DECIMAL")),
                    SimpleNamespace(name="ok", type_name=SimpleNamespace(value="BOOLEAN")),
                    SimpleNamespace(name="at", type_name=SimpleNamespace(value="TIMESTAMP"))]
            return SimpleNamespace(
                statement_id=sid, status=SimpleNamespace(state="SUCCEEDED"),
                manifest=SimpleNamespace(schema=SimpleNamespace(columns=cols)),
                result=SimpleNamespace(data_array=[["0.15", "true", "2026-11-01T00:00:00Z"]]),
            )

    ws = SimpleNamespace(statement_execution=Stmt())
    rows = run_query("SELECT 1", ws=ws, warehouse_id="wh", sleep=sleeps.append, clock=lambda: 0.0)
    assert rows == [{"share": 0.15, "ok": True, "at": datetime(2026, 11, 1, tzinfo=timezone.utc)}]
    assert sleeps == [1.0, 1.0]  # PENDING and RUNNING each wait one poll interval


def test_a_failed_statement_raises_a_code_not_the_server_text():
    class Stmt:
        def execute_statement(self, **kw):
            return SimpleNamespace(statement_id="s2", status=SimpleNamespace(
                state="FAILED", error=SimpleNamespace(message="PERMISSION_DENIED: user x on hr.payroll")))

    with pytest.raises(AdmQueryError) as exc:
        run_query("SELECT 1", ws=SimpleNamespace(statement_execution=Stmt()), warehouse_id="wh",
                  sleep=lambda s: None, clock=lambda: 0.0)
    assert exc.value.code == "adm_query_failed"
    assert "PERMISSION_DENIED" not in str(exc.value)
    assert "hr.payroll" not in str(exc.value)


def test_a_statement_that_never_finishes_times_out_and_is_cancelled():
    cancelled = []

    class Stmt:
        def execute_statement(self, **kw):
            return SimpleNamespace(statement_id="s3", status=SimpleNamespace(state="RUNNING"))

        def get_statement(self, sid):
            return SimpleNamespace(statement_id=sid, status=SimpleNamespace(state="RUNNING"))

        def cancel_execution(self, sid):
            cancelled.append(sid)

    clock_values = iter([0.0, 0.0, 100.0, 100.0, 100.0])
    with pytest.raises(AdmQueryError) as exc:
        run_query("SELECT 1", ws=SimpleNamespace(statement_execution=Stmt()), warehouse_id="wh", timeout_s=10,
                  sleep=lambda s: None, clock=lambda: next(clock_values))
    assert exc.value.code == "adm_query_timeout"
    assert cancelled == ["s3"]


def test_no_warehouse_is_a_coded_refusal():
    with pytest.raises(AdmQueryError) as exc:
        run_query("SELECT 1", ws=SimpleNamespace(), warehouse_id=None)
    assert exc.value.code == "adm_no_warehouse"


def test_typed_values_follow_the_manifest_type_and_percentages_are_shares():
    assert adm.coerce_value("15%", adm.DECIMAL) == pytest.approx(0.15)
    assert adm.coerce_value("3", adm.INT) == 3
    assert adm.coerce_value("yes", adm.BOOLEAN) is True
    assert adm.coerce_value("maybe", adm.BOOLEAN) is None
    assert adm.coerce_value("not a number", adm.DECIMAL) is None   # an unknown, never a guess
    assert adm.parse_timestamp("2026-11-01T00:00:00Z").tzinfo is not None


# ----------------------------------------------------- 5. identity (VERIFIED only)

def test_the_identity_index_drops_ambiguous_aliases_and_keeps_the_unambiguous_ones():
    alias_by_entity, entity_by_alias = adm.identity_index([
        {"source_id": "a@x", "entity_id": "E1"},
        {"source_id": "a@x", "entity_id": "E2"},          # ambiguous: fails closed
        {"source_id": "b@x", "entity_id": "E1"},
    ])
    assert "a@x" not in entity_by_alias
    assert entity_by_alias == {"b@x": "E1"}
    assert alias_by_entity == {"E1": "b@x"}


def test_an_actor_without_a_verified_link_is_unknown_and_its_row_is_skipped(db_session, monkeypatch):
    # The identity read returns nothing for the actor (its link is PENDING, so not VERIFIED).
    mgr = _manager(monkeypatch, observed=[_obs(1, actor="ent-pending")],
                   rows_by_table={"source_identity_map": []})
    _set_shared_schema(db_session)
    rel = _ar(mgr, db_session, "unverified")
    sample = mgr._collect_evidence(db_session, rel, SimpleNamespace(started_at=NOW))
    assert sample.rows[0]["actor_identity"] is None
    assert sample.rows[0]["actor_identity_status"] == "UNKNOWN"
    assert sample.basis["identity_unknown"] == 1
    # A check that reads the actor can't decide the row, so the row is skipped, not divergent.
    result = dna.compute_dnaco([dna.Criterion(code="who", rule="ASSERT obj.actor_identity = 'x@y'")], sample.rows)
    assert result.sampled_count == 0 and result.skipped_count == 1


def test_a_verified_actor_is_read_by_its_alias(db_session, monkeypatch):
    mgr = _manager(monkeypatch, observed=[_obs(1, actor="ent-director")],
                   rows_by_table={"source_identity_map": [{"source_id": "director@x", "entity_id": "ent-director"}]})
    _set_shared_schema(db_session)
    rel = _ar(mgr, db_session, "verified")
    sample = mgr._collect_evidence(db_session, rel, SimpleNamespace(started_at=NOW))
    assert sample.rows[0]["actor_identity"] == "director@x"
    assert sample.rows[0]["actor_identity_status"] == "VERIFIED"
    assert sample.basis["identity_unknown"] == 0


def test_the_context_carries_the_canonical_value_as_a_share():
    row = adm.observation_row(_obs(1, ctx='{"value": "22%", "budget_usd": 150000, "action": "spoof"}'),
                              actor_identity="a@x", identity_status="VERIFIED")
    assert row["value"] == pytest.approx(0.22)
    assert row["budget_usd"] == 150000
    assert row["action"] == "approve"          # a context key never overrides a canonical field


# ---------------------------------------------------------------- 6. DNA engine

def _crit(rule, direction, name, dimension="people", weight=1.0):
    return dna.Criterion(code=name, rule=rule, direction=direction, weight=weight, dimension=dimension)


def test_the_run_keeps_one_decision_row_per_sampled_row(db_session, monkeypatch):
    mgr = _manager(monkeypatch)
    rel = _ar(mgr, db_session, "per-row", criteria=[
        CriterionInput(name="cap", rule="ASSERT obj.value <= 0.15", direction=dna.DIR_ACTUAL_EXCEEDS),
    ])
    run = mgr.compute_dnaco(db_session, rel.id, rows=[
        {"actor_identity": "a", "value": 0.22},
        {"actor_identity": "a", "value": 0.10},
        {"actor_identity": "a", "value": 0.11},
    ], requested_by="alice")
    db_session.commit()
    decisions = db_session.query(AuthorityDecisionDb).filter(AuthorityDecisionDb.dna_run_id == run.id).all()
    assert len(decisions) == 3
    assert sorted(d.divergence_magnitude for d in decisions) == [0.0, 0.0, 1.0]
    assert run.sample_basis["requested_by"] == "alice"
    assert run.sample_basis["method_version"] == adm.DNA_METHOD_VERSION
    assert run.position == pytest.approx(1.0 / 3.0, abs=1e-4)   # one +1 breach among three equal-weight rows


def test_no_cancellation_between_dimensions_and_the_position_is_signed():
    a = _crit("ASSERT obj.actor_identity IN ['ok']", dna.DIR_ACTUAL_EXCEEDS, "ppl", "people")
    b = _crit("ASSERT obj.value <= 10", dna.DIR_DOCUMENTED_EXCEEDS, "pol", "policy")
    r = dna.compute_dnaco([a, b], [{"actor_identity": "bad", "value": 5}, {"actor_identity": "ok", "value": 50}])
    assert r.magnitude == 1.0
    assert r.position == 0.0


def test_the_ceiling_gates_on_the_magnitude_not_the_position(db_session, monkeypatch):
    mgr = _manager(monkeypatch)
    rel = _ar(mgr, db_session, "ceiling", criteria=[
        CriterionInput(name="up", rule="ASSERT obj.value <= 0.15", direction=dna.DIR_ACTUAL_EXCEEDS),
        CriterionInput(name="down", rule="ASSERT obj.cosign_present = True", direction=dna.DIR_DOCUMENTED_EXCEEDS),
    ])
    rel.status = STATUS_ACTIVE
    db_session.commit()
    # Two of four rows diverge in opposite directions: magnitude 0.5, position 0.
    mgr.compute_dnaco(db_session, rel.id, rows=[
        {"actor_identity": "a", "value": 0.22, "cosign_present": True},     # up
        {"actor_identity": "a", "value": 0.10, "cosign_present": False},    # down
        {"actor_identity": "a", "value": 0.10, "cosign_present": True},
        {"actor_identity": "a", "value": 0.10, "cosign_present": True},
    ])
    db_session.commit()
    rel = mgr.get_relation(db_session, rel.id)
    assert rel.dna_magnitude == 0.5
    assert rel.dna_position == 0.0
    assert rel.status == STATUS_NEEDS_REVIEW


def test_a_magnitude_under_the_ceiling_does_not_flag(db_session, monkeypatch):
    mgr = _manager(monkeypatch)
    rel = _ar(mgr, db_session, "under-ceiling", criteria=[
        CriterionInput(name="heavy", rule="ASSERT obj.value <= 0.15", direction=dna.DIR_ACTUAL_EXCEEDS, weight=5.0),
    ])
    rel.status = STATUS_ACTIVE
    db_session.commit()
    rows = [{"actor_identity": "a", "value": 0.10}] * 9 + [{"actor_identity": "a", "value": 0.30}]
    mgr.compute_dnaco(db_session, rel.id, rows=rows)
    db_session.commit()
    rel = mgr.get_relation(db_session, rel.id)
    # One breach in ten: magnitude 0.1 (under the 0.3 ceiling), position = 5 / (5 * 10) = 0.1.
    assert rel.dna_magnitude == 0.1
    assert rel.dna_position == pytest.approx(0.1)
    assert rel.status == STATUS_ACTIVE


def test_the_structural_dimension_is_shown_but_does_not_gate(db_session, monkeypatch):
    mgr = _manager(monkeypatch)
    rel = _ar(mgr, db_session, "structural")
    run = mgr.compute_dnaco(db_session, rel.id, rows=[{"actor_identity": "a", "value": 0.0}])
    assert run.per_dimension_scores["structural"]["kind"] == "definition"
    assert run.magnitude == 0.0


def test_a_legacy_run_with_float_dimensions_is_still_readable(db_session, monkeypatch):
    mgr = _manager(monkeypatch)
    rel = _ar(mgr, db_session, "legacy-read")
    rel.dna_dimensions = {"people": 0.08, "policy": 0.07, "structural": 0.0}   # the pre-slice-4 shape
    rel.dna_magnitude = 0.15
    db_session.commit()
    read = mgr.to_read_dict(db_session, rel)
    assert read["dna_dimensions"]["people"] == 0.08
    assert read["adm_schema"] is None


# ------------------------------------------------------ 7. resolve-time facts

def _facts_inputs(*, verified=True, revoked=False, claim="VERIFIED", valid_to=None):
    identity = [{"source_id": "director@x", "entity_id": "ent-director", "valid_from": NOW - timedelta(days=30),
                 "valid_to": None}] if verified else []
    entitlement = {"entitlement_id": "e1", "entity_id": "ent-director", "role_id": "approver",
                   "valid_from": NOW - timedelta(days=10), "valid_to": valid_to,
                   "revoked_at": NOW - timedelta(hours=1) if revoked else None, "claim_status": claim}
    role = {"role_id": "approver", "permissions": '["approve", "escalate"]',
            "valid_from": NOW - timedelta(days=100), "valid_to": None}
    return {"authority_links": identity, "entitlement": entitlement, "role": role}


def test_facts_are_current_only_when_verified_unrevoked_and_in_window():
    ok = _facts_inputs()
    now = NOW
    current = adm.derive_facts(identity={"entity_id": "ent-director"}, entitlements=[ok["entitlement"]],
                               roles=[ok["role"]], delegations=[], at=now)
    assert current["entitlement_current"] is True
    assert current["role_codes"] == ["approve", "escalate"]
    assert current["identity_verified"] is True

    revoked = adm.derive_facts(identity={"entity_id": "ent-director"},
                               entitlements=[_facts_inputs(revoked=True)["entitlement"]], roles=[], delegations=[], at=now)
    assert revoked["entitlement_current"] is False

    expired = adm.derive_facts(identity={"entity_id": "ent-director"},
                               entitlements=[_facts_inputs(valid_to=NOW - timedelta(days=1))["entitlement"]],
                               roles=[], delegations=[], at=now)
    assert expired["entitlement_current"] is False

    asserted = adm.derive_facts(identity={"entity_id": "ent-director"},
                                entitlements=[_facts_inputs(claim="ASSERTED")["entitlement"]], roles=[],
                                delegations=[], at=now)
    assert asserted["entitlement_current"] is False


def test_an_unverified_caller_has_unknown_entitlement_facts():
    facts = adm.derive_facts(identity=None, entitlements=[], roles=[], delegations=[], at=NOW)
    assert facts["identity_verified"] is False
    assert facts["entitlement_current"] is None
    assert facts["delegation_active"] is None


def test_a_fact_with_no_schema_is_unknown_so_the_rule_fails_closed(db_session, monkeypatch):
    mgr = _manager(monkeypatch)
    rel = _ar(mgr, db_session, "fact-closed", actor_role="approver", criteria=[
        CriterionInput(name="Current entitlement", rule="ASSERT fact.entitlement_current = True",
                       failure_message="No current entitlement."),
    ])
    result = mgr.resolve(db_session, rel.id, {"actor_identity": "director@x"}, record=False, require_active=False)
    assert result["verdict"] == "denied"
    assert "fact.entitlement_current" in result["reason"] or "entitlement_current" in result["reason"]


def test_a_fact_read_from_the_schema_decides_and_is_recorded(db_session, monkeypatch):
    inputs = _facts_inputs()

    def fake_query(self, sql):
        if "source_identity_map" in sql:
            return inputs["authority_links"]
        if "`entitlements`" in sql:
            return [inputs["entitlement"]]
        if "`roles`" in sql:
            return [inputs["role"]]
        return []

    monkeypatch.setattr(AuthorityResolutionManager, "_adm_query", fake_query)
    monkeypatch.setattr(AuthorityAdmManager, "conformance",
                        lambda self, s: adm.conformance_report(_conformant_columns(), schema_fqn=s))
    mgr = AuthorityResolutionManager()
    _set_shared_schema(db_session)
    rel = _ar(mgr, db_session, "fact-ok", actor_role="approver", criteria=[
        CriterionInput(name="Current entitlement", rule="ASSERT fact.entitlement_current = True"),
    ])
    rel.status = STATUS_ACTIVE
    db_session.commit()
    result = mgr.resolve(db_session, rel.id, {"actor_identity": "director@x"})
    db_session.commit()
    assert result["verdict"] == "approved"
    decision = db_session.query(AuthorityDecisionDb).filter(AuthorityDecisionDb.relation_id == rel.id).first()
    assert decision.provenance["facts"]["values"]["entitlement_current"] is True


def test_a_request_cannot_spoof_a_fact(db_session, monkeypatch):
    mgr = _manager(monkeypatch)
    rel = _ar(mgr, db_session, "spoof", criteria=[
        CriterionInput(name="Current entitlement", rule="ASSERT fact.entitlement_current = True"),
    ])
    result = mgr.resolve(db_session, rel.id,
                         {"actor_identity": "director@x", "fact": {"entitlement_current": True}},
                         record=False, require_active=False)
    assert result["verdict"] == "denied"


def test_the_evaluation_object_drops_a_request_fact_namespace():
    obj = arule.evaluation_object({"fact": {"entitlement_current": True}, "value": 1}, {}, policy_ref={})
    assert obj[arule.NS_FACT] == {}
    assert "fact" in arule.RESERVED_KEYS


def test_an_unknown_fact_name_is_refused_on_save(db_session, monkeypatch):
    mgr = _manager(monkeypatch)
    with pytest.raises(AuthorityInvalidError):
        _ar(mgr, db_session, "bad-fact", criteria=[
            CriterionInput(name="Typo", rule="ASSERT fact.entitlement_valid_form = '2020'"),
        ])


# ------------------------------------------------------------- 8. recompute job

def test_recompute_skips_retired_and_ars_whose_cron_has_not_fired(db_session, monkeypatch):
    mgr = _manager(monkeypatch)
    now = mgr._now()
    due = _ar(mgr, db_session, "due", schedule_cron="0 0 6 * * ?")
    not_due = _ar(mgr, db_session, "measured-after-fire", schedule_cron="0 0 6 * * ?")
    retired = _ar(mgr, db_session, "retired", schedule_cron="0 0 6 * * ?")
    retired.status = STATUS_RETIRED
    from src.common.quartz_cron import previous_run
    fire = previous_run("0 0 6 * * ?", None, now)
    due.dna_measured_at = fire - timedelta(days=2)
    not_due.dna_measured_at = fire + timedelta(minutes=1)
    db_session.commit()

    calls = []

    def fake_compute(self, db, relation_id, rows=None, *, requested_by=None):
        calls.append((relation_id, requested_by))
        return SimpleNamespace(id="run", status="succeeded", magnitude=0.0)

    monkeypatch.setattr(AuthorityResolutionManager, "compute_dnaco", fake_compute)
    summary = mgr.recompute_scheduled(db_session)
    by_id = {r["relation_id"]: r for r in summary["results"]}
    assert by_id[retired.id]["reason"] == "retired"
    assert by_id[not_due.id]["reason"] == "not_due"
    assert calls == [(due.id, "scheduled")]


def test_an_ar_never_measured_is_due_once_its_cron_is_set(db_session, monkeypatch):
    mgr = _manager(monkeypatch)
    rel = _ar(mgr, db_session, "never-measured", schedule_cron="0 0 6 * * ?")
    assert mgr._is_due(rel, mgr._now()) is True


def test_an_unparseable_cron_is_skipped_not_fatal(db_session, monkeypatch):
    mgr = _manager(monkeypatch)
    rel = _ar(mgr, db_session, "bad-cron")
    rel.schedule_cron = "not a cron"
    db_session.commit()
    summary = mgr.recompute_scheduled(db_session)
    result = next(r for r in summary["results"] if r["relation_id"] == rel.id)
    assert result["status"] == "skipped" and result["reason"] == "invalid_schedule"


def test_the_workflow_config_helper_sets_the_warehouse_and_initialises_settings(monkeypatch):
    from src.common import workflow_config
    calls = []
    monkeypatch.setattr("src.common.config.init_config", lambda: calls.append("init"))
    monkeypatch.setenv("DATABRICKS_HOST", "https://ws.example")
    monkeypatch.setenv("DATABRICKS_WAREHOUSE_ID", "")   # restored by monkeypatch at teardown
    ws = SimpleNamespace(config=SimpleNamespace(host=None))
    workflow_config.initialize_application_config(ws, warehouse_id="wh-123")
    import os
    assert os.environ["DATABRICKS_WAREHOUSE_ID"] == "wh-123"
    assert calls == ["init"]


def test_the_compliance_job_wrapper_still_initialises_without_a_warehouse(monkeypatch):
    from src.workflows.compliance_checks import compliance_checks as job
    seen = {}

    def fake(ws, warehouse_id=None):
        seen["warehouse"] = warehouse_id

    monkeypatch.setattr("src.common.workflow_config.initialize_application_config", fake)
    job._initialize_application_config(SimpleNamespace())
    assert seen == {"warehouse": None}


def _route(path, method):
    import src.routes.authority_resolution_routes as routes
    for route in routes.router.routes:
        if route.path == path and method in route.methods:
            return route
    raise AssertionError(f"no route {method} {path}")


def _required_level(route):
    from src.common.authorization import PermissionChecker
    for dep in route.dependant.dependencies:
        if isinstance(dep.call, PermissionChecker):
            return dep.call.required_level
    return None


@pytest.mark.parametrize("path, method, level", [
    ("/api/authority/recompute-scheduled", "POST", FeatureAccessLevel.ADMIN),
    ("/api/authority/adm-schema", "PUT", FeatureAccessLevel.ADMIN),
    ("/api/authority/adm-schema", "GET", FeatureAccessLevel.READ_ONLY),
    ("/api/authority/adm-schema/ddl", "GET", FeatureAccessLevel.READ_ONLY),
    ("/api/authority/relations/{relation_id}/compute-dnaco", "POST", FeatureAccessLevel.READ_WRITE),
])
def test_the_adm_and_recompute_routes_carry_the_permission_matrix_level(path, method, level):
    assert _required_level(_route(path, method)) == level


# ----------------------------------------------------------------- 9. migration

def _load_migration():
    path = BACKEND_SRC.parent / "alembic" / "versions" / "ao1_authority_adm_schema.py"
    spec = importlib.util.spec_from_file_location("ao1_authority_adm_schema", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_ao1_migration_moves_table_evidence_to_a_slice_and_back():
    mig = _load_migration()
    assert mig.revision == "ao1_authority_adm_schema"
    assert mig.down_revision == "an1_authority_policy_references"
    eng = sa.create_engine("sqlite://")
    with eng.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE authority_relations (id VARCHAR PRIMARY KEY, action VARCHAR, "
                             "evidence_binding JSON, evidence_sources JSON)")
        conn.exec_driver_sql("CREATE TABLE authority_dna_runs (id VARCHAR PRIMARY KEY)")
        conn.exec_driver_sql(
            "INSERT INTO authority_relations VALUES "
            "('with-action', 'approve', '{\"source_table_fqn\": \"t.a.b\"}', NULL), "
            "('no-action', NULL, '{\"source_table_fqn\": \"t.a.b\"}', NULL), "
            "('no-table', 'approve', NULL, NULL)"
        )
    with eng.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            mig.upgrade()
    with eng.begin() as conn:
        cols = {c["name"] for c in sa.inspect(conn).get_columns("authority_relations")}
        assert "evidence_slice" in cols and "adm_schema_override" in cols and "dna_position" in cols
        assert "evidence_binding" not in cols and "evidence_sources" not in cols
        rows = dict(conn.execute(sa.text("SELECT id, evidence_slice FROM authority_relations")).all())
    assert rows["no-action"] is None and rows["no-table"] is None
    import json
    slice_ = json.loads(rows["with-action"])
    assert slice_["action_codes"] == ["approve"] and slice_["domain_scope"] is True

    with eng.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            mig.downgrade()
    with eng.begin() as conn:
        cols = {c["name"] for c in sa.inspect(conn).get_columns("authority_relations")}
        assert "evidence_binding" in cols and "evidence_sources" in cols
        assert "evidence_slice" not in cols and "dna_position" not in cols
        run_cols = {c["name"] for c in sa.inspect(conn).get_columns("authority_dna_runs")}
        assert "position" not in run_cols and "sample_basis" not in run_cols
