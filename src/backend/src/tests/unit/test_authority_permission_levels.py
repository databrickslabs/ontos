"""ARF 1.2.0 batch 1: permission levels, MCP scope mapping, atomic usage counters,
filtered reads, coded errors and the default grants (#859 review findings
B2, B3 (gate only), S11, S13, S14, R7, the MCP scope gap, 1491-6, 1495-4).
"""
import asyncio
import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock
import uuid

import pytest

from src.common.features import FeatureAccessLevel
from src.controller.authority_resolution_manager import (
    AuthorityInvalidError,
    AuthorityPermissionError,
    AuthorityResolutionManager,
    AuthorityStatusError,
    STATUS_ACTIVE,
    VERDICT_APPROVED,
)
from src.db_models.authority_resolution import AuthorityDecisionDb, AuthorityRelationDb
from src.db_models.compliance import CompliancePolicyDb
from src.models.authority_resolution import AuthorityRelationCreate
from src.repositories.authority_resolution_repository import authority_dna_run_repo

RO = FeatureAccessLevel.READ_ONLY
RW = FeatureAccessLevel.READ_WRITE
ADMIN = FeatureAccessLevel.ADMIN
FEATURE = "authority-resolution"


# An always-passing enabled check: a version needs one to resolve (B5). The DSL
# treats a missing operand in != as unequal, so this passes for any request.
PASS_CHECK = {"name": "Not blocked", "rule": "ASSERT TRUE"}


def _make_ar(mgr, db, *, slug=None, name="AR", caller_is_admin=True, **kwargs):
    kwargs.setdefault("criteria", [PASS_CHECK])
    return mgr.create_relation(db, AuthorityRelationCreate(name=name, slug=slug, **kwargs),
                               caller_is_admin=caller_is_admin)


def _active_ar(mgr, db, slug):
    rel = _make_ar(mgr, db, slug=slug)
    rel.status = STATUS_ACTIVE
    db.commit()
    return rel


# ----------------------------------------------------------- admin-only actions

def test_non_admin_cannot_activate_or_retire(db_session):
    mgr = AuthorityResolutionManager()
    rel = _make_ar(mgr, db_session, slug="levels-activate")
    db_session.commit()
    with pytest.raises(AuthorityPermissionError) as exc:
        mgr.set_status(db_session, rel.id, STATUS_ACTIVE, caller_is_admin=False)
    assert exc.value.params == {"from": "draft", "to": "active", "required_level": "Admin"}
    with pytest.raises(AuthorityPermissionError):
        mgr.set_status(db_session, rel.id, "retired", caller_is_admin=False)
    db_session.refresh(rel)
    assert rel.status == "draft"


def test_non_admin_can_move_between_draft_and_needs_review(db_session):
    mgr = AuthorityResolutionManager()
    rel = _make_ar(mgr, db_session, slug="levels-review")
    db_session.commit()
    updated = mgr.set_status(db_session, rel.id, "needs_review", caller_is_admin=False)
    assert updated.status == "needs_review"


def test_non_admin_cannot_create_with_app_sp_identity(db_session):
    mgr = AuthorityResolutionManager()
    with pytest.raises(AuthorityPermissionError) as exc:
        _make_ar(mgr, db_session, slug="levels-sp-create", resolver_auth="app_sp", caller_is_admin=False)
    assert exc.value.params["field"] == "resolver_auth"
    db_session.rollback()
    assert mgr.resolve_relation_ref(db_session, "levels-sp-create") is None


def test_non_admin_cannot_switch_to_app_sp_but_keeps_an_admin_setting(db_session):
    mgr = AuthorityResolutionManager()
    rel = _make_ar(mgr, db_session, slug="levels-sp-update", resolver_auth="obo")
    db_session.commit()
    with pytest.raises(AuthorityPermissionError):
        mgr.update_relation(db_session, rel.id, _update(resolver_auth="app_sp"), caller_is_admin=False)
    db_session.refresh(rel)
    assert rel.resolver_auth == "obo"

    admin_rel = _make_ar(mgr, db_session, slug="levels-sp-admin", resolver_auth="app_sp")
    db_session.commit()
    # Re-sending the value an Admin already set is not a change: a Read-write
    # author can still edit the other fields of that AR.
    updated = mgr.update_relation(db_session, admin_rel.id,
                                  _update(resolver_auth="app_sp", description="edited"),
                                  caller_is_admin=False)
    assert updated.description == "edited" and updated.resolver_auth == "app_sp"


