"""Scoped domain context and the ODRL-shaped rule of an Authority Relation (#1294).

Covers the pure layer (src.common.authority_rule), the Compliance-DSL
``ctx.`` / ``req.`` namespaces, and the manager: the scope gate at resolve time,
rule constraints / duties / prohibitions, anti-spoofing, DNA over evidence rows,
the MCP tool's ``context`` and the legacy-blob migration.
"""
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.common import authority_rule as arule
from src.common.compliance_dsl import evaluate_rule_on_object
from src.controller.authority_resolution_manager import (
    AuthorityResolutionManager,
    VERDICT_APPROVED,
    VERDICT_CONDITIONAL,
    VERDICT_DENIED,
    VERDICT_NO_AUTHORITY,
)
from src.models.authority_resolution import (
    AuthorityRelationCreate,
    AuthorityRelationUpdate,
    CriterionInput,
    PrerequisiteInput,
)

CEILING = {"leftOperand": "payAmount", "operator": "lteq", "rightOperandReference": "ctx.threshold",
           "message": "Value is above the threshold."}
COSIGN_DUTY = {"action": "arf:obtainCoApproval", "name": "CFO co-approval",
               "message": "CFO co-approval is pending.",
               "constraint": [{"leftOperand": "arf:cosignPresent", "operator": "eq", "rightOperand": True}]}


def _ar(mgr, db, *, slug="tp", scope=None, params=None, rule=None, criteria=None, prerequisites=None):
    return mgr.create_relation(db, AuthorityRelationCreate(
        name=f"AR {slug}", slug=slug,
        domain_context={"scope": scope or [], "params": params or {}},
        rule=rule,
        criteria=[CriterionInput(**c) for c in (criteria or [])],
        prerequisites=[PrerequisiteInput(**p) for p in (prerequisites or [])],
    ))


def _resolve(mgr, db, slug, req, **kw):
    return mgr.resolve(db, slug, req, record=False, require_active=False, **kw)


# ------------------------------------------------------------- DSL namespaces

def test_dsl_reads_ctx_and_req_namespaces():
    obj = {"value": 5, "ctx": {"threshold": 10}, "req": {"market": "DE"}}
    assert evaluate_rule_on_object("ASSERT obj.value <= ctx.threshold", obj) == (True, None)
    assert evaluate_rule_on_object("ASSERT req.market = 'DE'", obj)[0] is True
    assert evaluate_rule_on_object("ASSERT ctx.missing = 1", obj)[0] is False


def test_dsl_other_prefixes_read_top_level_as_before():
    # ``p.x`` / ``obj.x`` read the top level; ``ctx.x`` too when there is no ctx namespace.
    assert evaluate_rule_on_object("ASSERT p.value = 5", {"value": 5})[0] is True
    assert evaluate_rule_on_object("ASSERT ctx.value = 5", {"value": 5})[0] is True


# ------------------------------------------------------------- domain context

def test_legacy_flat_blob_becomes_params():
    assert arule.normalize_domain_context({"market": "DE", "threshold": 0.1}) == {
        "scope": [], "params": {"market": "DE", "threshold": 0.1},
    }
    assert arule.normalize_domain_context(None) == {"scope": [], "params": {}}


def test_scope_mapping_becomes_odrl_constraints():
    dc = arule.normalize_domain_context({"scope": {"market": ["DE", "AT"], "spatial": "EU"}})
    assert dc["scope"] == [
        {"leftOperand": "arf:market", "operator": "isAnyOf", "rightOperand": ["DE", "AT"]},
        {"leftOperand": "spatial", "operator": "eq", "rightOperand": "EU"},
    ]


@pytest.mark.parametrize("bad", [
    {"scope": [{"leftOperand": "arf:market", "operator": "like", "rightOperand": "DE"}]},
    {"scope": [{"leftOperand": "bad name", "operator": "eq", "rightOperand": "DE"}]},
    {"scope": [{"leftOperand": "arf:market", "operator": "eq", "rightOperandReference": "ctx.m"}]},
    {"scope": [{"leftOperand": "arf:market", "operator": "eq", "rightOperand": ["DE", "AT"]}]},
    {"params": {"not-an-identifier": 1}},
])
def test_invalid_domain_context_is_rejected_on_write(bad):
    with pytest.raises(ValueError):
        arule.normalize_domain_context(bad, strict=True)


