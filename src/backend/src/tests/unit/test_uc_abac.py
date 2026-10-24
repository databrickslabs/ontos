"""UC ABAC strategy: column masks and row filters compiled from ODRL constraints (Phase 3)."""
from datetime import datetime, timezone

from src.common import uc_policy_adapter as uc
from src.common.odrl_compiler import AbacConfig, PolicyInput, compile_policies

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)
ABAC = AbacConfig(mask_function="gov.abac.mask", row_filter_function="gov.abac.region_eq", spatial_tag="region",
                  has_tagged_column=lambda table, tag: True)
MASK = {"prohibition": [{"target": "uc:main.sales", "action": "read", "assignee": "group:contractors",
                         "constraint": [{"leftOperand": "ontos:columnTag", "operator": "eq", "rightOperand": "pii=ssn"}]}]}
REGION = {"permission": [{"target": "uc:main.sales.orders", "action": "read", "assignee": "group:eu_analysts",
                          "constraint": [{"leftOperand": "spatial", "operator": "eq", "rightOperand": "EU"}]}]}


def _plan(rules, abac=ABAC):
    return compile_policies([PolicyInput(doc={"uid": "urn:ontos:policy:p", "type": "Set", "conflict": "prohibit", **rules},
                                         id="p", name="P", version="1.0.0")], now=NOW, abac=abac)


def test_disabled_abac_keeps_the_old_fail_safe_behaviour():
    off = AbacConfig()
    assert [g.gate for g in _plan(REGION, off).gated] == ["abac"]
    plan = _plan({**MASK, "permission": [{"target": "uc:main.sales", "action": "read", "assignee": "group:contractors"}]}, off)
    assert plan.entitlements == [] and plan.abac == []  # prohibition applied unconditionally


def test_column_tag_prohibition_becomes_a_column_mask_not_a_deny():
    plan = _plan({**MASK, "permission": [{"target": "uc:main.sales", "action": "read", "assignee": "group:contractors"}]})
    assert [e.principal for e in plan.entitlements] == ["group:contractors"]
    [rule] = plan.abac
    assert (rule.kind, rule.tag_key, rule.tag_value, rule.principals) == ("column_mask", "pii", "ssn", ["group:contractors"])
    [row] = uc.build_abac(plan, ABAC)
    assert row.securable_type == uc.ABAC_POLICY and row.spec["on_securable_type"] == "SCHEMA"
    assert row.spec["match_condition"] == "has_tag_value('pii', 'ssn')"
    assert uc.abac_create_sql(row.spec).startswith(f"CREATE POLICY `{row.spec['name']}` ON SCHEMA `main`.`sales`")


def test_spatial_permission_becomes_grant_plus_row_filter():
    plan = _plan(REGION)
    assert [(e.principal, e.securable) for e in plan.entitlements] == [("group:eu_analysts", "uc:main.sales.orders")]
    [row] = uc.build_abac(plan, ABAC)
    assert row.spec["kind"] == "row_filter" and row.spec["on_securable_type"] == "TABLE"
    assert row.spec["using"] == [{"alias": "c"}, {"constant": "EU"}] and row.spec["to_principals"] == ["eu_analysts"]


def test_policy_names_are_deterministic_and_change_with_the_rule():
    a = uc.build_abac(_plan(REGION), ABAC)[0]
    b = uc.build_abac(_plan(REGION), ABAC)[0]
    other = uc.build_abac(_plan({"permission": [{**REGION["permission"][0], "constraint": [
        {"leftOperand": "spatial", "operator": "eq", "rightOperand": "US"}]}]}), ABAC)[0]
    assert a.key == b.key and a.key != other.key


def test_mask_for_everyone_or_inexact_parties_is_an_error():
    plan = _plan({"prohibition": [{**MASK["prohibition"][0], "assignee": None}]})
    assert plan.has_errors and plan.abac == []


def test_diff_sql_orders_restrictions_safely_and_grants_ignore_abac_rows():
    mask = uc.build_abac(_plan(MASK), ABAC)[0]
    grant = uc.UCGrant("x", "table", "m.s.t", "SELECT")
    old = uc.UCGrant(uc.ABAC_PRINCIPAL, uc.ABAC_POLICY, "SCHEMA:m.s:ontos_column_mask_old", "COLUMN_MASK")
    diff = uc.diff_grants([mask, grant], [old])
    sql = uc.render_sql(diff)
    assert sql[0].startswith("CREATE POLICY") and sql[1].startswith("GRANT") and sql[-1].startswith("DROP POLICY `ontos_column_mask_old` ON SCHEMA `m`.`s`")
    assert uc.group_for_apply(diff.add) == [{"principal": "x", "securable_type": "table", "securable_name": "m.s.t",
                                            "privileges": ["SELECT"]}]


