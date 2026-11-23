"""ARF 1.2.0 hardening, batch 4: rule correctness (PR #1491 review, findings 1491-1..6).

One test per probe from the review: a missing operand fails closed (1491-1), a scope
operand reads its canonical field (1491-2), a numeric-looking string matches in a set
(1491-4), a bad weight is refused on save (1491-5), and rule/validate answers the coded
shape (1491-6). Also covers the unknown ``ctx.`` reference refused on save.
"""
import asyncio
import json

import pytest
from fastapi import HTTPException

from src.common import authority_rule as arule
from src.common.api_errors import coded_http_exception_handler
from src.common.compliance_dsl import evaluate_rule_on_object, evaluate_rule_strict
from src.controller.authority_resolution_manager import (
    AuthorityInvalidError,
    AuthorityResolutionManager,
    REASON_MISSING_OPERAND,
    REASON_MISSING_PARAMETER,
    VERDICT_APPROVED,
    VERDICT_CONDITIONAL,
    VERDICT_CONFLICT,
    VERDICT_DENIED,
    VERDICT_NO_AUTHORITY,
)
from src.models.authority_resolution import (
    AuthorityRelationCreate,
    AuthorityRelationUpdate,
    CriterionInput,
    ResourceRefInput,
)


def _ar(mgr, db, *, slug, rule=None, params=None, scope=None, criteria=None):
    return mgr.create_relation(db, AuthorityRelationCreate(
        name=f"AR {slug}", slug=slug,
        domain_context={"scope": scope or [], "params": params or {}},
        rule=rule,
        criteria=[CriterionInput(**c) for c in (criteria or [])],
    ))


def _resolve(mgr, db, slug, req):
    return mgr.resolve(db, slug, req, record=False, require_active=False)


# ------------------------------------------------------------- 1491-1: missing operands

def test_no_self_grant_prohibition_denies_when_the_grantee_is_absent(db_session):
    """Probe: the demo "No self-grant" prohibition approved a request with no grantee."""
    mgr = AuthorityResolutionManager()
    _ar(mgr, db_session, slug="grant", rule={"prohibition": [{
        "message": "A principal may not grant production access to themselves.",
        "constraint": [{"leftOperand": "arf:grantee", "operator": "eq",
                        "rightOperandReference": "req.actor_identity"}],
    }]})
    out = _resolve(mgr, db_session, "grant", {"actor_identity": "a@x"})
    assert out["verdict"] == VERDICT_DENIED
    assert out["reason_code"] == REASON_MISSING_OPERAND
    assert "'grantee'" in out["reason"]
    assert _resolve(mgr, db_session, "grant", {"actor_identity": "a@x", "grantee": "b@x"})["verdict"] == VERDICT_APPROVED


def test_prohibition_on_a_removed_parameter_is_a_conflict_not_an_approval(db_session):
    """Probe: a prohibition on ctx.cap after the parameter is removed approved.

    The save refuses the removal (the rule still reads it). A stored context that lost
    the parameter anyway is undecidable, so it is a conflict.
    """
    mgr = AuthorityResolutionManager()
    rel = _ar(mgr, db_session, slug="cap", params={"cap": 100}, rule={"prohibition": [{
        "message": "Over the cap.",
        "constraint": [{"leftOperand": "payAmount", "operator": "gteq", "rightOperandReference": "ctx.cap"}],
    }]})
    db_session.commit()
    with pytest.raises(arule.UnknownParameterError, match=r"ctx\.cap"):
        mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(domain_context={"params": {}}))

    rel.domain_context = {"scope": [], "params": {}}
    db_session.commit()
    out = _resolve(mgr, db_session, "cap", {"value": 1})
    assert (out["verdict"], out["reason_code"]) == (VERDICT_CONFLICT, REASON_MISSING_PARAMETER)


def test_not_in_a_list_holds_only_when_the_market_is_present(db_session):
    """Probe: ``market isNoneOf [RU]`` approved a request with no market."""
    mgr = AuthorityResolutionManager()
    _ar(mgr, db_session, slug="market", rule={"permission": {"constraint": [
        {"leftOperand": "arf:market", "operator": "isNoneOf", "rightOperand": ["RU"]},
    ]}})
    out = _resolve(mgr, db_session, "market", {"value": 1})
    assert out["verdict"] == VERDICT_DENIED
    assert out["reason_code"] == REASON_MISSING_OPERAND
    assert _resolve(mgr, db_session, "market", {"market": "RU"})["verdict"] == VERDICT_DENIED
    assert _resolve(mgr, db_session, "market", {"market": "DE"})["verdict"] == VERDICT_APPROVED