def test_update_replaces_only_the_parts_sent(db_session):
    mgr = AuthorityResolutionManager()
    rel = _ar(mgr, db_session, scope=[{"leftOperand": "arf:market", "operator": "eq", "rightOperand": "DE"}],
              params={"threshold": 0.1})
    mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(domain_context={"params": {"threshold": 0.2}}))
    dc = mgr.get_relation(db_session, rel.id).domain_context
    assert dc["params"] == {"threshold": 0.2}
    assert dc["scope"][0]["rightOperand"] == "DE"


# ------------------------------------------------------------- scope gate

MARKET_DACH = [{"leftOperand": "arf:market", "operator": "isAnyOf", "rightOperand": ["DE", "AT", "CH"]}]


def test_scope_gate_accepts_member_and_rejects_others(db_session):
    mgr = AuthorityResolutionManager()
    _ar(mgr, db_session, scope=MARKET_DACH)
    assert _resolve(mgr, db_session, "tp", {"market": "at"})["verdict"] == VERDICT_APPROVED

    out = _resolve(mgr, db_session, "tp", {"market": "FR"})
    assert out["verdict"] == VERDICT_NO_AUTHORITY
    assert out["reason"] == "out of scope: market=FR"
    assert out["scope_check"][0]["passed"] is False


def test_scope_gate_missing_key_is_no_authority(db_session):
    mgr = AuthorityResolutionManager()
    _ar(mgr, db_session, scope=MARKET_DACH)
    out = _resolve(mgr, db_session, "tp", {"value": 1})
    assert out["verdict"] == VERDICT_NO_AUTHORITY
    assert out["reason"] == "context.market missing"


def test_scope_gate_is_recorded_in_provenance(db_session):
    from src.repositories.authority_resolution_repository import authority_decision_repo
    mgr = AuthorityResolutionManager()
    rel = _ar(mgr, db_session, scope=MARKET_DACH)
    mgr.resolve(db_session, "tp", {"market": "FR"}, record=True, require_active=False)
    [decision] = authority_decision_repo.list_for_relation(db_session, relation_id=rel.id)
    assert decision.verdict == VERDICT_NO_AUTHORITY
    assert decision.provenance["scope_check"][0]["actual"] == "FR"


def test_scope_gate_matches_a_concept_label_to_its_iri(db_session):
    mgr = AuthorityResolutionManager()
    _ar(mgr, db_session, scope=[{"leftOperand": "arf:brand", "operator": "eq",
                                  "rightOperand": "urn:demo:brand:alpha-cola"}])

    class Semantic:
        def find_concept_iris_by_label(self, text, limit=20):
            return ["urn:demo:brand:alpha-cola"] if text.lower() == "alpha cola" else []

        def get_concept_details(self, iri):
            return None

    out = _resolve(mgr, db_session, "tp", {"brand": "Alpha Cola"}, semantic_models_manager=Semantic())
    assert out["verdict"] == VERDICT_APPROVED


def test_prerequisite_is_gated_by_its_own_scope(db_session):
    mgr = AuthorityResolutionManager()
    _ar(mgr, db_session, slug="market-clearance", scope=MARKET_DACH)
    _ar(mgr, db_session, slug="tp", prerequisites=[{"prerequisite_family_slug": "market-clearance"}])
    assert _resolve(mgr, db_session, "tp", {"market": "DE"})["verdict"] == VERDICT_APPROVED
    out = _resolve(mgr, db_session, "tp", {"market": "FR"})
    assert out["verdict"] == VERDICT_DENIED
    assert "out of scope: market=FR" in out["reason"]


# ------------------------------------------------------------- rule

def test_rule_constraint_reads_ctx_params(db_session):
    mgr = AuthorityResolutionManager()
    _ar(mgr, db_session, params={"threshold": 0.15}, rule={"permission": {"constraint": [CEILING]}})
    assert _resolve(mgr, db_session, "tp", {"value": 0.10})["verdict"] == VERDICT_APPROVED
    out = _resolve(mgr, db_session, "tp", {"value": 0.30})
    assert out["verdict"] == VERDICT_DENIED
    assert out["reason"] == "Value is above the threshold."


