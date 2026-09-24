"""Unit tests for the Authority Resolution feature (ARF).

Covers the pure pieces — the DNA-Coefficient engine and the deterministic
runtime decision evaluation — without a DB or a warehouse. The full manager /
route / MCP integration is exercised separately with the DB fixtures.
"""
from src.common.authority_resolution_dna import (
    ARSpec,
    compute_dnaco,
    evaluate_row,
    maturity_level,
    DIR_ACTUAL_EXCEEDS,
    DIR_DOCUMENTED_EXCEEDS,
    DIR_NONE,
)
from src.controller.authority_resolution_manager import (
    AuthorityResolutionManager,
    VERDICT_APPROVED,
    VERDICT_DENIED,
)
from src.db_models.authority_resolution import AuthorityRelationDb


COLUMN_MAP = {
    "actual_approver": "approver",
    "documented_approver": "documented",
    "value": "discount",
    "escalated": "escalated",
    "cosign_present": "cosign",
    "action": "action",
    "object_id": "promo_id",
}


# --------------------------------------------------------------- DNAco engine

def test_clean_evidence_scores_zero():
    spec = ARSpec(documented_approver="rsm-east", threshold=0.15)
    rows = [
        {"approver": "rsm-east", "discount": 0.10, "escalated": False},
        {"approver": "rsm-east", "discount": 0.12, "escalated": False},
    ]
    result = compute_dnaco(spec, rows, COLUMN_MAP)
    assert result.magnitude == 0.0
    assert result.direction == DIR_NONE
    assert result.divergent_count == 0


def test_threshold_breach_without_escalation_is_actual_exceeds():
    spec = ARSpec(documented_approver="rsm-east", threshold=0.15)
    rows = [
        {"approver": "rsm-east", "discount": 0.22, "escalated": False},   # breach, no escalation
        {"approver": "rsm-east", "discount": 0.10, "escalated": False},   # clean
    ]
    result = compute_dnaco(spec, rows, COLUMN_MAP)
    assert result.divergent_count == 1
    assert result.magnitude == 0.5
    assert result.direction == DIR_ACTUAL_EXCEEDS


def test_escalated_breach_is_clean():
    spec = ARSpec(documented_approver="rsm-east", threshold=0.15)
    rows = [{"approver": "rsm-east", "discount": 0.22, "escalated": True}]
    result = compute_dnaco(spec, rows, COLUMN_MAP)
    assert result.divergent_count == 0
    assert result.magnitude == 0.0


def test_missing_cosign_is_documented_exceeds():
    spec = ARSpec(documented_approver="rsm-east", threshold=0.15, required_cosign=True)
    rows = [
        {"approver": "rsm-east", "discount": 0.10, "cosign": False},   # missing required co-sign
        {"approver": "rsm-east", "discount": 0.10, "cosign": True},    # clean
    ]
    result = compute_dnaco(spec, rows, COLUMN_MAP)
    assert result.divergent_count == 1
    assert result.direction == DIR_DOCUMENTED_EXCEEDS


def test_approver_mismatch_flags_divergence():
    spec = ARSpec(documented_approver="rsm-east")
    row = {"approver": "someone-else"}
    rd = evaluate_row(spec, row, COLUMN_MAP)
    assert rd.diverged
    assert "approver_mismatch" in rd.reasons


def test_reason_weights_raise_magnitude():
    spec = ARSpec(documented_approver="rsm-east", threshold=0.15)
    rows = [
        {"approver": "rsm-east", "discount": 0.22, "escalated": False},
        {"approver": "rsm-east", "discount": 0.10, "escalated": False},
        {"approver": "rsm-east", "discount": 0.10, "escalated": False},
        {"approver": "rsm-east", "discount": 0.10, "escalated": False},
    ]
    # Default: 1 of 4 diverges -> 0.25
    assert compute_dnaco(spec, rows, COLUMN_MAP).magnitude == 0.25
    # Weighted: the breach counts triple, capped at 1.0 -> 0.75
    weighted = compute_dnaco(
        spec, rows, COLUMN_MAP,
        {"reason_weights": {"threshold_breach_without_escalation": 3.0}},
    )
    assert weighted.magnitude == 0.75


