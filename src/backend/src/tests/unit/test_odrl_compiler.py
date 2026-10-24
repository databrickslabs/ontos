"""Golden tests: ODRL policies → Entitlement IR → Unity Catalog grants."""
from datetime import datetime, timezone

from src.common import odrl
from src.common import uc_policy_adapter as uc
from src.common.odrl_compiler import PolicyInput, compile_policies, typed_principal

NOW = datetime(2026, 10, 17, tzinfo=timezone.utc)
AUD = "urn:ontos:audience:analysts"
COL = "urn:ontos:asset-collection:restricted"


def _policy(rules, uid="urn:ontos:policy:p1", conflict="prohibit", name="P1"):
    return PolicyInput(doc={"uid": uid, "type": "Set", "conflict": conflict, **rules}, id=uid, name=name, version="1.0.0")


def _compile(*policies, audiences=None, collections=None, directory=None):
    return compile_policies(list(policies), audiences or {}, collections or {}, directory, now=NOW)


def _keys(grants):
    return {(g.principal, g.securable_type, g.securable_name, g.privilege) for g in grants}


def test_read_on_table_adds_implied_use_privileges():
    plan = _compile(_policy({"permission": [{"target": "uc:Main.Sales.Orders", "action": "read", "assignee": "group:analysts"}]}))
    grants = uc.build_grants(plan)
    assert _keys(grants) == {
        ("analysts", "table", "main.sales.orders", "SELECT"),
        ("analysts", "catalog", "main", "USE_CATALOG"),
        ("analysts", "schema", "main.sales", "USE_SCHEMA"),
    }
    implied = {g.privilege: g.implied for g in grants}
    assert implied == {"SELECT": False, "USE_CATALOG": True, "USE_SCHEMA": True}


def test_audience_members_and_business_role_refinement_resolve_via_directory():
    audiences = {AUD: odrl.CollectionDef(AUD, "Analysts", refinement=[
        {"leftOperand": "ontos:businessRole", "operator": "eq", "rightOperand": "Analyst"}])}
    directory = lambda: [("ana@example.com", {"ontos:businessRole": ["Analyst"]}),  # noqa: E731
                         ("bob@example.com", {"ontos:businessRole": ["Steward"]})]
    plan = _compile(_policy({"permission": [{"target": "uc:main.sales", "action": "read", "assignee": AUD}]}),
                    audiences=audiences, directory=directory)
    assert {e.principal for e in plan.entitlements} == {"user:ana@example.com"}


def test_group_refinement_compiles_to_groups_without_directory():
    audiences = {AUD: odrl.CollectionDef(AUD, "Analysts", refinement=[
        {"leftOperand": "ontos:group", "operator": "isAnyOf", "rightOperand": ["g1", "g2"]}])}
    plan = _compile(_policy({"permission": [{"target": "uc:main", "action": "read", "assignee": AUD}]}), audiences=audiences)
    assert {e.principal for e in plan.entitlements} == {"group:g1", "group:g2"}


def test_everyone_maps_to_account_users_and_empty_audience_grants_nothing():
    audiences = {AUD: odrl.CollectionDef(AUD, "Empty")}
    plan = _compile(_policy({"permission": [
        {"target": "uc:main", "action": "ontos:browse"},
        {"target": "uc:hr", "action": "read", "assignee": AUD}]}), audiences=audiences)
    grants = uc.build_grants(plan)
    assert _keys(grants) == {("account users", "catalog", "main", "BROWSE")}


def test_full_prohibition_removes_grant_across_policies():
    allow = _policy({"permission": [{"target": "uc:main.hr.salaries", "action": "read", "assignee": "user:ana@example.com"}]})
    deny = _policy({"prohibition": [{"target": "uc:main.hr", "action": "use", "assignee": "user:ana@example.com"}]},
                   uid="urn:ontos:policy:p2", name="P2")
    plan = _compile(allow, deny)
    assert plan.entitlements == [] and not plan.has_errors
    assert any(i.code == "denied_by_prohibition" for i in plan.issues)