def test_check_can_compare_request_with_param(db_session):
    mgr = AuthorityResolutionManager()
    _ar(mgr, db_session, params={"threshold": 0.15},
        criteria=[{"name": "ceiling", "rule": "ASSERT req.value <= ctx.threshold", "failure_message": "too high"}])
    assert _resolve(mgr, db_session, "tp", {"value": 0.1})["verdict"] == VERDICT_APPROVED
    assert _resolve(mgr, db_session, "tp", {"value": 0.2})["verdict"] == VERDICT_DENIED


def test_request_cannot_spoof_ctx_or_req(db_session):
    mgr = AuthorityResolutionManager()
    _ar(mgr, db_session, params={"threshold": 0.15}, rule={"permission": {"constraint": [CEILING]}})
    out = _resolve(mgr, db_session, "tp", {"value": 0.30, "ctx": {"threshold": 9}, "req": {"value": 0}})
    assert out["verdict"] == VERDICT_DENIED


def test_unfulfilled_duty_is_conditional_and_fulfilled_duty_approves(db_session):
    mgr = AuthorityResolutionManager()
    _ar(mgr, db_session, rule={"permission": {"constraint": [], "duty": [COSIGN_DUTY]}})
    out = _resolve(mgr, db_session, "tp", {"cosign_present": False})
    assert out["verdict"] == VERDICT_CONDITIONAL
    assert out["pending_duties"] == [{"duty": "CFO co-approval", "message": "CFO co-approval is pending."}]
    assert _resolve(mgr, db_session, "tp", {"cosign_present": True})["verdict"] == VERDICT_APPROVED


def test_duty_with_an_or_constraint_applies_only_above_the_threshold(db_session):
    mgr = AuthorityResolutionManager()
    duty = {"action": "arf:obtainCoApproval", "constraint": [{"or": [
        {"leftOperand": "payAmount", "operator": "lteq", "rightOperandReference": "ctx.threshold"},
        {"leftOperand": "arf:cosignPresent", "operator": "eq", "rightOperand": True},
    ]}]}
    _ar(mgr, db_session, params={"threshold": 100}, rule={"permission": {"duty": [duty]}})
    assert _resolve(mgr, db_session, "tp", {"value": 50})["verdict"] == VERDICT_APPROVED
    assert _resolve(mgr, db_session, "tp", {"value": 500})["verdict"] == VERDICT_CONDITIONAL
    assert _resolve(mgr, db_session, "tp", {"value": 500, "cosign_present": True})["verdict"] == VERDICT_APPROVED


def test_failing_check_denies_before_pending_duties(db_session):
    mgr = AuthorityResolutionManager()
    _ar(mgr, db_session, rule={"permission": {"duty": [COSIGN_DUTY]}},
        criteria=[{"name": "allow", "rule": "ASSERT obj.actor_identity IN ['cpo']", "failure_message": "not the CPO"}])
    out = _resolve(mgr, db_session, "tp", {"actor_identity": "intruder"})
    assert out["verdict"] == VERDICT_DENIED
    assert out["reason"] == "not the CPO"


def test_matched_prohibition_denies(db_session):
    mgr = AuthorityResolutionManager()
    _ar(mgr, db_session, rule={"prohibition": [{
        "message": "No self-grant.",
        "constraint": [{"leftOperand": "arf:grantee", "operator": "eq", "rightOperandReference": "req.actor_identity"}],
    }]})
    out = _resolve(mgr, db_session, "tp", {"actor_identity": "a@x", "grantee": "a@x"})
    assert (out["verdict"], out["reason"]) == (VERDICT_DENIED, "No self-grant.")
    assert _resolve(mgr, db_session, "tp", {"actor_identity": "a@x", "grantee": "b@x"})["verdict"] == VERDICT_APPROVED


def test_conditional_prerequisite_makes_the_outer_conditional(db_session):
    mgr = AuthorityResolutionManager()
    _ar(mgr, db_session, slug="co-approval", rule={"permission": {"duty": [COSIGN_DUTY]}})
    _ar(mgr, db_session, slug="tp", prerequisites=[{"prerequisite_family_slug": "co-approval"}])
    out = _resolve(mgr, db_session, "tp", {"cosign_present": False})
    assert out["verdict"] == VERDICT_CONDITIONAL
    assert out["pending_duties"][0]["duty"] == "CFO co-approval"
    assert out["prerequisite_chain"][0]["pending_duties"][0]["duty"] == "CFO co-approval"
    assert "own_pending_duties" not in out