def test_no_self_grant_template_fails_without_a_grantee(db_session):
    mgr = AuthorityResolutionManager()
    _ar(mgr, db_session, slug="tpl-grant", criteria=[{"template_key": "no_self_grant"}])
    assert _resolve(mgr, db_session, "tpl-grant", {"actor_identity": "a@x"})["verdict"] == VERDICT_DENIED
    assert _resolve(mgr, db_session, "tpl-grant", {"actor_identity": "a@x", "grantee": "b@x"})["verdict"] == VERDICT_APPROVED


def test_general_dsl_semantics_are_unchanged_outside_strict_mode():
    """The fix is ARF-scoped: the general evaluator still reads an absent operand as unequal."""
    assert evaluate_rule_on_object("ASSERT NOT (obj.x = 'y')", {}) == (True, None)


@pytest.mark.parametrize("rule, obj, expected", [
    ("ASSERT obj.a = 1 OR obj.b = 2", {"b": 2}, True),      # UNKNOWN OR TRUE  = TRUE
    ("ASSERT obj.a = 1 AND obj.b = 2", {"b": 3}, False),    # UNKNOWN AND FALSE = FALSE
    ("ASSERT obj.a = 1 AND obj.b = 2", {"b": 2}, None),     # UNKNOWN AND TRUE = UNKNOWN
    ("ASSERT obj.a = 1 OR obj.b = 2", {"b": 3}, None),      # UNKNOWN OR FALSE = UNKNOWN
    ("ASSERT NOT (obj.a = 1)", {}, None),                   # NOT UNKNOWN      = UNKNOWN
    ("ASSERT obj.a = 1", {"a": 1}, True),
    ("ASSERT obj.a = 1", {"a": 2}, False),
])
def test_kleene_truth_tables_for_absent_operands(rule, obj, expected):
    assert evaluate_rule_strict(rule, obj).passed is expected


def test_the_outcome_names_the_absent_operands():
    out = evaluate_rule_strict("ASSERT obj.a = 1 AND obj.b = 2", {"b": 3})
    assert out.passed is False and out.missing == (("obj", "a"),)
    out = evaluate_rule_strict("ASSERT obj.a = 1 OR obj.b = 2", {"b": 3})
    assert out.passed is None and out.missing == (("obj", "a"),)


def test_an_or_with_a_present_true_side_passes_without_the_absent_operand(db_session):
    mgr = AuthorityResolutionManager()
    _ar(mgr, db_session, slug="or-region", rule={"permission": {"constraint": [{"or": [
        {"leftOperand": "arf:region", "operator": "eq", "rightOperand": "EU"},
        {"leftOperand": "arf:cosignPresent", "operator": "eq", "rightOperand": True},
    ]}]}})
    assert _resolve(mgr, db_session, "or-region", {"cosign_present": True})["verdict"] == VERDICT_APPROVED
    out = _resolve(mgr, db_session, "or-region", {"cosign_present": False})
    assert (out["verdict"], out["reason_code"]) == (VERDICT_DENIED, REASON_MISSING_OPERAND)
    assert "'region'" in out["reason"]


def test_a_prohibition_on_an_absent_operand_denies_and_names_the_field(db_session):
    """Deliberate deviation from ODRL (documented in authority_rule): an undecidable prohibition denies."""
    mgr = AuthorityResolutionManager()
    _ar(mgr, db_session, slug="no-ru", rule={"prohibition": [{
        "message": "No sales into RU.",
        "constraint": [{"leftOperand": "arf:market", "operator": "eq", "rightOperand": "RU"}],
    }]})
    out = _resolve(mgr, db_session, "no-ru", {"value": 1})
    assert (out["verdict"], out["reason_code"]) == (VERDICT_DENIED, REASON_MISSING_OPERAND)
    assert "'market'" in out["reason"]
    assert _resolve(mgr, db_session, "no-ru", {"market": "DE"})["verdict"] == VERDICT_APPROVED


def test_a_duty_on_an_absent_operand_stays_unfulfilled(db_session):
    mgr = AuthorityResolutionManager()
    _ar(mgr, db_session, slug="duty-market", rule={"permission": {"duty": [{
        "action": "arf:obtainCoApproval",
        "constraint": [{"leftOperand": "arf:market", "operator": "eq", "rightOperand": "DE"}],
    }]}})
    assert _resolve(mgr, db_session, "duty-market", {"value": 1})["verdict"] == VERDICT_CONDITIONAL
    assert _resolve(mgr, db_session, "duty-market", {"market": "DE"})["verdict"] == VERDICT_APPROVED


