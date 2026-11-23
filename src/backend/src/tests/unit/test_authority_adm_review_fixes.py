"""ARF 1.2.0 slice 4 review fixes (#1294): the code-review findings on the slice 4 commits.

One test group per finding: the fact namespace is strict-only, legacy action codes and stored
slices that no longer validate, the job's warehouse parameter, delegation facts scoped to the
AR's role, ADM routes that don't block the loop and a stored conformance result, SDK failures
as coded errors, weight-0 checks that never gate, batched identity reads without truncation,
and result chunks followed up to a cap with truncation recorded.
"""
import importlib.util
import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from src.common import adm
from src.common import authority_resolution_dna as dna
from src.common.adm_sql import AdmQueryError, AdmRows, run_query, ADM_RESULT_TRUNCATED
from src.controller import authority_adm_manager as adm_mod
from src.controller.authority_adm_manager import AdmPermissionError, AuthorityAdmManager
from src.controller.authority_resolution_manager import AuthorityResolutionManager, _AdmSample
from src.models.authority_resolution import AuthorityRelationCreate, CriterionInput, EvidenceSlice

BACKEND_SRC = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
SCHEMA = "demo.arf_adm"


def _conformant_columns():
    return [(t, c, {"DECIMAL": "DECIMAL(20,4)", "INT": "INT", "BOOLEAN": "BOOLEAN",
                    "TIMESTAMP": "TIMESTAMP", "STRING": "STRING"}[logical])
            for t, spec in adm.TABLES.items() for c, logical in spec]


def _set_schema(db, schema=SCHEMA):
    from src.db_models.app_settings import AppSettingDb
    db.add(AppSettingDb(key=adm_mod.SHARED_SCHEMA_SETTING, value=schema))
    db.commit()


def _ar(mgr, db, slug, **kwargs):
    kwargs.setdefault("criteria", [CriterionInput(name="Not blocked", rule="ASSERT TRUE")])
    kwargs.setdefault("evidence_slice", EvidenceSlice(action_codes=["approve"]))
    rel = mgr.create_relation(db, AuthorityRelationCreate(name=slug, slug=slug, **kwargs), caller_is_admin=True)
    db.commit()
    return rel


# ------------------------------------------- 1. action codes: migration and reads never raise