def test_rule_literals_cannot_break_out_of_the_dsl_string():
    rule = {"permission": {"constraint": [
        {"leftOperand": "arf:market", "operator": "eq", "rightOperand": "DE' OR obj.x = 'y"},
    ]}}
    [c] = arule.compile_rule(rule)
    obj = arule.evaluation_object({"market": "FR", "x": "y"}, {})
    assert evaluate_rule_on_object(c.rule, obj)[0] is False
    obj = arule.evaluation_object({"market": "DE' OR obj.x = 'y"}, {})
    assert evaluate_rule_on_object(c.rule, obj)[0] is True


@pytest.mark.parametrize("bad", [
    {"permission": {"constraint": [{"leftOperand": "payAmount", "operator": "lteq",
                                    "rightOperandReference": "ctx.a; DROP"}]}},
    {"permission": {"duty": [{"action": "arf:obtainCoApproval"}]}},
    {"prohibition": [{"constraint": []}]},
    {"permission": {"constraint": [{"or": [CEILING]}]}},
])
def test_invalid_rule_is_rejected(bad):
    with pytest.raises(ValueError):
        arule.normalize_rule(bad)


def test_rule_is_validated_on_create(db_session):
    mgr = AuthorityResolutionManager()
    with pytest.raises(ValueError):
        _ar(mgr, db_session, rule={"permission": {"constraint": [{"leftOperand": "payAmount", "operator": "near",
                                                                  "rightOperand": 1}]}})


def test_new_version_carries_the_rule_and_context(db_session):
    mgr = AuthorityResolutionManager()
    rel = _ar(mgr, db_session, scope=MARKET_DACH, params={"threshold": 1}, rule={"permission": {"constraint": [CEILING]}})
    new = mgr.create_new_version(db_session, rel.id, "1.1.0")
    assert new.rule == rel.rule
    assert new.domain_context == rel.domain_context


# ------------------------------------------------------------- DNA

def test_dna_evaluates_rule_and_params_per_row_and_skips_out_of_scope_rows(db_session):
    mgr = AuthorityResolutionManager()
    rel = _ar(mgr, db_session, scope=MARKET_DACH, params={"threshold": 0.15},
              rule={"permission": {"constraint": [CEILING], "duty": [COSIGN_DUTY]}})
    rows = [
        {"market": "DE", "value": 0.10, "cosign_present": True},   # clean
        {"market": "DE", "value": 0.30, "cosign_present": True},   # over the ceiling
        {"market": "AT", "value": 0.10, "cosign_present": False},  # duty unfulfilled
        {"market": "FR", "value": 0.99, "cosign_present": False},  # out of scope: skipped
        {"value": 0.10, "cosign_present": True},                   # no market column: kept
    ]
    run = mgr.compute_dnaco(db_session, rel.id, rows=rows)
    assert run.status == "succeeded"
    assert (run.sampled_count, run.divergent_count) == (4, 2)


def test_dna_fails_when_every_row_is_out_of_scope(db_session):
    mgr = AuthorityResolutionManager()
    rel = _ar(mgr, db_session, scope=MARKET_DACH)
    with pytest.raises(ValueError, match="outside the Authority Relation's scope"):
        mgr.compute_dnaco(db_session, rel.id, rows=[{"market": "FR"}])


# ------------------------------------------------------------- concept lookup

def test_concept_lookup_reads_the_scope_values(db_session):
    from src.db_models.semantic_links import EntitySemanticLinkDb
    import uuid
    mgr = AuthorityResolutionManager()
    for slug, market in (("tp-de", "DE"), ("tp-fr", "FR")):
        rel = _ar(mgr, db_session, slug=slug, scope=[{"leftOperand": "arf:market", "operator": "eq",
                                                      "rightOperand": market}])
        rel.status = "active"
        db_session.add(EntitySemanticLinkDb(id=uuid.uuid4(), entity_id=rel.id, entity_type="authority_relation",
                                            iri="urn:c", label="c"))
    db_session.commit()
    out = mgr.find_authority_for_concept(db_session, "urn:c", {"market": "DE"})
    assert out["resolved"] == "tp-de"


# ------------------------------------------------------------- routes, tool, migration

