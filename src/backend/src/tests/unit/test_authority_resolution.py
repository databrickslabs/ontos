"""Unit tests for the Authority Resolution feature (ARF).

Covers the pure pieces — the criteria-driven DNA-Coefficient engine and the
deterministic runtime gate — plus the DB-backed configurable-criteria path
(inline Compliance Checks driving both the gate and divergence) and the shared
Maturity Level integration.
"""
from src.common.authority_resolution_dna import (
    Criterion,
    compute_dnaco,
    evaluate_row,
    maturity_level,
    DIR_ACTUAL_EXCEEDS,
    DIR_DOCUMENTED_EXCEEDS,
    DIR_NEUTRAL,
    DIR_NONE,
)
from src.controller.authority_resolution_manager import (
    AuthorityResolutionManager,
    VERDICT_APPROVED,
    VERDICT_DENIED,
)
from src.db_models.authority_resolution import AuthorityRelationDb, AuthorityCriterionDb
from src.db_models.compliance import CompliancePolicyDb


# --------------------------------------------------------------- helpers

def _crit(rule, *, direction=DIR_NEUTRAL, weight=1.0, message=None, order=0,
          enabled=True, name="crit") -> Criterion:
    """A pure engine Criterion (rule already includes ASSERT)."""
    return Criterion(code=name, rule=rule, direction=direction, weight=weight, message=message)


# canonical criteria mirroring the trade-promotion worked example
ALLOWLIST = _crit("ASSERT obj.actor_identity IN ['rsm-east']",
                  direction=DIR_ACTUAL_EXCEEDS, name="approver_mismatch")
THRESHOLD = _crit("ASSERT obj.value <= 0.15 OR obj.escalated = True",
                  direction=DIR_ACTUAL_EXCEEDS, name="threshold_breach_without_escalation")
COSIGN = _crit("ASSERT obj.cosign_present = True",
               direction=DIR_DOCUMENTED_EXCEEDS, name="missing_cosign")


# --------------------------------------------------------------- DNAco engine

def test_clean_evidence_scores_zero():
    rows = [
        {"actor_identity": "rsm-east", "value": 0.10, "escalated": False},
        {"actor_identity": "rsm-east", "value": 0.12, "escalated": False},
    ]
    result = compute_dnaco([ALLOWLIST, THRESHOLD], rows)
    assert result.magnitude == 0.0
    assert result.direction == DIR_NONE
    assert result.divergent_count == 0


def test_threshold_breach_without_escalation_is_actual_exceeds():
    rows = [
        {"actor_identity": "rsm-east", "value": 0.22, "escalated": False},   # breach
        {"actor_identity": "rsm-east", "value": 0.10, "escalated": False},   # clean
    ]
    result = compute_dnaco([THRESHOLD], rows)
    assert result.divergent_count == 1
    assert result.magnitude == 0.5
    assert result.direction == DIR_ACTUAL_EXCEEDS


def test_escalated_breach_is_clean():
    rows = [{"actor_identity": "rsm-east", "value": 0.22, "escalated": True}]
    result = compute_dnaco([THRESHOLD], rows)
    assert result.divergent_count == 0
    assert result.magnitude == 0.0


def test_missing_cosign_is_documented_exceeds():
    rows = [
        {"actor_identity": "rsm-east", "value": 0.10, "cosign_present": False},  # missing co-sign
        {"actor_identity": "rsm-east", "value": 0.10, "cosign_present": True},   # clean
    ]
    result = compute_dnaco([COSIGN], rows)
    assert result.divergent_count == 1
    assert result.direction == DIR_DOCUMENTED_EXCEEDS


def test_approver_mismatch_flags_divergence():
    rd = evaluate_row([ALLOWLIST], {"actor_identity": "someone-else"})
    assert rd.diverged
    assert "approver_mismatch" in rd.reasons


def test_criterion_weights_raise_magnitude():
    rows = [
        {"actor_identity": "rsm-east", "value": 0.22, "escalated": False},
        {"actor_identity": "rsm-east", "value": 0.10, "escalated": False},
        {"actor_identity": "rsm-east", "value": 0.10, "escalated": False},
        {"actor_identity": "rsm-east", "value": 0.10, "escalated": False},
    ]
    # Default weight: 1 of 4 diverges -> 0.25
    assert compute_dnaco([THRESHOLD], rows).magnitude == 0.25
    # Weighted: the breach counts triple, capped at 1.0 -> 0.75
    weighted = _crit(THRESHOLD.rule, direction=DIR_ACTUAL_EXCEEDS, weight=3.0, name="threshold")
    assert compute_dnaco([weighted], rows).magnitude == 0.75


