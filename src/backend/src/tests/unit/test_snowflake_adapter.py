"""Snowflake target adapter (P4b): roles for principals, ALL + FUTURE grants for containers."""
from src.common import policy_targets as pt
from src.common import snowflake_policy_adapter as sf
from src.common import uc_policy_adapter as uc
from src.common.odrl_compiler import PolicyInput, compile_policies

SF = pt.get_adapter("snowflake")


def _plan(rules, policy_type="Set"):
    doc = {"uid": "urn:ontos:policy:p1", "@type": policy_type, "conflict": "prohibit", **rules}
    return compile_policies([PolicyInput(doc=doc, id="p1", name="P", version="1.0.0")], audiences={},
                            asset_collections={}, directory=lambda: [])


def _keys(grants):
    return {(g.principal, g.securable_type, g.securable_name, g.privilege) for g in grants}


def test_registered_and_owns_only_snowflake_refs():
    assert SF is not None and SF.label == "Snowflake" and pt.CAP_APPLY_GRANTS not in SF.capabilities
    plan = _plan({"permission": [{"target": "snowflake:DB.S.T", "action": "read", "assignee": "group:analysts"},
                                 {"target": "uc:main.s.t", "action": "read", "assignee": "group:analysts"}]})
    SF.own_plan(plan)
    assert [e.securable for e in plan.entitlements] == ["snowflake:db.s.t"]


def test_table_read_for_a_group_uses_the_group_role_and_parent_usage():
    plan = _plan({"permission": [{"target": "snowflake:db.s.t", "action": "read", "assignee": "group:analysts"}]})
    SF.own_plan(plan)
    assert _keys(SF.build(plan, None)) == {("ANALYSTS", "table", "db.s.t", "SELECT"),
                                         ("ANALYSTS", "database", "db", "USAGE"),
                                         ("ANALYSTS", "schema", "db.s", "USAGE")}


def test_user_gets_a_derived_role_and_schema_read_becomes_all_and_future():
    plan = _plan({"permission": [{"target": "snowflake:db.s", "action": "read", "assignee": "user:Jane@x.com"}]})
    SF.own_plan(plan)
    grants = SF.build(plan, None)
    role = sf.derived_role("user:Jane@x.com")
    assert role.startswith("ONTOS_U_") and role == sf.derived_role("user:jane@x.com")
    keys = _keys(grants)
    assert ("jane@x.com", "role", role, "MEMBER") in keys
    assert {(role, f"schema:{p}:{w}", "db.s", "SELECT") for p in ("tables", "views") for w in ("all", "future")} <= keys
    sql = SF.render_sql(uc.diff_grants(grants, []))
    assert sql[0] == f'CREATE ROLE IF NOT EXISTS "{role}";'
    assert f'GRANT SELECT ON FUTURE TABLES IN SCHEMA "DB"."S" TO ROLE "{role}";' in sql
    assert sql[-1] == f'GRANT ROLE "{role}" TO USER "JANE@X.COM";'


def test_revocations_drop_membership_first():
    plan = _plan({"permission": [{"target": "snowflake:db.s.t", "action": "read", "assignee": "user:a@x.com"}]})
    SF.own_plan(plan)
    sql = SF.render_sql(uc.diff_grants([], SF.build(plan, None)))
    assert sql[0].startswith("REVOKE ROLE") and all(s.startswith("REVOKE") for s in sql)


def test_unsupported_actions_are_gated_and_masks_block():
    plan = _plan({"permission": [{"target": "snowflake:db.s.t", "action": "ontos:manage", "assignee": "group:g"}]})
    SF.own_plan(plan)
    assert SF.build(plan, None) == [] and plan.gated
    plan2 = _plan({})
    from src.common.odrl_compiler import AbacRule
    plan2.abac = [AbacRule("column_mask", ["group:g"], ["snowflake:db.s.t"], "pii")]
    SF.build(plan2, None)
    assert plan2.has_errors


def test_identifiers_are_quoted_safely():
    assert sf.ident('db.we"ird') == '"DB"."WE""IRD"'


def test_prohibitions_do_not_cross_platforms():
    plan = _plan({"permission": [{"target": "snowflake:db.s.t", "action": "read", "assignee": "group:g"}],
                  "prohibition": [{"target": "uc:db.s.t", "action": "read", "assignee": "group:g"}]})
    SF.own_plan(plan)
    assert [e.securable for e in plan.entitlements] == ["snowflake:db.s.t"]


# ------------------------------------------------------------ /review findings (P4b)

def test_adapter_module_imports_first_in_a_fresh_interpreter():
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    out = subprocess.run([sys.executable, "-c", "import src.common.snowflake_policy_adapter as m; "
                          "from src.common import policy_targets as pt; assert pt.get_adapter('snowflake')"],
                         cwd=root, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


def test_derived_roles_are_per_target():
    assert sf.derived_role("user:a@x.com", "sf-a") != sf.derived_role("user:a@x.com", "sf-b")


def test_database_future_grants_are_repeated_on_schemas_with_their_own():
    plan = _plan({"permission": [{"target": "snowflake:db", "action": "read", "assignee": "group:a"},
                                 {"target": "snowflake:db.s", "action": "read", "assignee": "group:b"}]})
    SF.own_plan(plan)
    keys = _keys(SF.build(plan, None))
    assert ("A", "schema:tables:future", "db.s", "SELECT") in keys
    assert any(i.code == "snowflake_future_precedence" for i in plan.issues)


def test_listed_views_are_granted_on_view():
    plan = _plan({"permission": [{"target": "snowflake:db.s.v", "action": "read", "assignee": "group:a"}]})
    SF.own_plan(plan)
    target = pt.ResolvedTarget(key="sf", label="SF", adapter=SF, connection={"views": ["DB.S.V"]})
    grants = SF.build(plan, None, target=target)
    assert ("A", "view", "db.s.v", "SELECT") in _keys(grants)
    assert 'GRANT SELECT ON VIEW "DB"."S"."V" TO ROLE "A";' in SF.render_sql(uc.diff_grants(grants, []))


def test_only_plain_usage_for_shared_roles_is_assumed_preexisting():
    plan = _plan({"permission": [{"target": "snowflake:db", "action": "read", "assignee": "group:a"},
                                 {"target": "snowflake:db.s.t", "action": "read", "assignee": "user:u@x.com"}]})
    SF.own_plan(plan)
    assumed = {(g.principal, g.securable_type) for g in SF.build(plan, None) if SF.assume_preexisting(g)}
    assert assumed == {("A", "database")}


def test_platform_scoped_compile_skips_other_platforms_issues():
    doc = {"uid": "urn:ontos:policy:p1", "@type": "Set", "conflict": "prohibit",
           "permission": [{"target": "uc:main.s.t", "action": "read", "assignee": "group:g"},
                          {"target": "snowflake:db.s.t", "action": "read", "assignee": "group:g"}],
           "prohibition": [{"target": "uc:main.s", "action": "read", "assignee": "group:g"}]}
    plan = compile_policies([PolicyInput(doc=doc, id="p1", name="P", version="1.0.0")], audiences={},
                            asset_collections={}, directory=lambda: [], owns=SF.owns)
    assert not plan.has_errors and [e.securable for e in plan.entitlements] == ["snowflake:db.s.t"]
    assert plan.elsewhere == {"uc:main.s.t", "uc:main.s"}