def test_non_admin_cannot_set_the_dna_ceiling(db_session):
    mgr = AuthorityResolutionManager()
    with pytest.raises(AuthorityPermissionError) as exc:
        _make_ar(mgr, db_session, slug="levels-ceiling", dna_max_threshold=0.9, caller_is_admin=False)
    assert exc.value.params["field"] == "dna_max_threshold"
    db_session.rollback()

    rel = _make_ar(mgr, db_session, slug="levels-ceiling-default", caller_is_admin=False)
    db_session.commit()
    assert rel.dna_max_threshold == 0.3
    with pytest.raises(AuthorityPermissionError):
        mgr.update_relation(db_session, rel.id, _update(dna_max_threshold=0.5), caller_is_admin=False)
    admin_set = mgr.update_relation(db_session, rel.id, _update(dna_max_threshold=0.5), caller_is_admin=True)
    assert admin_set.dna_max_threshold == 0.5


def test_non_admin_cannot_set_a_recompute_schedule(db_session):
    mgr = AuthorityResolutionManager()
    rel = _make_ar(mgr, db_session, slug="levels-cron")
    db_session.commit()
    with pytest.raises(AuthorityPermissionError) as exc:
        mgr.update_relation(db_session, rel.id, _update(schedule_cron="0 6 * * *"), caller_is_admin=False)
    assert exc.value.params["field"] == "schedule_cron"


def _update(**fields):
    from src.models.authority_resolution import AuthorityRelationUpdate
    return AuthorityRelationUpdate(**fields)


# --------------------------------------------------------- app_sp test/resolve

def _sp_ar_with_pinned_market(mgr, db, slug):
    from src.models.authority_resolution import ResourceRefInput
    rel = mgr.create_relation(db, AuthorityRelationCreate(
        name=f"SP {slug}", slug=slug, resolver_auth="app_sp", criteria=[PASS_CHECK],
        resource_refs=[ResourceRefInput(
            field_path="actor_identity", ref_type="mcp_tool",
            mcp_service_name="mcp-services/hr.org.ontos_identity", mcp_tool_name="get_role_holder",
            mcp_params={"market": "{{ ctx.market }}"}, mcp_result_pointer="$.approver",
        )],
    ), caller_is_admin=True)
    rel.domain_context = {"params": {"market": "DE"}}
    rel.status = STATUS_ACTIVE
    db.commit()
    return rel


class _Client:
    calls = []

    def __init__(self, ws, service_name, deadline=None):
        pass

    def call_tool(self, name, arguments):
        _Client.calls.append(arguments)
        return {"approver": "someone@example.com"}


def test_read_only_test_is_refused(db_session):
    mgr = AuthorityResolutionManager()
    rel = _make_ar(mgr, db_session, slug="levels-test-ro")
    db_session.commit()
    with pytest.raises(AuthorityPermissionError):
        mgr.test_relation(db_session, rel.id, {}, caller_can_write=False, caller_is_admin=True)


def test_non_admin_cannot_test_an_app_sp_ar(db_session):
    mgr = AuthorityResolutionManager()
    rel = _sp_ar_with_pinned_market(mgr, db_session, "levels-test-sp")
    with pytest.raises(AuthorityPermissionError):
        mgr.test_relation(db_session, rel.id, {}, caller_can_write=True, caller_is_admin=False,
                          mcp_client_factory=_Client, app_ws_factory=lambda: object())
    out = mgr.test_relation(db_session, rel.id, {}, caller_can_write=True, caller_is_admin=True,
                            mcp_client_factory=_Client, app_ws_factory=lambda: object())
    assert out["verdict"] == VERDICT_APPROVED


def test_app_sp_params_never_take_caller_request_fields(db_session):
    """B2: a request field named like a param is not templated into an app_sp call."""
    mgr = AuthorityResolutionManager()
    rel = _sp_ar_with_pinned_market(mgr, db_session, "levels-sp-template")
    _Client.calls = []
    out = mgr.resolve(db_session, rel.id, {"market": "US", "request": "x", "actor_identity": "a"},
                      record=False, app_ws_factory=lambda: object(), mcp_client_factory=_Client)
    assert out["verdict"] == VERDICT_APPROVED
    assert _Client.calls == [{"market": "DE"}]