def test_percent_string_and_bool_string_coerce():
    rows = [{"actor_identity": "rsm-east", "value": "22%", "escalated": "false"}]
    result = compute_dnaco([THRESHOLD], rows)
    assert result.divergent_count == 1


def test_no_criteria_scores_zero():
    rows = [{"actor_identity": "whoever", "value": 9.9, "escalated": False}]
    result = compute_dnaco([], rows)
    assert result.magnitude == 0.0
    assert result.divergent_count == 0


# ---------------------------------------------------- deterministic gate

def _relation(*criteria: AuthorityCriterionDb) -> AuthorityRelationDb:
    return AuthorityRelationDb(id="ar-1", name="Test AR", status="active", version=1,
                              criteria=list(criteria))


def _link(rule, *, direction=DIR_NEUTRAL, weight=1.0, message=None, order=0,
          enabled=True, name="crit") -> AuthorityCriterionDb:
    return AuthorityCriterionDb(
        id=f"crit-{order}", relation_id="ar-1",
        compliance_policy=CompliancePolicyDb(
            id=f"pol-{order}", name=name, rule=rule, failure_message=message, is_active=True,
        ),
        direction=direction, weight=weight, display_order=order, enabled=enabled,
    )


def test_gate_approves_when_all_criteria_pass():
    mgr = AuthorityResolutionManager()
    rel = _relation(
        _link("ASSERT obj.actor_identity IN ['rsm-east']", order=0),
        _link("ASSERT obj.value <= 0.15 OR obj.escalated = True", order=1),
    )
    verdict, _ = mgr._evaluate_decision(rel, {"actor_identity": "rsm-east", "value": 0.10})
    assert verdict == VERDICT_APPROVED


def test_gate_denies_unauthorized_signer_with_message():
    mgr = AuthorityResolutionManager()
    rel = _relation(_link("ASSERT obj.actor_identity IN ['rsm-east']",
                          message="Signer is not an authorized RSM.", order=0))
    verdict, reason = mgr._evaluate_decision(rel, {"actor_identity": "intruder"})
    assert verdict == VERDICT_DENIED
    assert reason == "Signer is not an authorized RSM."


def test_gate_denies_over_threshold_without_escalation():
    mgr = AuthorityResolutionManager()
    rel = _relation(_link("ASSERT obj.value <= 0.15 OR obj.escalated = True", order=0))
    verdict, _ = mgr._evaluate_decision(rel, {"value": 0.30, "escalated": False})
    assert verdict == VERDICT_DENIED


def test_gate_allows_over_threshold_with_escalation():
    mgr = AuthorityResolutionManager()
    rel = _relation(_link("ASSERT obj.value <= 0.15 OR obj.escalated = True", order=0))
    verdict, _ = mgr._evaluate_decision(rel, {"value": 0.30, "escalated": True})
    assert verdict == VERDICT_APPROVED


def test_gate_denies_missing_cosign():
    mgr = AuthorityResolutionManager()
    rel = _relation(_link("ASSERT obj.cosign_present = True", order=0))
    verdict, _ = mgr._evaluate_decision(rel, {"cosign_present": False})
    assert verdict == VERDICT_DENIED


def test_gate_denies_action_mismatch():
    mgr = AuthorityResolutionManager()
    rel = _relation(_link("ASSERT obj.action = 'approve'", order=0))
    verdict, _ = mgr._evaluate_decision(rel, {"action": "override"})
    assert verdict == VERDICT_DENIED


def test_gate_disabled_criterion_is_skipped():
    mgr = AuthorityResolutionManager()
    rel = _relation(_link("ASSERT obj.actor_identity IN ['rsm-east']", enabled=False, order=0))
    verdict, _ = mgr._evaluate_decision(rel, {"actor_identity": "intruder"})
    assert verdict == VERDICT_APPROVED


def test_gate_no_criteria_approves():
    mgr = AuthorityResolutionManager()
    verdict, _ = mgr._evaluate_decision(_relation(), {"actor_identity": "anyone"})
    assert verdict == VERDICT_APPROVED


# ------------------------------------------------------------- maturity

def test_maturity_levels():
    assert maturity_level(has_object=False, dna_measured=False, fully_affirmed=False) == "L1"
    assert maturity_level(has_object=True, dna_measured=False, fully_affirmed=False) == "L2"
    assert maturity_level(has_object=True, dna_measured=True, fully_affirmed=False) == "L3"
    assert maturity_level(has_object=True, dna_measured=True, fully_affirmed=True) == "L4"


# ---------------------------------- configurable criteria (DB-backed, end to end)