def test_narrower_prohibition_is_a_blocking_error():
    plan = _compile(_policy({
        "permission": [{"target": "uc:main", "action": "read", "assignee": "group:analysts"}],
        "prohibition": [{"target": "uc:main.hr", "action": "read", "assignee": "group:analysts"}]}))
    assert plan.has_errors and plan.entitlements == []
    assert any(i.code == "prohibition_unenforceable" for i in plan.issues)


def test_user_prohibition_against_group_grant_is_unenforceable():
    plan = _compile(_policy({
        "permission": [{"target": "uc:main.sales", "action": "read", "assignee": "group:analysts"}],
        "prohibition": [{"target": "uc:main.sales", "action": "read", "assignee": "user:eve@example.com"}]}))
    assert plan.has_errors


def test_conflict_perm_lets_permission_win_within_policy_only():
    plan = _compile(_policy({
        "permission": [{"target": "uc:main.sales", "action": "read", "assignee": "group:a"}],
        "prohibition": [{"target": "uc:main.sales", "action": "read", "assignee": "group:a"}]}, conflict="perm"))
    assert [e.securable for e in plan.entitlements] == ["uc:main.sales"]


def test_conflict_invalid_voids_policy():
    plan = _compile(_policy({
        "permission": [{"target": "uc:main.sales", "action": "read", "assignee": "group:a"},
                       {"target": "uc:other", "action": "read", "assignee": "group:a"}],
        "prohibition": [{"target": "uc:main.sales", "action": "read", "assignee": "group:a"}]}, conflict="invalid"))
    assert plan.entitlements == [] and any(i.code == "policy_conflict_invalid" for i in plan.issues)


def test_duties_purpose_and_abac_operands_are_gated_not_granted():
    plan = _compile(_policy({"permission": [
        {"target": "uc:a", "action": "read", "assignee": "group:g", "duty": [{"action": "ontos:acknowledgeTerms"}]},
        {"target": "uc:b", "action": "read", "assignee": "group:g",
         "constraint": [{"leftOperand": "purpose", "operator": "eq", "rightOperand": "analytics"}]},
        {"target": "uc:c", "action": "read", "assignee": "group:g",
         "constraint": [{"leftOperand": "spatial", "operator": "eq", "rightOperand": "EU"}]},
        {"target": "uc:d", "action": "read", "assignee": "group:g",
         "constraint": [{"leftOperand": "ontos:remark", "operator": "eq", "rightOperand": "be nice"}]},
    ]}))
    assert [e.securable for e in plan.entitlements] == ["uc:d"]
    assert plan.entitlements[0].advisories
    assert sorted(g.gate for g in plan.gated) == ["abac", "workflow", "workflow"]


def test_datetime_bounds_become_expiry_and_expired_rules_drop():
    plan = _compile(_policy({"permission": [
        {"target": "uc:a", "action": "read", "assignee": "group:g",
         "constraint": [{"leftOperand": "dateTime", "operator": "lteq", "rightOperand": "2027-01-01T00:00:00Z"}]},
        {"target": "uc:b", "action": "read", "assignee": "group:g",
         "constraint": [{"leftOperand": "dateTime", "operator": "lt", "rightOperand": "2026-01-01"}]},
        {"target": "uc:c", "action": "read", "assignee": "group:g",
         "constraint": [{"leftOperand": "dateTime", "operator": "gteq", "rightOperand": "2027-06-01"}]},
    ]}))
    assert [(e.securable, e.expires_at) for e in plan.entitlements] == [("uc:a", "2027-01-01T00:00:00Z")]
    assert {i.code for i in plan.issues} >= {"expired", "not_yet_active"}


def test_refined_asset_collection_gates_permission_and_blocks_prohibition():
    cols = {COL: odrl.CollectionDef(COL, "Restricted", members=["uc:main"], refinement=[
        {"leftOperand": "ontos:classification", "operator": "eq", "rightOperand": "restricted"}])}
    plan = _compile(_policy({"permission": [{"target": COL, "action": "read", "assignee": "group:g"}]}), collections=cols)
    assert plan.entitlements == [] and plan.gated[0].gate == "abac"
    plan = _compile(_policy({"prohibition": [{"target": COL, "action": "read", "assignee": "group:g"}]}), collections=cols)
    assert plan.has_errors