# ------------------------------------------------------- resolve and decisions

def test_read_only_resolve_writes_no_decision_row(db_session):
    mgr = AuthorityResolutionManager()
    rel = _active_ar(mgr, db_session, "levels-resolve-ro")
    out = mgr.resolve(db_session, "levels-resolve-ro", {"actor_identity": "a"}, record=False)
    db_session.commit()
    assert out["verdict"] == VERDICT_APPROVED
    assert db_session.query(AuthorityDecisionDb).filter_by(relation_id=rel.id).count() == 0
    db_session.refresh(rel)
    assert rel.usage_count == 0


def test_recorded_resolve_writes_a_decision_row(db_session):
    mgr = AuthorityResolutionManager()
    rel = _active_ar(mgr, db_session, "levels-resolve-rw")
    mgr.resolve(db_session, "levels-resolve-rw", {"actor_identity": "a"}, record=True)
    db_session.commit()
    assert db_session.query(AuthorityDecisionDb).filter_by(relation_id=rel.id).count() == 1
    db_session.refresh(rel)
    assert rel.usage_count == 1 and rel.approved_count == 1


def test_usage_counter_is_incremented_in_the_database(db_session):
    """S14: the increment is ``col = col + 1`` in SQL. A read-modify-write would
    write 1 here, because this session still holds usage_count == 0 while the
    database has moved on to 10."""
    mgr = AuthorityResolutionManager()
    rel = _active_ar(mgr, db_session, "levels-atomic")
    assert rel.usage_count == 0  # the ORM object is loaded and stale from here on
    db_session.query(AuthorityRelationDb).filter(AuthorityRelationDb.id == rel.id).update(
        {AuthorityRelationDb.usage_count: 10}, synchronize_session=False)
    mgr.resolve(db_session, "levels-atomic", {"actor_identity": "a"}, record=True)
    db_session.flush()
    stored = db_session.query(AuthorityRelationDb.usage_count).filter(
        AuthorityRelationDb.id == rel.id).scalar()
    assert stored == 11


# ---------------------------------------------------------------- MCP scopes

def test_authority_scope_maps_to_the_feature():
    from src.tools.caller import SCOPE_FEATURES, scope_read_levels
    assert SCOPE_FEATURES["authority"] == FEATURE
    assert scope_read_levels(["authority:read"]) == {FEATURE: RO}
    assert scope_read_levels(["authority:write"]) == {FEATURE: RW}
    assert scope_read_levels(["authority:*"]) == {FEATURE: RW}
    assert scope_read_levels(["authority:read", "authority:write"]) == {FEATURE: RW}
    assert scope_read_levels(["authority:write", "authority:read"]) == {FEATURE: RW}
    assert scope_read_levels(["search:read"]) == {}


def _ctx(db, caller):
    from src.tools.base import ToolContext
    return ToolContext(db=db, settings=MagicMock(), caller=caller)


def _caller(level):
    from src.tools.base import ToolCaller
    return ToolCaller(email=None, auth_path="test", permissions={FEATURE: level} if level else {})