def test_rule_validate_route_compiles_and_tries_a_sample():
    from src.routes.authority_resolution_routes import validate_rule
    payload = {"domain_context": {"scope": {"market": "DE"}, "params": {"threshold": 0.15}},
               "rule": {"permission": {"constraint": [CEILING], "duty": [COSIGN_DUTY]}},
               "request": {"market": "DE", "value": 0.1}}
    out = asyncio.run(validate_rule(None, payload, True))
    assert out["valid"] is True
    assert [c["kind"] for c in out["compiled"]] == ["constraint", "duty"]
    assert out["verdict"] == VERDICT_CONDITIONAL

    out = asyncio.run(validate_rule(None, {**payload, "request": {"market": "FR"}}, True))
    assert (out["verdict"], out["reason"]) == (VERDICT_NO_AUTHORITY, "out of scope: market=FR")

    out = asyncio.run(validate_rule(None, {"rule": {"permission": {"constraint": [{"leftOperand": "x"}]}}}, True))
    assert out["valid"] is False and out["error"]


def test_criteria_validate_route_reads_params_and_context():
    from src.routes.authority_resolution_routes import validate_criterion
    out = asyncio.run(validate_criterion(None, {
        "rule": "req.value <= ctx.threshold AND req.market = 'DE'",
        "object": {"value": 0.1}, "context": {"market": "DE"}, "params": {"threshold": 0.15},
    }, True))
    assert out["passed"] is True


def test_mcp_resolve_tool_forwards_context(monkeypatch):
    from src.tools import authority_resolution as tools_mod
    seen = {}
    monkeypatch.setattr(tools_mod._manager, "resolve", lambda db, ar, req, **kw: seen.setdefault("req", req))
    ctx = SimpleNamespace(db=None, semantic_models_manager=None, obo_workspace_client_factory=None)
    asyncio.run(tools_mod.ResolveAuthorityTool().execute(ctx, ar_id="tp", value=1, context={"market": "DE"}))
    assert seen["req"]["market"] == "DE" and seen["req"]["value"] == 1