def test_boolean_set_members_keep_the_boolean(db_session):
    mgr = AuthorityResolutionManager()
    _ar(mgr, db_session, slug="esc-any", rule={"permission": {"constraint": [
        {"leftOperand": "arf:escalated", "operator": "isAnyOf", "rightOperand": [True]}]}})
    _ar(mgr, db_session, slug="esc-none", rule={"permission": {"constraint": [
        {"leftOperand": "arf:escalated", "operator": "isNoneOf", "rightOperand": [True]}]}})
    assert _resolve(mgr, db_session, "esc-any", {"escalated": True})["verdict"] == VERDICT_APPROVED
    assert _resolve(mgr, db_session, "esc-any", {"escalated": False})["verdict"] == VERDICT_DENIED
    assert _resolve(mgr, db_session, "esc-none", {"escalated": True})["verdict"] == VERDICT_DENIED
    assert _resolve(mgr, db_session, "esc-none", {"escalated": False})["verdict"] == VERDICT_APPROVED


def test_equality_with_a_number_matches_the_same_text(db_session):
    mgr = AuthorityResolutionManager()
    _ar(mgr, db_session, slug="obj-eq", rule={"permission": {"constraint": [
        {"leftOperand": "arf:objectId", "operator": "eq", "rightOperand": 1234}]}})
    _ar(mgr, db_session, slug="obj-neq", rule={"permission": {"constraint": [
        {"leftOperand": "arf:objectId", "operator": "neq", "rightOperand": 1234}]}})
    assert _resolve(mgr, db_session, "obj-eq", {"object_id": "1234"})["verdict"] == VERDICT_APPROVED
    assert _resolve(mgr, db_session, "obj-eq", {"object_id": "9999"})["verdict"] == VERDICT_DENIED
    assert _resolve(mgr, db_session, "obj-neq", {"object_id": "1234"})["verdict"] == VERDICT_DENIED
    assert _resolve(mgr, db_session, "obj-neq", {"object_id": "9999"})["verdict"] == VERDICT_APPROVED


def test_criteria_validate_route_is_strict_like_resolve():
    from src.routes.authority_resolution_routes import validate_criterion
    out = asyncio.run(validate_criterion(None, {
        "rule": "obj.grantee != obj.actor_identity", "object": {"actor_identity": "a"}}, True))
    assert out["passed"] is False and "'grantee'" in out["message"]
    out = asyncio.run(validate_criterion(None, {
        "rule": "obj.grantee != obj.actor_identity", "object": {"actor_identity": "a", "grantee": "b"}}, True))
    assert out["passed"] is True


def test_dna_skips_a_row_without_a_checked_operand(db_session):
    mgr = AuthorityResolutionManager()
    rel = _ar(mgr, db_session, slug="dna-skip", rule={"prohibition": [{
        "message": "self", "constraint": [{"leftOperand": "arf:grantee", "operator": "eq",
                                           "rightOperandReference": "req.actor_identity"}]}]})
    rows = [{"actor_identity": "a"},                       # no grantee: not measured
            {"actor_identity": "a", "grantee": "a"},       # self-grant: divergent
            {"actor_identity": "a", "grantee": "b"}]       # clean
    run = mgr.compute_dnaco(db_session, rel.id, rows=rows)
    assert run.status == "succeeded"
    assert (run.sampled_count, run.divergent_count) == (2, 1)


def test_dna_fails_the_run_when_a_checked_parameter_is_absent(db_session):
    mgr = AuthorityResolutionManager()
    rel = _ar(mgr, db_session, slug="dna-cfg", params={"cap": 10}, rule={"permission": {"constraint": [
        {"leftOperand": "payAmount", "operator": "lteq", "rightOperandReference": "ctx.cap"}]}})
    db_session.commit()
    rel.domain_context = {"scope": [], "params": {}}
    db_session.commit()
    with pytest.raises(AuthorityInvalidError, match=r"ctx\.cap") as exc:
        mgr.compute_dnaco(db_session, rel.id, rows=[{"value": 1}])
    assert exc.value.params == {"parameters": ["cap"]}


def test_dna_reads_a_domain_context_ref_as_a_parameter(db_session):
    mgr = AuthorityResolutionManager()
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(
        name="AR dna-ref", slug="dna-ref",
        rule={"permission": {"constraint": [
            {"leftOperand": "arf:market", "operator": "eq", "rightOperandReference": "ctx.home"}]}},
        criteria=[], resource_refs=[ResourceRefInput(field_path="domain_context.home",
                                                     ref_type="literal", literal_value="DE")],
    ))
    db_session.commit()
    run = mgr.compute_dnaco(db_session, rel.id, rows=[{"market": "DE"}, {"market": "FR"}])
    assert (run.sampled_count, run.divergent_count) == (2, 1)