def test_percent_string_threshold_and_value_coerce():
    spec = ARSpec(documented_approver="rsm-east", threshold=0.15)
    rows = [{"approver": "rsm-east", "discount": "22%", "escalated": "false"}]
    result = compute_dnaco(spec, rows, COLUMN_MAP)
    assert result.divergent_count == 1


# ---------------------------------------------------- deterministic gate

def _relation(**decision_logic) -> AuthorityRelationDb:
    return AuthorityRelationDb(
        id="ar-1", name="Test AR", status="active", version=1,
        decision_logic=decision_logic,
    )


def test_gate_approves_authorized_signer_under_threshold():
    mgr = AuthorityResolutionManager()
    rel = _relation(allowed_principals=["rsm-east"], threshold=0.15, action="approve")
    verdict, _ = mgr._evaluate_decision(rel, {
        "actor_identity": "rsm-east", "action": "approve", "value": 0.10,
    })
    assert verdict == VERDICT_APPROVED


def test_gate_denies_unauthorized_signer():
    mgr = AuthorityResolutionManager()
    rel = _relation(allowed_principals=["rsm-east"])
    verdict, reason = mgr._evaluate_decision(rel, {"actor_identity": "intruder"})
    assert verdict == VERDICT_DENIED
    assert "not an allowed principal" in reason


def test_gate_denies_over_threshold_without_escalation():
    mgr = AuthorityResolutionManager()
    rel = _relation(allowed_principals=["rsm-east"], threshold=0.15)
    verdict, reason = mgr._evaluate_decision(rel, {
        "actor_identity": "rsm-east", "value": 0.30, "escalated": False,
    })
    assert verdict == VERDICT_DENIED
    assert "exceeds threshold" in reason


def test_gate_allows_over_threshold_with_escalation():
    mgr = AuthorityResolutionManager()
    rel = _relation(allowed_principals=["rsm-east"], threshold=0.15)
    verdict, _ = mgr._evaluate_decision(rel, {
        "actor_identity": "rsm-east", "value": 0.30, "escalated": True,
    })
    assert verdict == VERDICT_APPROVED


def test_gate_denies_missing_cosign():
    mgr = AuthorityResolutionManager()
    rel = _relation(allowed_principals=["rsm-east"], required_cosign=True)
    verdict, reason = mgr._evaluate_decision(rel, {
        "actor_identity": "rsm-east", "cosign_present": False,
    })
    assert verdict == VERDICT_DENIED
    assert "co-sign" in reason


def test_gate_denies_action_mismatch():
    mgr = AuthorityResolutionManager()
    rel = _relation(action="approve")
    verdict, _ = mgr._evaluate_decision(rel, {"action": "override"})
    assert verdict == VERDICT_DENIED


# ------------------------------------------------------------- maturity

def test_maturity_levels():
    assert maturity_level(has_object=False, dna_measured=False, fully_affirmed=False) == "L1"
    assert maturity_level(has_object=True, dna_measured=False, fully_affirmed=False) == "L2"
    assert maturity_level(has_object=True, dna_measured=True, fully_affirmed=False) == "L3"
    assert maturity_level(has_object=True, dna_measured=True, fully_affirmed=True) == "L4"


# ---------------------------------- shared Maturity Level feature (compliance-gated)

def test_authority_maturity_feature_integration(db_session):
    """The ARF ladder is seeded as entity_type-specific levels, overrides the
    generic "all" set, and the compliance-gated evaluator advances an AR through
    the levels as it gains an object / evidence+DNA / affirmation."""
    from src.repositories.maturity_repository import maturity_repo
    from src.controller.maturity_evaluator import MaturityEvaluator
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.models.authority_resolution import (
        AuthorityRelationCreate, AffirmationInput, EvidenceSource,
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
        evidence_sources=[EvidenceSource(type="delta_table", ref="c.s.t", column_map={"actual_approver": "a"})],
    ))
    db_session.commit()
    mgr.compute_dnaco(db_session, rel2.id, rows=[])  # measured (empty sample -> magnitude 0.0)
    db_session.commit()
    rep2 = evaluator.evaluate(db_session, entity_type="AuthorityRelation", entity_id=rel2.id, persist=False)
    # object + evidence + measured + within ceiling, but not affirmed -> L3 DNA-Measured
    assert rep2.achieved_level_order == 3