def test_migration_wraps_legacy_blobs_and_unwraps_on_downgrade():
    path = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "al1_authority_scoped_context.py"
    spec = importlib.util.spec_from_file_location("al1", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.wrap_legacy({"market": "DE"}) == {"scope": [], "params": {"market": "DE"}}
    already = {"scope": [], "params": {"a": 1}}
    assert mod.wrap_legacy(already) is already
    assert mod.unwrap({"scope": [{"leftOperand": "arf:m"}], "params": {"a": 1}}) == {"a": 1}


# ------------------------------------------------------------- review regressions

def test_legacy_blob_with_a_scope_key_is_still_params():
    blob = {"scope": "feature", "market": "DE"}
    assert arule.normalize_domain_context(blob) == {"scope": [], "params": blob}
    path = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "al1_authority_scoped_context.py"
    spec = importlib.util.spec_from_file_location("al1b", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.wrap_legacy(blob) == {"scope": [], "params": blob}


def test_scope_rejects_logical_constraints():
    with pytest.raises(ValueError, match="plain constraints"):
        arule.normalize_domain_context({"scope": [{"or": [
            {"leftOperand": "arf:market", "operator": "eq", "rightOperand": "DE"},
            {"leftOperand": "arf:market", "operator": "eq", "rightOperand": "AT"},
        ]}]}, strict=True)


def test_negative_and_tiny_literals_compile_and_evaluate():
    rule = {"permission": {"constraint": [
        {"leftOperand": "arf:margin", "operator": "gteq", "rightOperand": -0.05},
        {"leftOperand": "payAmount", "operator": "gt", "rightOperand": 1e-05},
    ]}}
    obj = arule.evaluation_object({"margin": -0.01, "value": 0.001}, {})
    for c in arule.compile_rule(rule):
        assert evaluate_rule_on_object(c.rule, obj)[0] is True, c.rule
    assert evaluate_rule_on_object("ASSERT obj.v = 3 - 1", {"v": 2})[0] is False  # '-' after a value is not a sign


@pytest.mark.parametrize("bad", [
    {"permission": {"constraint": [{"leftOperand": "arf:end", "operator": "eq", "rightOperand": 1}]}},
    {"permission": {"constraint": [{"leftOperand": "payAmount", "operator": "lteq", "rightOperandReference": "ctx.length"}]}},
])
def test_dsl_keyword_names_are_rejected(bad):
    with pytest.raises(ValueError, match="reserved word"):
        arule.normalize_rule(bad)
    with pytest.raises(ValueError, match="reserved word"):
        arule.normalize_domain_context({"params": {"tag": 1}}, strict=True)


def test_explicit_null_clears_the_domain_context(db_session):
    mgr = AuthorityResolutionManager()
    rel = _ar(mgr, db_session, scope=MARKET_DACH, params={"a": 1})
    mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(domain_context=None))
    assert mgr.get_relation(db_session, rel.id).domain_context == {"scope": [], "params": {}}


def test_numeric_string_context_compares_as_a_number(db_session):
    mgr = AuthorityResolutionManager()
    _ar(mgr, db_session, params={"ceiling": 1000}, rule={"permission": {"constraint": [
        {"leftOperand": "arf:budget", "operator": "lteq", "rightOperandReference": "ctx.ceiling"}]}})
    assert _resolve(mgr, db_session, "tp", {"budget": "600"})["verdict"] == VERDICT_APPROVED
    assert _resolve(mgr, db_session, "tp", {"budget": "6000"})["verdict"] == VERDICT_DENIED


def test_context_never_overrides_typed_fields(monkeypatch):
    from src.models.authority_resolution import ResolveRequest
    from src.routes.authority_resolution_routes import _resolve_req_dict
    req = _resolve_req_dict(ResolveRequest(value=900, cosign_present=False,
                                           context={"value": 1, "cosign_present": True, "market": "DE"}))
    assert (req["value"], req["cosign_present"], req["market"]) == (900, False, "DE")

    from src.tools import authority_resolution as tools_mod
    seen = {}
    monkeypatch.setattr(tools_mod._manager, "resolve", lambda db, ar, r, **kw: seen.setdefault("req", r))
    ctx = SimpleNamespace(db=None, semantic_models_manager=None, obo_workspace_client_factory=None)
    asyncio.run(tools_mod.ResolveAuthorityTool().execute(ctx, ar_id="tp", value=900, context={"value": 1}))
    assert seen["req"]["value"] == 900


def _concept_ar(mgr, db, slug, **kw):
    from src.db_models.semantic_links import EntitySemanticLinkDb
    import uuid
    rel = _ar(mgr, db, slug=slug, **kw)
    rel.status = "active"
    db.add(EntitySemanticLinkDb(id=uuid.uuid4(), entity_id=rel.id, entity_type="authority_relation", iri="urn:c", label="c"))
    return rel


def test_concept_lookup_uses_params_of_unscoped_ars_and_every_scope_operator(db_session):
    mgr = AuthorityResolutionManager()
    # Migrated (unscoped) ARs still rank by their params, as before the scope existed.
    _concept_ar(mgr, db_session, "legacy-de", params={"market": "DE"})
    _concept_ar(mgr, db_session, "legacy-fr", params={"market": "FR"})
    # An exclusion scope conflicts with the excluded market.
    _concept_ar(mgr, db_session, "not-de", scope=[{"leftOperand": "arf:market", "operator": "isNoneOf",
                                                   "rightOperand": ["DE"]}])
    db_session.commit()
    out = mgr.find_authority_for_concept(db_session, "urn:c", {"market": "DE"})
    assert out["resolved"] == "legacy-de"
    by_slug = {c["family_slug"]: c for c in out["candidates"]}
    assert by_slug["not-de"]["context_conflicts"] == ["market"]
    assert by_slug["legacy-fr"]["context_conflicts"] == ["market"]


def test_concept_lookup_treats_a_conditional_prerequisite_as_viable(db_session):
    mgr = AuthorityResolutionManager()
    pre = _ar(mgr, db_session, slug="co-approval", rule={"permission": {"duty": [COSIGN_DUTY]}})
    pre.status = "active"
    _concept_ar(mgr, db_session, "tp", prerequisites=[{"prerequisite_family_slug": "co-approval"}])
    db_session.commit()
    out = mgr.find_authority_for_concept(db_session, "urn:c", {}, request={"cosign_present": False})
    assert out["resolved"] == "tp"
    assert out["candidates"][0]["unmet_prerequisites"] == []