def test_policy_info_for_the_sdk():
    from src.controller.grant_manager import _abac_policy_info
    spec = uc.build_abac(_plan(REGION), ABAC)[0].spec
    info = _abac_policy_info(spec)
    assert info.policy_type.value == "POLICY_TYPE_ROW_FILTER" and info.row_filter.function_name == "gov.abac.region_eq"
    assert info.match_columns[0].condition == "has_tag('region')" and info.row_filter.using[1].constant == "EU"



# ------------------------------------------------------------ /review findings (P3d)

def _perm(target, region=None, principal="group:eu"):
    c = [{"leftOperand": "spatial", "operator": "eq", "rightOperand": region}] if region else []
    return {"target": target, "action": "read", "assignee": principal, "constraint": c}


def test_row_filter_needs_a_verified_tagged_column_on_a_table():
    for cfg in (AbacConfig(row_filter_function="f", has_tagged_column=lambda t, g: False),
                AbacConfig(row_filter_function="f", has_tagged_column=lambda t, g: None),
                AbacConfig(row_filter_function="f")):
        plan = _plan({"permission": [_perm("uc:main.sales.orders", "EU")]}, cfg)
        assert plan.entitlements == [] and plan.abac == [] and [g.gate for g in plan.gated] == ["abac"]
    plan = _plan({"permission": [_perm("uc:main.sales", "EU")]})  # schema target
    assert plan.entitlements == []


def test_several_regions_are_withheld_and_unconditional_access_needs_no_filter():
    plan = _plan({"permission": [_perm("uc:main.sales.orders", "EU"), _perm("uc:main.sales.orders", "US")]})
    assert plan.entitlements == [] and plan.abac == []
    plan = _plan({"permission": [_perm("uc:main.sales.orders", "EU"), _perm("uc:main.sales")]})
    assert plan.abac == [] and {e.row_filter for e in plan.entitlements} == {None}


def test_only_exact_read_prohibitions_become_masks_and_perm_overrides():
    use = {"prohibition": [{**MASK["prohibition"][0], "action": "use"}],
           "permission": [{"target": "uc:main.sales", "action": "modify", "assignee": "group:contractors"}]}
    plan = _plan(use)
    assert plan.abac == [] and plan.entitlements == []  # broader deny stays fail-closed
    perm = compile_policies([PolicyInput(doc={"uid": "urn:ontos:policy:p", "type": "Set", "conflict": "perm", **MASK,
                                              "permission": [{"target": "uc:main.sales", "action": "read",
                                                              "assignee": "group:contractors"}]},
                                         id="p", name="P", version="1.0.0")], now=NOW, abac=ABAC)
    assert perm.abac == []


def test_unbuildable_abac_policy_blocks_the_release():
    plan = _plan(MASK | {"prohibition": [{**MASK["prohibition"][0], "target": "uc:main.sales.files"}]})
    uc.build_abac(plan, ABAC, resolve_object_kind=lambda n: "volume")
    assert plan.has_errors


def test_failed_restriction_withholds_grants():
    from types import SimpleNamespace

    from src.controller.delivery_service import (
        DeliveryChangeType,
        DeliveryMode,
        DeliveryPayload,
        DeliveryService,
    )

    class G:
        def __init__(self):
            self.calls = []

        def apply_abac_policy(self, spec, dry_run=False):
            return {"success": False, "error": "ABAC beta disabled"}

        def apply_grant(self, data, dry_run=False):
            self.calls.append("grant")
            return {"success": True}

        def apply_revoke(self, data, dry_run=False):
            self.calls.append("revoke")
            return {"success": True}

        def drop_abac_policy(self, ref, dry_run=False):
            return {"success": True}

    g = G()
    svc = DeliveryService(settings=SimpleNamespace(DELIVERY_DIRECT_DRY_RUN=False), grant_manager=g)
    data = {"abac_create": [{"name": "m"}], "revoke": [{"principal": "a", "privileges": ["SELECT"], "securable_name": "x"}],
            "grant": [{"principal": "b", "privileges": ["SELECT"], "securable_name": "y"}]}
    res = svc.deliver(DeliveryPayload(change_type=DeliveryChangeType.POLICY_RELEASE, entity_type="AccessPolicyRelease",
                                      entity_id="r", data=data), [DeliveryMode.DIRECT]).results[0]
    assert g.calls == ["revoke"] and res.success is False