def test_configurable_criteria_gate_and_divergence(db_session):
    """Inline-authored criteria create Compliance Checks, drive the runtime gate,
    and produce signed/weighted DNAco divergence — one definition, both engines."""
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.models.authority_resolution import AuthorityRelationCreate, CriterionInput

    mgr = AuthorityResolutionManager()
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(
        name="Trade promo approval",
        criteria=[
            CriterionInput(name="Authorized RSM", rule="obj.actor_identity IN ['rsm-east']",
                           failure_message="Signer is not an authorized RSM.",
                           direction=DIR_ACTUAL_EXCEEDS, weight=1.0, order=0),
            CriterionInput(name="Within discount cap",
                           rule="obj.value <= 0.15 OR obj.escalated = True",
                           failure_message="Discount exceeds 15% without escalation.",
                           direction=DIR_ACTUAL_EXCEEDS, weight=1.5, order=1),
        ],
    ))
    db_session.commit()

    # Inline criteria created Compliance Checks (category tagged), linked to the AR.
    assert len(rel.criteria) == 2
    cats = {c.compliance_policy.category for c in rel.criteria}
    assert cats == {"Authority Decision"}
    # The ASSERT keyword is prepended when the author omits it.
    assert all(c.compliance_policy.rule.upper().startswith("ASSERT") for c in rel.criteria)

    # Gate (dry-run, any status): good request approved, bad request denied w/ message.
    ok = mgr.resolve(db_session, rel.id, {"actor_identity": "rsm-east", "value": 0.10},
                     record=False, require_active=False)
    assert ok["verdict"] == VERDICT_APPROVED
    bad = mgr.resolve(db_session, rel.id, {"actor_identity": "intruder", "value": 0.10},
                      record=False, require_active=False)
    assert bad["verdict"] == VERDICT_DENIED
    assert bad["reason"] == "Signer is not an authorized RSM."

    # Divergence over an evidence sample: 1 of 2 rows breaches the cap (weight 1.5).
    run = mgr.compute_dnaco(db_session, rel.id, rows=[
        {"actor_identity": "rsm-east", "value": 0.22, "escalated": False},   # over cap
        {"actor_identity": "rsm-east", "value": 0.10, "escalated": False},   # clean
    ])
    db_session.commit()
    assert run.divergent_count == 1
    assert run.direction == DIR_ACTUAL_EXCEEDS
    assert run.magnitude == 0.75   # 1.5 / 2 rows


def test_authority_maturity_feature_integration(db_session):
    """The ARF ladder is seeded as entity_type-specific levels, overrides the
    generic "all" set, and the compliance-gated evaluator advances an AR through
    the levels as it gains an object / evidence+DNA / affirmation."""
    from src.repositories.maturity_repository import maturity_repo
    from src.controller.maturity_evaluator import MaturityEvaluator
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.models.authority_resolution import (
        AuthorityRelationCreate, EvidenceSource,
    )

    # Seed the generic "all" model AND the ARF-specific ladder.
    maturity_repo.seed_defaults(db_session)
    maturity_repo.seed_authority_defaults(db_session)
    db_session.commit()

    ar_levels = maturity_repo.get_all_ordered(db_session, entity_type="AuthorityRelation")
    # Specific overrides generic: only the 4 ARF levels, none of the "all" set.
    assert [l.name for l in ar_levels] == [
        "Documented", "Object-Resolved", "DNA-Measured", "N-Functionally-Affirmed",
    ]
    assert all(l.entity_type == "AuthorityRelation" for l in ar_levels)

    mgr = AuthorityResolutionManager()
    evaluator = MaturityEvaluator()

    # (1) name only -> L1 Documented (no object stops the ladder).
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(name="AR"))
    db_session.commit()
    rep = evaluator.evaluate(db_session, entity_type="AuthorityRelation", entity_id=rel.id, persist=False)
    assert rep.achieved_level_order == 1

    # (2) add an object -> L2 Object-Resolved (no evidence/DNA stops it there).
    rel2 = mgr.create_relation(db_session, AuthorityRelationCreate(
        name="AR2", object_id="dp-1",
        evidence_sources=[EvidenceSource(type="delta_table", ref="c.s.t", column_map={"actor_identity": "a"})],
    ))
    db_session.commit()
    mgr.compute_dnaco(db_session, rel2.id, rows=[])  # measured (empty sample -> magnitude 0.0)
    db_session.commit()
    rep2 = evaluator.evaluate(db_session, entity_type="AuthorityRelation", entity_id=rel2.id, persist=False)
    # object + evidence + measured + within ceiling, but not affirmed -> L3 DNA-Measured
    assert rep2.achieved_level_order == 3
