"""Batch 2 merged with ARF slice 1 (scoped domain context and ODRL rule): the definition hash covers
the scope, params and rule; the threshold template reads a parameter; rule constraints are not
written as check rows."""
from src.controller.authority_resolution_manager import (
    AuthorityImmutableError,
    AuthorityResolutionManager,
    STATUS_ACTIVE,
    VERDICT_APPROVED,
    VERDICT_CONFLICT,
    VERDICT_DENIED,
)
import pytest

from src.common.authority_rule import UnknownParameterError
from src.db_models.authority_resolution import AuthorityCriterionDb
from src.models.authority_resolution import (
    AffirmationInput,
    AuthorityRelationCreate,
    AuthorityRelationUpdate,
    CriterionInput,
    EvidenceSource,
)

MARKET_DE = [{"leftOperand": "arf:market", "operator": "eq", "rightOperand": "DE"}]
CEILING = {"leftOperand": "payAmount", "operator": "lteq", "rightOperandReference": "ctx.threshold",
           "name": "Pay ceiling", "message": "Above the pay ceiling."}
RULE = {"permission": {"constraint": [CEILING], "duty": []}, "prohibition": []}


def _complete(mgr, db, slug, *, scope=MARKET_DE, rule=RULE, params=None, criteria=None):
    rel = mgr.create_relation(db, AuthorityRelationCreate(
        name=f"Merge {slug}", slug=slug, object_id="dp-1",
        justification_chain={"policy_id": "p"},
        evidence_sources=[EvidenceSource(type="delta_table", ref="c.s.t", column_map={"actor_identity": "a"})],
        domain_context={"scope": scope, "params": params if params is not None else {"threshold": 100}},
        rule=rule,
        criteria=criteria if criteria is not None else [CriterionInput(name="Not blocked", rule="ASSERT TRUE")],
        affirmations=[AffirmationInput(role="Approver", principal="approver@x.com")],
    ), current_user="author@x.com", caller_is_admin=True)
    db.commit()
    return rel


def test_a_scope_change_on_an_active_ar_is_refused_with_409(db_session):
    mgr = AuthorityResolutionManager()
    rel = _complete(mgr, db_session, "m-scope")
    rel.status = STATUS_ACTIVE
    db_session.commit()
    try:
        mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(
            domain_context={"scope": [{"leftOperand": "arf:market", "operator": "eq", "rightOperand": "FR"}]}))
        raised = None
    except AuthorityImmutableError as e:
        raised = e
    assert raised is not None and raised.http_status == 409


def test_a_rule_re_sent_unchanged_hashes_the_same(db_session):
    mgr = AuthorityResolutionManager()
    rel = _complete(mgr, db_session, "m-same")
    before = mgr.definition_hash(db_session, rel)
    # The editor re-sends the rule with its defaults filled in, and the same scope.
    resent = {"permission": {"constraint": [dict(CEILING)], "duty": []}, "prohibition": []}
    mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(
        rule=resent, domain_context={"scope": MARKET_DE, "params": {"threshold": 100}}))
    db_session.commit()
    assert mgr.definition_hash(db_session, rel) == before


def test_a_draft_rule_change_resets_the_measurement_and_stales_the_affirmations(db_session):
    mgr = AuthorityResolutionManager()
    rel = _complete(mgr, db_session, "m-draft")
    aff = mgr.to_read_dict(db_session, rel)["affirmations"][0]
    mgr.affirm(db_session, aff["id"], affirmed_by="approver@x.com", user=type("U", (), {
        "email": "approver@x.com", "username": "approver@x.com", "user": "approver@x.com", "groups": []})())
    mgr.compute_dnaco(db_session, rel.id, rows=[{"actor_identity": "a", "value": 1}])
    db_session.commit()
    assert mgr.is_fully_affirmed(db_session, rel.id)

    changed = {"permission": {"constraint": [dict(CEILING, rightOperandReference="ctx.threshold")], "duty": []},
               "prohibition": [{"name": "Blocked", "message": "No.",
                                "constraint": [{"leftOperand": "actor_identity", "operator": "isAnyOf",
                                                "rightOperand": ["x"]}]}]}
    mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(rule=changed))
    db_session.commit()
    fresh = mgr.get_relation(db_session, rel.id)
    assert fresh.dna_magnitude is None
    assert not mgr.is_fully_affirmed(db_session, rel.id)


def test_the_threshold_template_reads_the_ar_parameter_and_fails_closed(db_session):
    mgr = AuthorityResolutionManager()
    rel = _complete(mgr, db_session, "m-tpl", scope=[], rule=None, params={"threshold": 100},
                    criteria=[CriterionInput(template_key="amount_within_threshold")])
    rel.status = STATUS_ACTIVE
    db_session.commit()
    ok = mgr.resolve(db_session, rel.id, {"value": 50}, record=False, require_active=False)
    assert ok["verdict"] == VERDICT_APPROVED
    over = mgr.resolve(db_session, rel.id, {"value": 150}, record=False, require_active=False)
    assert over["verdict"] == VERDICT_DENIED and "threshold" in over["reason"]

    # A template that reads ctx.threshold can't be saved without the parameter (#1491-1).
    with pytest.raises(UnknownParameterError, match=r"ctx\.threshold"):
        _complete(mgr, db_session, "m-tpl-none", scope=[], rule=None, params={},
                  criteria=[CriterionInput(template_key="amount_within_threshold")])
    db_session.rollback()

    # If the parameter is gone from the stored context anyway, the check is undecidable: a conflict.
    stale = _complete(mgr, db_session, "m-tpl-stale", scope=[], rule=None, params={"threshold": 100},
                      criteria=[CriterionInput(template_key="amount_within_threshold")])
    stale.status = STATUS_ACTIVE
    stale.domain_context = {"scope": [], "params": {}}
    db_session.commit()
    out = mgr.resolve(db_session, stale.id, {"value": 1}, record=False, require_active=False)
    assert (out["verdict"], out["reason_code"]) == (VERDICT_CONFLICT, "missing_parameter")
    assert "'threshold'" in out["reason"]


def test_rule_constraints_are_not_written_as_check_rows(db_session):
    mgr = AuthorityResolutionManager()
    before = db_session.query(AuthorityCriterionDb).count()
    rel = _complete(mgr, db_session, "m-rule-only", criteria=[])
    # A rule with no checks is a gate of its own: the constraint is compiled at evaluation,
    # never stored as an authority_criteria row.
    assert db_session.query(AuthorityCriterionDb).count() == before
    assert rel.rule is not None
    out = mgr.resolve(db_session, rel.id, {"market": "DE", "value": 1000, "payAmount": 1000},
                      record=False, require_active=False)
    assert out["verdict"] == VERDICT_DENIED


def test_the_cited_policy_and_its_clauses_are_part_of_the_hash():
    """Approvers vouch against the cited document: changing the citation changes the definition."""
    from src.common import authority_definition as d

    def view(policy="p1", refs=("§7.1",), clause="§7.2"):
        return d.definition_view(
            {"authority_policy_id": policy, "policy_clause_refs": list(refs)},
            [{"name": "c", "rule": "ASSERT obj.value > 0", "failure_message": None, "direction": "neutral",
              "weight": 1.0, "dimension": "people", "display_order": 0, "enabled": True,
              "policy_clause_ref": clause}],
        )
    base = d.definition_hash(view())
    assert d.definition_hash(view(policy="p2")) != base
    assert d.definition_hash(view(refs=("§7.2",))) != base
    assert d.definition_hash(view(clause="§9.9")) != base
    assert d.definition_hash(view()) == base