@pytest.fixture
def inline_threadpool(monkeypatch):
    """The tools run the manager in a worker thread; the test session is not thread-safe."""
    import src.tools.authority_resolution as artools

    async def run_here(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(artools, "run_in_threadpool", run_here)
    return artools


def test_resolve_authority_records_only_for_a_write_capable_caller(db_session, inline_threadpool):
    from src.tools.authority_resolution import ResolveAuthorityTool
    mgr = AuthorityResolutionManager()
    rel = _active_ar(mgr, db_session, "levels-mcp-resolve")
    tool = ResolveAuthorityTool()

    read_only = asyncio.run(tool.execute(_ctx(db_session, _caller(RO)), ar_id=rel.id, actor_identity="a"))
    assert read_only.success and read_only.data["verdict"] == VERDICT_APPROVED
    db_session.commit()
    assert db_session.query(AuthorityDecisionDb).filter_by(relation_id=rel.id).count() == 0

    no_caller = asyncio.run(tool.execute(_ctx(db_session, None), ar_id=rel.id, actor_identity="a"))
    assert no_caller.success
    db_session.commit()
    assert db_session.query(AuthorityDecisionDb).filter_by(relation_id=rel.id).count() == 0

    writer = asyncio.run(tool.execute(_ctx(db_session, _caller(RW)), ar_id=rel.id, actor_identity="a"))
    assert writer.success
    db_session.commit()
    assert db_session.query(AuthorityDecisionDb).filter_by(relation_id=rel.id).count() == 1


def test_compute_tool_needs_read_write_on_the_feature(db_session):
    from src.tools.authority_resolution import ComputeDnaCoefficientTool, ResolveAuthorityTool
    from src.tools.base import check_tool_permission

    compute = ComputeDnaCoefficientTool()
    assert compute.required_scope == "authority:write"
    assert compute.required_permission == (FEATURE, RW)
    assert check_tool_permission(compute, _ctx(db_session, _caller(RO))) is not None
    assert check_tool_permission(compute, _ctx(db_session, _caller(RW))) is None
    assert check_tool_permission(compute, _ctx(db_session, None)) is not None

    resolve = ResolveAuthorityTool()
    assert resolve.required_permission == (FEATURE, RO)
    assert check_tool_permission(resolve, _ctx(db_session, _caller(RO))) is None


# ----------------------------------------------------------- filtered checks

def _check(db, name, category):
    row = CompliancePolicyDb(
        id=str(uuid.uuid4()), name=name, rule="ASSERT obj.value <= 1",
        category=category, is_active=True,
    )
    db.add(row)
    db.flush()
    return row


def test_reusable_checks_are_limited_to_the_arf_category(db_session):
    mgr = AuthorityResolutionManager()
    arf = _check(db_session, "ARF check zz", "Authority Decision")
    other = _check(db_session, "Compliance check zz", "Maturity")
    db_session.commit()

    names = lambda rows: {r.id for r in rows}  # noqa: E731
    limited = names(mgr.list_reusable_checks(db_session, caller_can_read_compliance=False))
    assert arf.id in limited and other.id not in limited

    full = names(mgr.list_reusable_checks(db_session, caller_can_read_compliance=True))
    assert {arf.id, other.id} <= full

    # A category filter narrows, and cannot widen past the ARF category.
    assert other.id not in names(mgr.list_reusable_checks(
        db_session, category="Maturity", caller_can_read_compliance=False))
    assert arf.id in names(mgr.list_reusable_checks(
        db_session, category="Authority Decision", caller_can_read_compliance=False))


# ------------------------------------------------------------- coded errors

def test_route_failure_hides_exception_text_and_carries_an_error_id():
    from src.routes.authority_resolution_routes import _failure
    err = _failure("test", RuntimeError("SELECT secret FROM hr.payroll.salaries: 403 Forbidden"))
    assert err.status_code == 500
    assert err.detail["code"] == "authority_failed"
    error_id = err.detail["params"]["errorId"]
    assert error_id in err.detail["message"]
    shown = json.dumps(err.detail)
    assert "hr.payroll" not in shown and "Forbidden" not in shown and "SELECT" not in shown


def test_coded_validation_error_keeps_its_code_for_the_client():
    from src.routes.authority_resolution_routes import _failure
    exc = AuthorityInvalidError("Evidence table 'x' must be a plain catalog.schema.table name.")
    err = _failure("test", exc, coded_status=400)
    assert err.status_code == 400
    assert err.detail == str(exc)
    assert err.__cause__ is exc
    assert exc.code == "authority_invalid"


def test_refusal_is_a_coded_403():
    from src.routes.authority_resolution_routes import _failure
    err = _failure("test", AuthorityPermissionError("Only an Admin can set an AR to 'active'.",
                                                   required_level="Admin"))
    assert err.status_code == 403
    assert err.__cause__.code == "authority_permission_denied"


def test_permission_check_failure_is_diagnosable_without_the_text():
    from src.common.api_errors import PERMISSION_CHECK_FAILED_CODE, permission_check_failure
    err = permission_check_failure(FEATURE, KeyError("'Read-Write-typo'"))
    assert err.status_code == 500
    assert err.detail["code"] == PERMISSION_CHECK_FAILED_CODE
    assert err.detail["params"]["feature"] == FEATURE
    assert "Read-Write-typo" not in json.dumps(err.detail)
    assert err.detail["params"]["errorId"] in err.detail["message"]


def test_failed_dna_run_stores_a_generic_message(db_session, monkeypatch):
    mgr = AuthorityResolutionManager()
    rel = _make_ar(mgr, db_session, slug="levels-dna-error")
    db_session.commit()

    def warehouse_error(_relation):
        raise RuntimeError("Table hr.payroll.salaries not found for principal a@example.com")

    monkeypatch.setattr(mgr, "_collect_evidence", warehouse_error)
    with pytest.raises(RuntimeError):
        mgr.compute_dnaco(db_session, rel.id)
    run = authority_dna_run_repo.list_for_relation(db_session, relation_id=rel.id)[0]
    assert run.status == "failed"
    assert "hr.payroll" not in run.error_message and "example.com" not in run.error_message
    assert "error id" in run.error_message


def test_validation_message_from_the_manager_is_kept(db_session, monkeypatch):
    mgr = AuthorityResolutionManager()
    rel = _make_ar(mgr, db_session, slug="levels-dna-empty")
    db_session.commit()
    with pytest.raises(AuthorityInvalidError, match="No evidence rows"):
        mgr.compute_dnaco(db_session, rel.id, rows=[])
    run = authority_dna_run_repo.list_for_relation(db_session, relation_id=rel.id)[0]
    assert "No evidence rows" in run.error_message


# ------------------------------------------------------------- default grants

def _load_migration():
    path = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "ak4_authority_resolution_grants.py"
    spec = importlib.util.spec_from_file_location("ak4_authority_resolution_grants", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_grant_migration_chains_on_the_current_head():
    migration = _load_migration()
    assert migration.revision == "ak4_authority_resolution_grants"
    assert migration.down_revision == "ak3_merge_ak2_s2"


@pytest.mark.parametrize("role, expected", [
    ("Admin", "Admin"),
    ("Data Governance Officer", "Admin"),
    ("Data Steward", "Read/Write"),
    ("Security Officer", "Read-only"),
    ("Data Producer", "Read-only"),
    ("Data Consumer", "Read-only"),
])
def test_grant_migration_levels_per_role(role, expected):
    migration = _load_migration()
    assert migration.grants_to_add(role, {}) == {FEATURE: expected}
    assert migration.grants_to_add(role, None) == {FEATURE: expected}


def test_grant_migration_fills_only_where_the_role_has_no_level():
    migration = _load_migration()
    # The key is present with 'None': the seeder writes every feature, so this is "no grant".
    assert migration.grants_to_add("Data Steward", {FEATURE: "None"}) == {FEATURE: "Read/Write"}
    # A level already granted (even a lower or higher one) is never overwritten.
    assert migration.grants_to_add("Data Consumer", {FEATURE: "Read/Write"}) == {}
    assert migration.grants_to_add("Data Governance Officer", {FEATURE: "Read-only"}) == {}
    # Roles outside the default set get nothing.
    assert migration.grants_to_add("Custom Role", {}) == {}


def test_new_install_defaults_match_the_migration():
    from src.controller.settings_manager import DEFAULT_ROLE_PERMISSIONS
    migration = _load_migration()
    for role, level in migration._GRANTS.items():
        if role == "Admin":
            continue  # Admin is granted every feature by default
        assert DEFAULT_ROLE_PERMISSIONS[role][FEATURE] == FeatureAccessLevel(level), role


def test_settings_yaml_default_roles_match_the_migration():
    import yaml
    migration = _load_migration()
    path = Path(__file__).resolve().parents[2] / "data" / "settings.yaml"
    roles = {r["name"]: r for r in yaml.safe_load(path.read_text())["roles"]}
    for role, level in migration._GRANTS.items():
        if role == "Admin":
            continue
        assert roles[role]["feature_permissions"][FEATURE] == level, role


# ---------------------------------------------- batch-1 review follow-up


def _prereq_pair(mgr, db, *, upstream_sp=True):
    """A Read/Write-authored head (obo) whose prerequisite is an app_sp AR."""
    from src.models.authority_resolution import PrerequisiteInput
    _make_ar(mgr, db, slug="fu-upstream", resolver_auth="app_sp" if upstream_sp else "obo")
    head = mgr.create_relation(db, AuthorityRelationCreate(
        name="FU head", slug="fu-head",
        prerequisites=[PrerequisiteInput(prerequisite_family_slug="fu-upstream")],
    ))
    db.commit()
    return head


def test_dry_run_is_refused_when_a_prerequisite_is_app_sp(db_session):
    """#2: the dry run walks the chain and calls an upstream app_sp ref as the SP."""
    mgr = AuthorityResolutionManager()
    head = _prereq_pair(mgr, db_session)
    with pytest.raises(AuthorityPermissionError) as exc:
        mgr.test_relation(db_session, head.id, {}, caller_can_write=True, caller_is_admin=False)
    assert exc.value.params["ar"] == "fu-upstream"
    out = mgr.test_relation(db_session, head.id, {}, caller_can_write=True, caller_is_admin=True)
    assert "verdict" in out


def test_dry_run_allowed_for_non_admin_when_the_chain_has_no_app_sp(db_session):
    mgr = AuthorityResolutionManager()
    head = _prereq_pair(mgr, db_session, upstream_sp=False)
    out = mgr.test_relation(db_session, head.id, {}, caller_can_write=True, caller_is_admin=False)
    assert "verdict" in out


def test_set_status_needs_admin_to_take_an_ar_into_or_out_of_service(db_session):
    """#3: the rule applies on either side of the change, both directions."""
    mgr = AuthorityResolutionManager()
    rel = _make_ar(mgr, db_session, slug="fu-status")
    db_session.commit()

    # Read-write moves between draft and needs_review (neither side in service).
    assert mgr.set_status(db_session, rel.id, "needs_review", caller_is_admin=False).status == "needs_review"
    assert mgr.set_status(db_session, rel.id, "draft", caller_is_admin=False).status == "draft"

    # Into service: refused.
    with pytest.raises(AuthorityPermissionError):
        mgr.set_status(db_session, rel.id, STATUS_ACTIVE, caller_is_admin=False)

    # Out of service: an active AR can't be taken down by a non-Admin.
    rel.status = STATUS_ACTIVE
    db_session.commit()
    with pytest.raises(AuthorityPermissionError) as exc:
        mgr.set_status(db_session, rel.id, "needs_review", caller_is_admin=False)
    assert exc.value.params["from"] == STATUS_ACTIVE
    assert db_session.query(AuthorityRelationDb).get(rel.id).status == STATUS_ACTIVE

    # A retired AR goes back only to active (S3), and only with an Admin and fresh affirmations.
    rel.status = "retired"
    db_session.commit()
    with pytest.raises(AuthorityPermissionError):
        mgr.set_status(db_session, rel.id, "draft", caller_is_admin=False)
    with pytest.raises(AuthorityStatusError) as exc:
        mgr.set_status(db_session, rel.id, "draft", caller_is_admin=True)
    assert exc.value.params["reason"] == "transition_not_allowed"


def test_resolve_route_records_by_default_for_write_callers_only(monkeypatch):
    """#6: default record follows the caller's write capability, as MCP does."""
    from fastapi import HTTPException
    import src.routes.authority_resolution_routes as routes
    from src.models.authority_resolution import ResolveRequest

    seen = {}

    def spy(db, ar_ref, req, record=True, **kwargs):
        seen["record"] = record
        return {"verdict": "approved"}

    monkeypatch.setattr(routes.manager, "resolve", spy)
    request = MagicMock()
    cases = [(True, None, True), (False, None, False), (True, False, False), (True, True, True)]
    for can_write, arg, expected in cases:
        monkeypatch.setattr(routes, "_may", lambda *a, **k: can_write)
        routes.resolve("ar", db=None, request=request, user=None, auth_manager=None,
                       payload=ResolveRequest(), record=arg)
        assert seen["record"] is expected, (can_write, arg)

    monkeypatch.setattr(routes, "_may", lambda *a, **k: False)
    with pytest.raises(HTTPException) as exc:
        routes.resolve("ar", db=None, request=request, user=None, auth_manager=None,
                       payload=ResolveRequest(), record=True)
    assert exc.value.status_code == 403


def test_token_scope_caps_recording(db_session):
    """#7: a read-scoped token never records, even for a Read-write user."""
    from src.tools.authority_resolution import _may_record
    from src.tools.base import ToolCaller, ToolContext

    def ctx(scopes):
        caller = ToolCaller(email="rw@x", auth_path="t", permissions={FEATURE: RW}, token_scopes=scopes)
        return ToolContext(db=db_session, settings=MagicMock(), caller=caller)

    assert _may_record(ctx(("authority:read",))) is False
    assert _may_record(ctx(("search:read",))) is False
    assert _may_record(ctx(("authority:write",))) is True
    assert _may_record(ctx(("authority:*",))) is True
    assert _may_record(ctx(("*",))) is True
    assert _may_record(ctx(None)) is True  # Ask Ontos: no token restriction

    read_only_user = ToolCaller(email="ro@x", auth_path="t", permissions={FEATURE: RO}, token_scopes=None)
    assert _may_record(ToolContext(db=db_session, settings=MagicMock(), caller=read_only_user)) is False


def test_read_scoped_forwarded_user_token_never_records_through_the_handler(monkeypatch, db_session):
    """#7 end to end: the MCP handler's forwarded-user path carries the token's scopes."""
    from types import SimpleNamespace
    import src.routes.mcp_routes as mcp_routes
    import src.tools.authority_resolution as artools
    from src.tools.base import ToolCaller

    seen = []
    monkeypatch.setattr(artools._manager, "resolve",
                        lambda *a, **k: seen.append(k.get("record")) or {"verdict": "approved"})

    async def fake_verify(request, settings):
        return SimpleNamespace(email="rw@x", username="rw@x", groups=[])

    async def fake_caller(user, request, auth_path, db=None):
        return ToolCaller(email=user.email, auth_path=auth_path, permissions={FEATURE: RW})

    monkeypatch.setattr(mcp_routes, "verify_forwarded_user", fake_verify)
    monkeypatch.setattr(mcp_routes, "resolve_tool_caller", fake_caller)

    def handler(scopes):
        request = SimpleNamespace(
            headers={"x-forwarded-access-token": "user-token"},
            app=SimpleNamespace(state=SimpleNamespace()),
            client=SimpleNamespace(host="127.0.0.1"),
        )
        token = SimpleNamespace(name="tok", created_by="rw@x", scopes=scopes, id=None)
        return mcp_routes.MCPHandler(db=db_session, settings=MagicMock(), token_info=token,
                                     request=request, audit_manager=None, session_id="s")

    call = {"name": "resolve_authority", "arguments": {"ar_id": "any"}}
    asyncio.run(handler(["authority:read"])._handle_tools_call(call))
    asyncio.run(handler(["authority:read", "authority:write"])._handle_tools_call(call))
    assert seen == [False, True]


def test_participant_refusals_are_coded_403s_that_keep_their_message(db_session):
    """#8: the specific refusal reaches the client with its own code."""
    from src.controller.authority_resolution_manager import (
        AuthorityNotAReviewerError, AuthorityNotNamedError, AuthorityReviewerNotApproverError,
    )
    from src.routes.authority_resolution_routes import _failure
    from src.models.authority_resolution import AffirmationInput

    mgr = AuthorityResolutionManager()
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(
        name="FU affirm", affirmations=[AffirmationInput(role="Approver", principal="alice@x.com")]))
    db_session.commit()
    aff = mgr.to_read_dict(db_session, rel)["affirmations"][0]
    with pytest.raises(AuthorityNotNamedError) as exc:
        mgr.affirm(db_session, aff["id"], affirmed_by="mallory@x.com", user=_user("mallory@x.com"))
    assert isinstance(exc.value, PermissionError)

    for error, code in [
        (AuthorityNotNamedError("Only the named participant can record this affirmation."),
         "authority_not_named_participant"),
        (AuthorityReviewerNotApproverError("This participant is a reviewer, not an approver."),
         "authority_reviewer_not_approver"),
        (AuthorityNotAReviewerError("This participant is not a reviewer."), "authority_not_a_reviewer"),
    ]:
        err = _failure("affirm", error)
        assert err.status_code == 403
        assert err.detail == str(error)
        assert err.__cause__.code == code


def test_failed_run_and_its_response_share_one_error_id(db_session, monkeypatch):
    """#9: one id for the run row and the response, and the failure is logged once."""
    from src.routes.authority_resolution_routes import _failure
    from src.common.api_errors import log_failure

    mgr = AuthorityResolutionManager()
    rel = _make_ar(mgr, db_session, slug="fu-dna-id")
    db_session.commit()

    def warehouse_error(_relation):
        raise RuntimeError("secret table hr.payroll")

    monkeypatch.setattr(mgr, "_collect_evidence", warehouse_error)
    with pytest.raises(RuntimeError) as exc:
        mgr.compute_dnaco(db_session, rel.id)
    run = authority_dna_run_repo.list_for_relation(db_session, relation_id=rel.id)[0]
    response = _failure("compute_dnaco", exc.value, coded_status=502, unexpected_status=502)

    error_id = response.detail["params"]["errorId"]
    assert error_id in run.error_message
    assert error_id == exc.value.error_id
    assert log_failure("again", exc.value) == error_id  # reused, not re-minted


def test_client_failure_payload_and_error_id_reuse():
    from src.common.api_errors import client_failure
    exc = RuntimeError("SELECT 1 FROM hr.payroll")
    first = client_failure("tag", exc, code="c", message="Failed ({errorId}).")
    assert first["code"] == "c"
    assert first["message"] == f"Failed ({first['params']['errorId']})."
    assert "hr.payroll" not in first["message"]
    assert client_failure("other", exc, code="c", message="x")["params"]["errorId"] == first["params"]["errorId"]


# -------------------------------------------- grant migration, run for real

def _role_db():
    from sqlalchemy import create_engine, text
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE app_roles (name TEXT PRIMARY KEY, feature_permissions TEXT)"))
        rows = [
            ("Admin", None),
            ("Data Governance Officer", "{}"),
            ("Data Steward", '{"authority-resolution": "None", "data-domains": "Read/Write"}'),
            ("Data Consumer", '{"authority-resolution": "Read/Write"}'),
            ("Data Producer", None),
            ("Custom Role", "{}"),
        ]
        for name, perms in rows:
            conn.execute(text("INSERT INTO app_roles VALUES (:n, :p)"), {"n": name, "p": perms})
    return engine


def _run_migration(engine, step_name):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    migration = _load_migration()
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            getattr(migration, step_name)()


def _role_perms(engine):
    import json
    from sqlalchemy import text
    with engine.connect() as conn:
        return {name: json.loads(raw) if raw else None for name, raw in conn.execute(
            text("SELECT name, feature_permissions FROM app_roles")).fetchall()}


def test_grant_migration_upgrade_changes_only_what_it_should():
    engine = _role_db()
    _run_migration(engine, "upgrade")
    perms = _role_perms(engine)
    assert perms["Admin"] == {FEATURE: "Admin"}
    assert perms["Data Governance Officer"] == {FEATURE: "Admin"}
    # 'None' counts as no grant: filled. Other features on the role are kept.
    assert perms["Data Steward"] == {"authority-resolution": "Read/Write", "data-domains": "Read/Write"}
    # A real grant is never lowered.
    assert perms["Data Consumer"] == {FEATURE: "Read/Write"}
    assert perms["Data Producer"] == {FEATURE: "Read-only"}
    assert perms["Custom Role"] == {}  # not in the default set: untouched


def test_grant_migration_upgrade_is_idempotent():
    engine = _role_db()
    _run_migration(engine, "upgrade")
    once = _role_perms(engine)
    _run_migration(engine, "upgrade")
    assert _role_perms(engine) == once


def test_grant_migration_downgrade_removes_only_its_own_levels():
    engine = _role_db()
    _run_migration(engine, "upgrade")
    _run_migration(engine, "downgrade")
    perms = _role_perms(engine)
    assert FEATURE not in perms["Data Governance Officer"]
    assert perms["Data Steward"] == {"data-domains": "Read/Write"}
    # The Consumer's Read/Write was not set by this migration: kept.
    assert perms["Data Consumer"] == {FEATURE: "Read/Write"}


def _user(email, groups=None):
    from types import SimpleNamespace
    return SimpleNamespace(email=email, username=email, user=email, groups=groups or [])