def test_a_check_weight_that_is_a_bool_is_refused_on_save(db_session):
    mgr = AuthorityResolutionManager()
    with pytest.raises(ValueError, match="boolean"):
        _ar(mgr, db_session, slug="bool-check", criteria=[
            {"name": "Limit", "rule": "ASSERT TRUE", "weight": True}])


def test_ref_param_key_strips_and_reads_one_segment():
    assert arule.ref_param_key(" domain_context.params. cap ") == "cap"
    assert arule.ref_param_key("domain_context.cap") == "cap"
    assert arule.ref_param_key("domain_context.a.b") is None
    assert arule.ref_param_key("object_id") is None


def test_a_metadata_edit_does_not_recheck_the_parameters(db_session):
    mgr = AuthorityResolutionManager()
    rel = _ar(mgr, db_session, slug="meta-only", params={"cap": 1}, rule={"prohibition": [{
        "constraint": [{"leftOperand": "payAmount", "operator": "gteq", "rightOperandReference": "ctx.cap"}]}]})
    db_session.commit()
    rel.domain_context = {"scope": [], "params": {}}    # stored state already inconsistent
    db_session.commit()
    mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(description="words only"))
    with pytest.raises(arule.UnknownParameterError):
        mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(rule={"prohibition": [{
            "constraint": [{"leftOperand": "payAmount", "operator": "gt", "rightOperandReference": "ctx.cap"}]}]}))


def test_a_save_computes_the_check_rows_once(db_session, monkeypatch):
    mgr = AuthorityResolutionManager()
    rel = _ar(mgr, db_session, slug="rows-once", rule={"permission": {"constraint": [
        {"leftOperand": "payAmount", "operator": "lteq", "rightOperand": 5}]}},
        criteria=[{"name": "Limit", "rule": "ASSERT obj.value <= 9"}])
    db_session.commit()
    calls = []
    original = mgr._criteria_rows

    def counting(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(mgr, "_criteria_rows", counting)
    mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(criteria=[
        CriterionInput(name="Limit", rule="ASSERT obj.value <= 7")]))
    assert len(calls) == 1


def test_concept_suggestion_reads_the_canonical_field_of_a_typed_scope(db_session):
    from src.db_models.semantic_links import EntitySemanticLinkDb
    import uuid
    mgr = AuthorityResolutionManager()
    rel = _ar(mgr, db_session, slug="actor-scoped",
              scope=[{"leftOperand": "arf:actor", "operator": "eq", "rightOperand": "alice"}],
              rule={"permission": {"constraint": [{"leftOperand": "payAmount", "operator": "lteq", "rightOperand": 5}]}})
    rel.status = "active"
    db_session.add(EntitySemanticLinkDb(id=uuid.uuid4(), entity_id=rel.id, entity_type="authority_relation",
                                        iri="urn:c", label="c"))
    db_session.commit()
    matched = mgr.find_authority_for_concept(db_session, "urn:c", {"actor_identity": "alice"})
    assert matched["candidates"][0]["context_matches"] == ["actor_identity"]
    clash = mgr.find_authority_for_concept(db_session, "urn:c", {"actor_identity": "bob"})
    assert clash["candidates"][0]["context_conflicts"] == ["actor_identity"]


def test_unknown_parameter_in_a_prohibition_is_refused_on_save(db_session):
    mgr = AuthorityResolutionManager()
    with pytest.raises(arule.UnknownParameterError) as exc:
        _ar(mgr, db_session, slug="unknown-ctx", params={"threshold": 1}, rule={"prohibition": [{
            "constraint": [{"leftOperand": "payAmount", "operator": "gteq", "rightOperandReference": "ctx.cap"}],
        }]})
    assert exc.value.code == "authority_unknown_parameter"
    assert exc.value.params == {"parameters": ["cap"]}
    db_session.rollback()


def test_unknown_parameter_in_a_check_is_refused_on_save(db_session):
    mgr = AuthorityResolutionManager()
    with pytest.raises(arule.UnknownParameterError) as exc:
        _ar(mgr, db_session, slug="unknown-check", params={},
            criteria=[{"name": "Limit", "rule": "ASSERT obj.value <= ctx.limit AND obj.value >= ctx.floor"}])
    assert exc.value.params == {"parameters": ["floor", "limit"]}
    db_session.rollback()