def test_unresolved_audience_in_prohibition_fails_closed():
    plan = _compile(_policy({"prohibition": [{"target": "uc:main", "action": "read", "assignee": AUD}]}))
    assert plan.has_errors and any(i.code == "prohibition_inexact" for i in plan.issues)


def test_foreign_targets_skipped_and_unmapped_action_gated():
    plan = _compile(_policy({"permission": [
        {"target": "urn:x:thing", "action": "read", "assignee": "group:g"},
        {"target": "uc:main.s.t", "action": "ontos:browse", "assignee": "group:g"}]}))
    grants = uc.build_grants(plan)
    assert grants == []
    assert any(i.code == "foreign_target" for i in plan.issues)
    assert any(g.gate == "unsupported" for g in plan.gated)


def test_expiry_merge_unbounded_wins_and_volume_kind():
    plan = _compile(_policy({"permission": [
        {"target": "uc:main.s.files", "action": "read", "assignee": "group:g",
         "constraint": [{"leftOperand": "dateTime", "operator": "lteq", "rightOperand": "2027-01-01"}]},
        {"target": "uc:main.s", "action": "read", "assignee": "group:g"}]}))
    grants = uc.build_grants(plan, resolve_object_kind=lambda n: "volume")
    by = {(g.securable_name, g.privilege): g for g in grants}
    assert ("main.s.files", "READ_VOLUME") in by
    assert by[("main.s", "USE_SCHEMA")].expires_at is None and by[("main.s", "USE_SCHEMA")].implied is False
    assert by[("main", "USE_CATALOG")].expires_at is None


def test_diff_and_sql_runbook():
    a = uc.UCGrant("analysts", "table", "main.sales.orders", "SELECT")
    b = uc.UCGrant("analysts", "catalog", "main", "USE_CATALOG", implied=True)
    c = uc.UCGrant("old", "schema", "main.x", "USE_SCHEMA")
    d_new = uc.UCGrant("analysts", "catalog", "main", "USE_CATALOG", expires_at="2027-01-01T00:00:00Z")
    diff = uc.diff_grants([a, d_new], [b, c])
    assert [g.principal for g in diff.add] == ["analysts"] and [g.principal for g in diff.remove] == ["old"]
    assert len(diff.update) == 1
    sql = uc.render_sql(diff)
    assert sql == ["REVOKE USE SCHEMA ON SCHEMA `main`.`x` FROM `old`;",
                   "GRANT SELECT ON TABLE `main`.`sales`.`orders` TO `analysts`;"]


def test_live_diff_reports_missing_unmanaged_and_stale():
    desired = [uc.UCGrant("a", "table", "m.s.t", "SELECT")]
    managed = [uc.UCGrant("old", "table", "m.s.t", "SELECT")]
    live = {("table", "m.s.t"): [{"principal": "old", "privileges": ["SELECT"]},
                                 {"principal": "manual", "privileges": ["MODIFY"]}]}
    out = uc.live_diff(managed, desired, live)
    assert [r["principal"] for r in out["missing"]] == ["a"]
    assert [r["principal"] for r in out["unmanaged"]] == ["manual"]
    assert [r["principal"] for r in out["stale"]] == ["old"] and out["in_sync"] is False


def test_typed_principal():
    assert typed_principal("mailto:A@x.com") == "user:a@x.com"
    assert typed_principal("data-eng") == "group:data-eng"
    assert typed_principal("x@y.z") == "user:x@y.z"


# ------------------------------------------------------------ review findings

def test_prohibition_matches_principals_case_insensitively():
    plan = _compile(_policy({
        "permission": [{"target": "uc:main.hr", "action": "read", "assignee": "user:Alice@corp.com"}],
        "prohibition": [{"target": "uc:main.hr", "action": "read", "assignee": "alice@corp.com"}]}))
    assert plan.entitlements == []