def _load_migration():
    path = BACKEND_SRC.parent / "alembic" / "versions" / "ao1_authority_adm_schema.py"
    spec = importlib.util.spec_from_file_location("ao1_authority_adm_schema", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migration_grammar_is_the_app_grammar():
    assert _load_migration().ACTION_CODE_RE.pattern == adm.ACTION_CODE_PATTERN


@pytest.mark.parametrize("raw, expected", [
    ("Approve Budget!", "approve_budget"),
    ("  Escalate  ", "escalate"),
    ("Pending: x", "pending:_x"),
    ("1st approve", "st_approve"),
    ("!!!", None),
    ("", None),
])
def test_the_migration_normalises_legacy_actions_and_drops_what_still_does_not_match(raw, expected):
    assert _load_migration().normalise_action_code(raw) == expected


def test_the_migration_writes_normalised_codes_and_no_slice_for_an_unusable_action():
    mig = _load_migration()
    eng = sa.create_engine("sqlite://")
    with eng.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE authority_relations (id VARCHAR PRIMARY KEY, action VARCHAR, "
                             "evidence_binding JSON, evidence_sources JSON)")
        conn.exec_driver_sql("CREATE TABLE authority_dna_runs (id VARCHAR PRIMARY KEY)")
        conn.exec_driver_sql(
            "INSERT INTO authority_relations VALUES "
            "('legacy', 'Approve Budget!', '{\"source_table_fqn\": \"t.a.b\"}', NULL), "
            "('junk', '!!!', '{\"source_table_fqn\": \"t.a.b\"}', NULL)")
    with eng.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            mig.upgrade()
    with eng.begin() as conn:
        rows = dict(conn.execute(sa.text("SELECT id, evidence_slice FROM authority_relations")).all())
    import json
    assert json.loads(rows["legacy"])["action_codes"] == ["approve_budget"]
    assert rows["junk"] is None


def test_a_stored_slice_that_no_longer_validates_never_breaks_the_definition_hash(db_session, monkeypatch):
    mgr = AuthorityResolutionManager()
    rel = _ar(mgr, db_session, "stored-bad")
    rel.evidence_slice = {"action_codes": ["Bad Code!", "approve"], "object_refs": [],
                          "domain_scope": True, "window_days": 90, "sample_size": 500}
    db_session.commit()
    assert len(mgr.definition_hash(db_session, rel)) == 64   # no exception


def test_a_stored_slice_reads_its_valid_codes_and_flags_the_invalid_ones(db_session, monkeypatch):
    mgr = AuthorityResolutionManager()
    _set_schema(db_session)
    rel = _ar(mgr, db_session, "stored-flag")
    rel.evidence_slice = {"action_codes": ["Bad Code!", "approve"], "object_refs": [],
                          "domain_scope": True, "window_days": 90, "sample_size": 500}
    db_session.commit()
    seen = []

    def fake(self, sql, **kwargs):
        seen.append(sql)
        return AdmRows()

    monkeypatch.setattr(AuthorityResolutionManager, "_adm_query", fake)
    sample = mgr._collect_evidence(db_session, rel, SimpleNamespace(started_at=NOW))
    assert sample.basis["invalid_action_codes"] == ["Bad Code!"]
    assert "action_code IN ('approve')" in seen[0]


def test_a_stored_slice_with_only_invalid_codes_fails_the_read_with_a_code_not_a_crash(db_session, monkeypatch):
    mgr = AuthorityResolutionManager()
    _set_schema(db_session)
    rel = _ar(mgr, db_session, "stored-none")
    rel.evidence_slice = {"action_codes": ["Bad Code!"], "object_refs": [], "domain_scope": True,
                          "window_days": 90, "sample_size": 500}
    db_session.commit()
    with pytest.raises(adm.AdmError) as exc:
        mgr._collect_evidence(db_session, rel, SimpleNamespace(started_at=NOW))
    assert exc.value.code == "evidence_slice_empty"


def test_writing_an_invalid_action_code_is_still_refused(db_session):
    mgr = AuthorityResolutionManager()
    with pytest.raises(adm.AdmError) as exc:
        _ar(mgr, db_session, "write-bad", evidence_slice=EvidenceSlice(action_codes=["Bad Code!"]))
    assert exc.value.code == "evidence_slice_invalid"


# ------------------------------------------- 2. the recompute job gets the warehouse

def test_the_job_parameters_inject_the_configured_warehouse_over_an_empty_saved_value():
    from src.controller.jobs_manager import JobsManager
    manager = JobsManager(db=MagicMock(), ws_client=MagicMock(),
                          settings=SimpleNamespace(DATABRICKS_WAREHOUSE_ID="wh-9"))
    manager.get_workflow_configuration = MagicMock(return_value={"databricks_warehouse_id": ""})
    manager._get_workflow_definition = MagicMock(return_value={"parameters": {"databricks_warehouse_id": ""}})
    merged = manager.get_merged_job_parameters("authority_dna_recompute")
    assert merged["databricks_warehouse_id"] == "wh-9"


def test_the_warehouse_is_not_injected_into_a_workflow_that_does_not_declare_it():
    from src.controller.jobs_manager import JobsManager
    manager = JobsManager(db=MagicMock(), ws_client=MagicMock(),
                          settings=SimpleNamespace(DATABRICKS_WAREHOUSE_ID="wh-9"))
    manager.get_workflow_configuration = MagicMock(return_value=None)
    manager._get_workflow_definition = MagicMock(return_value={"parameters": {"verbose": "false"}})
    assert "databricks_warehouse_id" not in manager.get_merged_job_parameters("uc_tag_sync")


def test_the_recompute_job_fails_once_with_a_code_when_no_warehouse_is_passed():
    from src.workflows.authority_dna_recompute import authority_dna_recompute as job
    with pytest.raises(AdmQueryError) as exc:
        job.require_warehouse("  ")
    assert exc.value.code == "adm_no_warehouse"
    job.require_warehouse("wh-1")   # no error


# ------------------------------------------- 3. delegation facts are for the AR's role

def test_a_delegation_for_another_role_does_not_make_the_fact_true():
    delegations = [{"role_id": "finance-controller", "valid_from": NOW - timedelta(days=5), "valid_to": None}]
    facts = adm.derive_facts(identity={"entity_id": "E1"}, entitlements=[], roles=[], delegations=delegations,
                             at=NOW, role_id="trade-director")
    assert facts["delegation_active"] is False


def test_a_current_delegation_for_the_ars_role_is_active():
    delegations = [{"role_id": "trade-director", "valid_from": NOW - timedelta(days=5), "valid_to": None}]
    facts = adm.derive_facts(identity={"entity_id": "E1"}, entitlements=[], roles=[], delegations=delegations,
                             at=NOW, role_id="trade-director")
    assert facts["delegation_active"] is True


def test_an_ar_without_a_role_has_an_unknown_delegation_fact():
    facts = adm.derive_facts(identity={"entity_id": "E1"}, entitlements=[], roles=[], delegations=[],
                             at=NOW, role_id=None)
    assert facts["delegation_active"] is None


# ------------------------------------------- 4. ADM routes: sync, stored conformance, check action

def test_the_adm_routes_are_sync_so_the_polling_runs_in_the_threadpool():
    import src.routes.authority_resolution_routes as routes
    for fn in (routes.get_adm_schema, routes.put_adm_schema, routes.check_adm_schema):
        assert not inspect.iscoroutinefunction(fn), fn.__name__


def test_reading_the_setting_queries_no_warehouse_and_returns_the_stored_result(db_session, monkeypatch):
    mgr = AuthorityAdmManager()
    _set_schema(db_session)
    calls = []
    monkeypatch.setattr(AuthorityAdmManager, "conformance", lambda self, s: calls.append(s) or {"status": "x"})
    AuthorityAdmManager._store_conformance(db_session, adm.conformance_report(_conformant_columns(), schema_fqn=SCHEMA))
    db_session.commit()
    state = mgr.state(db_session)
    assert calls == []
    assert state["conformance"]["status"] == "conformant"
    assert state["checked_at"]


def test_the_check_action_stores_an_unavailable_result_with_its_code(db_session, monkeypatch):
    mgr = AuthorityAdmManager()
    _set_schema(db_session)

    def down(self, s):
        raise AdmQueryError("The ADM statement failed.", code="adm_query_failed")

    monkeypatch.setattr(AuthorityAdmManager, "conformance", down)
    state = mgr.check(db_session, caller_is_admin=True)
    assert state["conformance"]["status"] == "unavailable"
    assert state["conformance"]["error_code"] == "adm_query_failed"
    assert mgr.state(db_session)["conformance"]["status"] == "unavailable"


def test_the_check_action_is_admin_only(db_session):
    with pytest.raises(AdmPermissionError):
        AuthorityAdmManager().check(db_session, caller_is_admin=False)


def test_the_check_route_is_admin_only():
    import src.routes.authority_resolution_routes as routes
    from src.common.authorization import PermissionChecker
    from src.common.features import FeatureAccessLevel
    route = next(r for r in routes.router.routes if r.path == "/api/authority/adm-schema/check" and "POST" in r.methods)
    levels = [d.call.required_level for d in route.dependant.dependencies if isinstance(d.call, PermissionChecker)]
    assert levels == [FeatureAccessLevel.ADMIN]


# ------------------------------------------- 5. SDK failures become coded errors

class _Boom(Exception):
    pass


def test_an_sdk_failure_on_execute_is_a_coded_error_with_no_server_text(monkeypatch):
    class Stmt:
        def execute_statement(self, **kw):
            raise _Boom("PERMISSION_DENIED: user x cannot read hr.payroll")

    with pytest.raises(AdmQueryError) as exc:
        run_query("SELECT 1", ws=SimpleNamespace(statement_execution=Stmt()), warehouse_id="wh")
    assert exc.value.code == "adm_query_failed"
    assert "hr.payroll" not in str(exc.value) and "PERMISSION" not in str(exc.value)
    assert exc.value.params.get("error_id")          # logged with an id, the id is what support sees


def test_an_sdk_failure_on_poll_is_a_coded_error(monkeypatch):
    class Stmt:
        def execute_statement(self, **kw):
            return SimpleNamespace(statement_id="s", status=SimpleNamespace(state="PENDING"))

        def get_statement(self, sid):
            raise ConnectionError("network down to 10.0.0.1")

    with pytest.raises(AdmQueryError) as exc:
        run_query("SELECT 1", ws=SimpleNamespace(statement_execution=Stmt()), warehouse_id="wh",
                  sleep=lambda s: None, clock=lambda: 0.0)
    assert exc.value.code == "adm_query_failed"
    assert "10.0.0.1" not in str(exc.value)


def test_a_failed_read_makes_the_facts_empty_so_the_resolve_fails_closed(db_session, monkeypatch):
    mgr = AuthorityResolutionManager()
    _set_schema(db_session)
    rel = _ar(mgr, db_session, "facts-down", actor_role="approver", criteria=[
        CriterionInput(name="Current", rule="ASSERT fact.entitlement_current = True"),
    ])

    def down(self, sql, **kw):
        raise AdmQueryError("The ADM statement failed.")

    monkeypatch.setattr(AuthorityResolutionManager, "_adm_query", down)
    assert mgr._facts_for(db_session, rel, {"actor_identity": "a@x"}) == {}
    result = mgr.resolve(db_session, rel.id, {"actor_identity": "a@x"}, record=False, require_active=False)
    assert result["verdict"] == "denied"


def test_a_workspace_client_failure_is_a_coded_error(monkeypatch):
    import src.common.workspace_client as wc
    import src.common.config as cfg
    monkeypatch.setattr(cfg, "get_settings", lambda: SimpleNamespace(DATABRICKS_WAREHOUSE_ID="wh"))

    def broken():
        raise RuntimeError("no credentials in /home/secret/.databrickscfg")

    monkeypatch.setattr(wc, "get_workspace_client", broken)
    with pytest.raises(AdmQueryError) as exc:
        adm_mod.workspace_and_warehouse()
    assert exc.value.code == "adm_query_failed"
    assert "secret" not in str(exc.value)


# ------------------------------------------- 6. weight-0 checks never gate

def test_a_failing_weight_zero_check_does_not_diverge_or_move_the_magnitude():
    informational = dna.Criterion(code="info", rule="ASSERT obj.value <= 1", direction=dna.DIR_ACTUAL_EXCEEDS,
                                  weight=0.0, dimension="people")
    gating = dna.Criterion(code="gate", rule="ASSERT obj.escalated = True", direction=dna.DIR_ACTUAL_EXCEEDS,
                           weight=1.0, dimension="policy")
    result = dna.compute_dnaco([informational], [{"value": 5}, {"value": 0.5}])
    assert result.magnitude == 0.0
    assert result.divergent_count == 0
    assert result.position == 0.0
    assert result.dimensions["people"].weight == 0.0
    result = dna.compute_dnaco([informational, gating], [{"value": 5, "escalated": False}])
    assert result.magnitude == 1.0          # the weight-1 check gates; the weight-0 one adds no reason
    assert result.rows[0].reasons == ["gate"]


# ------------------------------------------- 7. identity reads: batched, no truncation

def test_the_identity_query_has_no_row_cap_and_escapes_its_ids():
    sql = adm.identity_links_sql(SCHEMA, as_of=NOW, entities=["E'1", "E2"])
    assert "LIMIT" not in sql
    assert "entity_id IN ('E\\'1', 'E2')" in sql
    assert "verification_status = 'VERIFIED'" in sql


def test_chunked_covers_every_value_in_bounded_batches():
    values = [f"E{i}" for i in range(450)]
    batches = adm.chunked(values, 200)
    assert [len(b) for b in batches] == [200, 200, 50]
    assert [v for b in batches for v in b] == values


def test_the_identity_read_batches_the_samples_entities(db_session, monkeypatch):
    mgr = AuthorityResolutionManager()
    entities = [f"E{i}" for i in range(450)]
    calls = []

    def fake(self, sql, **kw):
        calls.append(sql)
        if "entity_id IN" in sql:
            return [{"source_id": "a@x", "entity_id": "E1"}] if "'E1'" in sql else []
        return [{"source_id": "a@x", "entity_id": "E1"}]

    monkeypatch.setattr(AuthorityResolutionManager, "_adm_query", fake)
    alias_by_entity, _ = mgr._identity_maps(SCHEMA, NOW, entities)
    entity_calls = [c for c in calls if "entity_id IN" in c]
    assert len(entity_calls) == 3                 # 200 + 200 + 50 entities
    assert alias_by_entity == {"E1": "a@x"}


def test_an_alias_mapped_to_an_entity_outside_the_sample_is_ambiguous(db_session, monkeypatch):
    mgr = AuthorityResolutionManager()

    def fake(self, sql, **kw):
        if "entity_id IN" in sql:
            return [{"source_id": "a@x", "entity_id": "E1"}]
        return [{"source_id": "a@x", "entity_id": "E1"}, {"source_id": "a@x", "entity_id": "E9"}]

    monkeypatch.setattr(AuthorityResolutionManager, "_adm_query", fake)
    alias_by_entity, entity_by_alias = mgr._identity_maps(SCHEMA, NOW, ["E1"])
    assert alias_by_entity == {}                  # the alias is ambiguous: fail closed
    assert "a@x" not in entity_by_alias


# ------------------------------------------- 8. result chunks: followed, capped, flagged

def test_run_query_follows_the_result_chunks():
    class Stmt:
        def execute_statement(self, **kw):
            return SimpleNamespace(statement_id="s9", status=SimpleNamespace(state="SUCCEEDED"),
                                   manifest=SimpleNamespace(schema=SimpleNamespace(columns=[
                                       SimpleNamespace(name="v", type_name=SimpleNamespace(value="STRING"))])),
                                   result=SimpleNamespace(data_array=[["a"]], next_chunk_index=1))

        def get_statement_result_chunk_n(self, sid, index):
            assert (sid, index) == ("s9", 1)
            return SimpleNamespace(data_array=[["b"]], next_chunk_index=None)

    rows = run_query("SELECT 1", ws=SimpleNamespace(statement_execution=Stmt()), warehouse_id="wh")
    assert [r["v"] for r in rows] == ["a", "b"]
    assert rows.truncated is False


def test_run_query_stops_at_the_cap_and_says_so():
    class Stmt:
        def execute_statement(self, **kw):
            return SimpleNamespace(statement_id="s8", status=SimpleNamespace(state="SUCCEEDED"),
                                   manifest=SimpleNamespace(schema=SimpleNamespace(columns=[
                                       SimpleNamespace(name="v", type_name=SimpleNamespace(value="STRING"))])),
                                   result=SimpleNamespace(data_array=[["a"]], next_chunk_index=1))

        def get_statement_result_chunk_n(self, sid, index):
            return SimpleNamespace(data_array=[["b"], ["c"]], next_chunk_index=2)

    rows = run_query("SELECT 1", ws=SimpleNamespace(statement_execution=Stmt()), warehouse_id="wh", max_rows=2)
    assert len(rows) == 2
    assert rows.truncated is True


def test_an_identity_read_that_hits_the_cap_fails_closed(monkeypatch):
    from src.controller import authority_resolution_manager as arm
    monkeypatch.setattr(arm, "workspace_and_warehouse", lambda: (object(), "wh"))
    truncated = AdmRows()
    truncated.truncated = True
    monkeypatch.setattr(arm, "run_query", lambda *a, **k: truncated)
    with pytest.raises(AdmQueryError) as exc:
        AuthorityResolutionManager()._adm_query("SELECT 1")
    assert exc.value.code == ADM_RESULT_TRUNCATED
    assert AuthorityResolutionManager()._adm_query("SELECT 1", allow_truncated=True) is truncated


def test_a_truncated_sample_is_recorded_in_the_basis_not_passed_off_as_complete(db_session, monkeypatch):
    mgr = AuthorityResolutionManager()
    _set_schema(db_session)
    rel = _ar(mgr, db_session, "truncated-sample")
    observed = AdmRows()
    observed.truncated = True

    def fake(self, sql, *, allow_truncated=False):
        return observed if "observed_decision_provenance" in sql else AdmRows()

    monkeypatch.setattr(AuthorityResolutionManager, "_adm_query", fake)
    sample = mgr._collect_evidence(db_session, rel, SimpleNamespace(started_at=NOW))
    assert sample.basis["truncated"] is True