def test_a_string_literal_is_not_a_parameter_reference():
    assert arule.context_references(["ASSERT obj.note = 'see ctx.cap'"]) == set()


# ------------------------------------------------------------- 1491-2: scope operands

def test_a_scope_on_a_typed_field_reads_the_canonical_field(db_session):
    """Probe: scope ``arf:objectId`` read a caller's ``objectId`` and admitted an object outside it."""
    mgr = AuthorityResolutionManager()
    _ar(mgr, db_session, slug="scoped-object",
        scope=[{"leftOperand": "arf:objectId", "operator": "eq", "rightOperand": "obj-allowed"}],
        rule={"permission": {"constraint": [{"leftOperand": "payAmount", "operator": "lteq", "rightOperand": 1000}]}})
    out = _resolve(mgr, db_session, "scoped-object", {"object_id": "obj-outside", "objectId": "obj-allowed", "value": 1})
    assert (out["verdict"], out["reason"]) == (VERDICT_NO_AUTHORITY, "out of scope: object_id=obj-outside")
    assert _resolve(mgr, db_session, "scoped-object", {"object_id": "obj-allowed", "value": 1})["verdict"] == VERDICT_APPROVED


def test_scope_key_maps_typed_fields_to_their_canonical_request_field():
    assert arule.scope_key("arf:actor") == "actor_identity"
    assert arule.scope_key("payAmount") == "value"
    assert arule.scope_key("arf:market") == "market"
    assert arule.scope_key("spatial") == "spatial"


# ------------------------------------------------------------- 1491-4: numeric strings

def test_is_any_of_a_numeric_string_matches_the_same_text(db_session):
    """Probe: ``isAnyOf ['1234']`` missed a request value '1234' (held as a number)."""
    mgr = AuthorityResolutionManager()
    _ar(mgr, db_session, slug="numeric-set", rule={"permission": {"constraint": [
        {"leftOperand": "arf:code", "operator": "isAnyOf", "rightOperand": ["1234"]},
    ]}})
    assert _resolve(mgr, db_session, "numeric-set", {"code": "1234"})["verdict"] == VERDICT_APPROVED
    assert _resolve(mgr, db_session, "numeric-set", {"code": "9999"})["verdict"] == VERDICT_DENIED


def test_equality_with_a_numeric_string_matches_the_number_too(db_session):
    mgr = AuthorityResolutionManager()
    _ar(mgr, db_session, slug="numeric-eq", rule={"permission": {"constraint": [
        {"leftOperand": "arf:code", "operator": "eq", "rightOperand": "1234"},
    ]}})
    assert _resolve(mgr, db_session, "numeric-eq", {"code": "1234"})["verdict"] == VERDICT_APPROVED
    assert _resolve(mgr, db_session, "numeric-eq", {"code": "1235"})["verdict"] == VERDICT_DENIED


# ------------------------------------------------------------- 1491-5: weights

@pytest.mark.parametrize("weight", ["heavy", -1, float("nan"), True])
def test_a_bad_weight_is_refused_on_save(db_session, weight):
    mgr = AuthorityResolutionManager()
    with pytest.raises(arule.RuleInvalidError, match="weight"):
        _ar(mgr, db_session, slug="bad-weight", rule={"permission": {"constraint": [
            {"leftOperand": "payAmount", "operator": "lteq", "rightOperand": 5, "weight": weight},
        ]}})
    db_session.rollback()


def test_a_zero_weight_is_kept(db_session):
    mgr = AuthorityResolutionManager()
    rel = _ar(mgr, db_session, slug="zero-weight", rule={"permission": {"constraint": [
        {"leftOperand": "payAmount", "operator": "lteq", "rightOperand": 5, "weight": 0},
    ]}})
    assert rel.rule["permission"]["constraint"][0]["weight"] == 0.0


# ------------------------------------------------------------- 1491-6: coded rule/validate

def test_rule_validate_answers_the_coded_shape_not_english():
    from src.routes.authority_resolution_routes import validate_rule
    payload = {"rule": {"permission": {"constraint": [
        {"leftOperand": "payAmount", "operator": "lteq", "rightOperand": 5, "weight": "heavy"},
    ]}}}
    with pytest.raises(HTTPException) as bad:
        asyncio.run(validate_rule(None, payload, True))
    assert bad.value.status_code == 400
    response = asyncio.run(coded_http_exception_handler(None, bad.value))
    body = json.loads(response.body)
    assert body["detail"]["code"] == "authority_invalid"
    assert "weight" in body["detail"]["message"]
    assert body["detail"]["params"] == {}