def test_expiry_merge_compares_instants_not_strings():
    assert uc._merge_expiry("2026-12-31T23:59:59Z", "2026-12-31T23:59:59.500000Z") == "2026-12-31T23:59:59.500000Z"


def test_preexisting_ledger_grants_are_untracked_not_revoked():
    shared = uc.UCGrant("account users", "catalog", "main", "USE_CATALOG", implied=True, preexisting=True)
    own = uc.UCGrant("account users", "table", "main.s.t", "SELECT")
    diff = uc.diff_grants([], [shared, own])
    assert [g.privilege for g in diff.remove] == ["SELECT"] and [g.privilege for g in diff.untrack] == ["USE_CATALOG"]
    assert uc.render_sql(diff) == ["REVOKE SELECT ON TABLE `main`.`s`.`t` FROM `account users`;"]


# ------------------------------------------------------------ /review findings (2nd pass)

def test_void_policy_prohibitions_have_no_effect_on_other_policies():
    void = _policy({  # no conflict strategy → spec default 'invalid'
        "permission": [{"target": "uc:main.hr", "action": "read", "assignee": "group:g"}],
        "prohibition": [{"target": "uc:main.hr", "action": "read", "assignee": "group:g"}]}, conflict=None)
    other = _policy({"permission": [{"target": "uc:main.hr", "action": "read", "assignee": "group:g"}]},
                    uid="urn:ontos:policy:p2", name="P2")
    for order in ((void, other), (other, void)):
        plan = _compile(*order)
        assert [e.source.policy_uid for e in plan.entitlements] == ["urn:ontos:policy:p2"]
        assert [i.code for i in plan.issues if i.severity == "error"] == ["policy_conflict_invalid"]


def test_scheduled_prohibition_becomes_the_grant_expiry():
    plan = _compile(
        _policy({"permission": [{"target": "uc:main.hr", "action": "read", "assignee": "group:g"}]}),
        _policy({"prohibition": [{"target": "uc:main", "action": "use", "assignee": "group:g",
                                  "constraint": [{"leftOperand": "dateTime", "operator": "gteq",
                                                  "rightOperand": "2026-11-01T00:00:00Z"}]}]},
                uid="urn:ontos:policy:p2", name="P2"))
    assert [(e.securable, e.expires_at) for e in plan.entitlements] == [("uc:main.hr", "2026-11-01T00:00:00Z")]
    assert not plan.has_errors


def test_live_diff_ignores_principal_case():
    desired = [uc.UCGrant("jane.doe@corp.com", "table", "m.s.t", "SELECT")]
    out = uc.live_diff(desired, desired, {("table", "m.s.t"): [{"principal": "Jane.Doe@corp.com", "privileges": ["SELECT"]}]})
    assert out["in_sync"] and out["missing"] == [] and out["unmanaged"] == []



def test_offer_permissions_are_gated_and_only_assigned_offer_prohibitions_apply():
    offer = PolicyInput(doc={"uid": "urn:ontos:policy:o", "type": "Offer", "conflict": "prohibit",
                             "permission": [{"target": "uc:main.sales", "action": "read", "assigner": "user:o@x.com"}],
                             "prohibition": [
                                 # Unbound product term: binds consumers via their Agreements, not everyone.
                                 {"target": "uc:main.sales.pii", "action": "use", "assigner": "user:o@x.com"},
                                 {"target": "uc:main.sales.pii", "action": "use", "assigner": "user:o@x.com",
                                  "assignee": "user:banned@x.com"}]},
                        id="o", name="Offer", version="1.0.0")
    other = _policy({"permission": [{"target": "uc:main.sales.pii", "action": "read", "assignee": "user:ok@x.com"},
                                    {"target": "uc:main.sales.pii", "action": "read", "assignee": "user:banned@x.com"}]})
    plan = _compile(offer, other)
    assert [e.principal for e in plan.entitlements] == ["user:ok@x.com"]
    assert [g.gate for g in plan.gated] == ["workflow"]
