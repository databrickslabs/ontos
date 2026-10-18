"""Unit tests for the Authority Resolution feature (ARF).

Covers the pure pieces — the criteria-driven DNA-Coefficient engine and the
deterministic runtime gate — plus the DB-backed configurable-criteria path
(inline Compliance Checks driving both the gate and divergence) and the shared
Maturity Level integration.
"""
import pytest

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

def _crit(rule, *, direction=DIR_NEUTRAL, weight=1.0, dimension="people", message=None,
          order=0, enabled=True, name="crit") -> Criterion:
    """A pure engine Criterion (rule already includes ASSERT)."""
    return Criterion(code=name, rule=rule, direction=direction, weight=weight,
                     dimension=dimension, message=message)


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


def test_dimensions_combine_by_probabilistic_union():
    people = _crit("ASSERT obj.actor_identity IN ['ok']", dimension="people", name="ppl")
    policy = _crit("ASSERT obj.value <= 10", dimension="policy", name="pol")
    rows = [
        {"actor_identity": "bad", "value": 5},    # people fails only
        {"actor_identity": "ok", "value": 50},    # policy fails only
    ]
    r = compute_dnaco([people, policy], rows)
    assert r.dimensions["people"] == 0.5      # 1 of 2 rows
    assert r.dimensions["policy"] == 0.5      # 1 of 2 rows
    # Noisy-OR: 1 - (1-0.5)(1-0.5) = 0.75 (scales into [0,1], not a capped sum).
    assert r.magnitude == 0.75


def test_combine_dimensions_properties():
    from src.common.authority_resolution_dna import combine_dimensions
    assert combine_dimensions([]) == 0.0
    assert combine_dimensions([0.0, 0.0]) == 0.0
    assert combine_dimensions([1.0, 0.3]) == 1.0        # a maxed dimension forces 1.0 (no dilution)
    assert combine_dimensions([0.5, 0.0]) == 0.5        # clean dimension leaves it unchanged
    assert combine_dimensions([0.225, 0.375, 0.0]) == 0.5156  # worked example


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
    # people dimension = 1.5 / 2 rows; structural also scored; overall = noisy-OR.
    assert run.per_dimension_scores["people"] == 0.75
    assert "structural" in run.per_dimension_scores
    from src.common.authority_resolution_dna import combine_dimensions
    assert run.magnitude == combine_dimensions(run.per_dimension_scores.values())


def test_structural_dimension_scores_incompleteness(db_session):
    """The built-in structural dimension scores AR-definition completeness: a
    relation complete except for its justification-chain scores 1/5 = 0.2."""
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.models.authority_resolution import (
        AuthorityRelationCreate, EvidenceSource, CriterionInput, AffirmationInput,
    )
    mgr = AuthorityResolutionManager()
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(
        name="Structural AR", object_id="dp-9",
        evidence_sources=[EvidenceSource(type="delta_table", ref="c.s.t", column_map={"actor_identity": "a"})],
        criteria=[CriterionInput(name="Authorized", rule="obj.actor_identity IN ['x']", dimension="people")],
        affirmations=[AffirmationInput(role="Governance Lead", principal="g@x.com", is_approver=True, is_reviewer=False)],
    ))
    db_session.commit()
    run = mgr.compute_dnaco(db_session, rel.id, rows=[{"actor_identity": "x"}])  # one clean row
    db_session.commit()
    assert run.per_dimension_scores["structural"] == 0.2   # only justification_chain missing
    assert run.per_dimension_scores["people"] == 0.0       # no divergent rows
    assert run.magnitude == 0.2


def test_update_does_not_bump_version(db_session):
    """Edits mutate the current row in place — no auto version bump (DP/DC parity)."""
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.models.authority_resolution import AuthorityRelationCreate, AuthorityRelationUpdate

    mgr = AuthorityResolutionManager()
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(name="Editable AR"))
    db_session.commit()
    assert rel.version == "1.0.0"
    assert rel.version_family_id == rel.id
    assert rel.base_name == "Editable AR"

    updated = mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(description="tweaked"))
    db_session.commit()
    assert updated.version == "1.0.0"          # unchanged
    assert updated.description == "tweaked"


def test_create_new_version_snapshots_definition(db_session):
    """New Version deep-clones the definition (criteria + participants + evidence)
    into a fresh draft row in the same family, resetting measured/observed state."""
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.models.authority_resolution import (
        AuthorityRelationCreate, CriterionInput, AffirmationInput, EvidenceSource,
    )
    mgr = AuthorityResolutionManager()
    src = mgr.create_relation(db_session, AuthorityRelationCreate(
        name="Versioned AR", object_id="dp-1",
        evidence_sources=[EvidenceSource(type="delta_table", ref="c.s.t", column_map={"actor_identity": "a"})],
        criteria=[CriterionInput(name="Authorized", rule="obj.actor_identity IN ['rsm-east']",
                                 direction=DIR_ACTUAL_EXCEEDS, weight=1.5, dimension="people")],
        affirmations=[AffirmationInput(role="Governance Lead", principal="g@x.com",
                                       is_approver=True, is_reviewer=True)],
    ))
    db_session.commit()
    # Simulate the source having been measured/used.
    src.dna_magnitude = 0.6
    src.usage_count = 5
    db_session.commit()

    v2 = mgr.create_new_version(db_session, src.id, "2.0.0", change_summary="raised the cap",
                                current_user="lars@x.com")
    db_session.commit()

    assert v2 is not None and v2.id != src.id
    assert v2.version == "2.0.0"
    assert v2.status == "draft"
    assert v2.version_family_id == src.version_family_id      # same family
    assert v2.parent_relation_id == src.id                    # lineage edge
    assert v2.change_summary == "raised the cap"
    assert v2.base_name == "Versioned AR"
    # Definition copied over.
    assert v2.object_id == "dp-1"
    assert v2.evidence_sources == src.evidence_sources
    # Measured/observed state reset on the new draft.
    assert v2.dna_magnitude is None
    assert v2.usage_count == 0

    # Criteria + affirmations were cloned onto the new row.
    v2_crit = mgr._load_criteria(v2)
    assert len(v2_crit) == 1
    v2_dict = mgr.to_read_dict(db_session, v2)
    assert len(v2_dict["affirmations"]) == 1
    assert v2_dict["affirmations"][0]["affirmed"] is False    # reset

    # Both versions live in the family, newest first.
    fam = mgr.get_relation_versions(db_session, src.id)
    assert {r.version for r in fam} == {"1.0.0", "2.0.0"}
    assert fam[0].id == v2.id                                  # newest first


def test_slug_resolves_to_family_active_version(db_session):
    """A slug is the family-level @id: it resolves to the family's active version
    (even though the slug physically lives on the original row), while a UUID pins
    the exact version."""
    from src.controller.authority_resolution_manager import AuthorityResolutionManager, STATUS_ACTIVE
    from src.models.authority_resolution import AuthorityRelationCreate

    mgr = AuthorityResolutionManager()
    v1 = mgr.create_relation(db_session, AuthorityRelationCreate(name="Promo rule", slug="ar-promo"))
    db_session.commit()
    v2 = mgr.create_new_version(db_session, v1.id, "2.0.0")
    db_session.commit()
    # v2 is a fresh draft with no slug of its own; activate it.
    v2.status = STATUS_ACTIVE
    db_session.commit()

    # By slug -> the family's active version (v2), not the row that holds the slug (v1).
    assert v2.slug is None
    resolved = mgr.resolve_relation_ref(db_session, "ar-promo")
    assert resolved is not None and resolved.id == v2.id
    # By UUID -> the exact version.
    assert mgr.resolve_relation_ref(db_session, v1.id).id == v1.id
    # No active version -> falls back to the anchor row that carries the slug.
    v2.status = "draft"
    db_session.commit()
    assert mgr.resolve_relation_ref(db_session, "ar-promo").id == v1.id


def test_list_collapses_by_family(db_session):
    """The default list returns one representative per family with a version_count;
    include_history returns every version."""
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.models.authority_resolution import AuthorityRelationCreate

    mgr = AuthorityResolutionManager()
    a = mgr.create_relation(db_session, AuthorityRelationCreate(name="Family A"))
    mgr.create_relation(db_session, AuthorityRelationCreate(name="Family B"))
    db_session.commit()
    mgr.create_new_version(db_session, a.id, "2.0.0")
    db_session.commit()

    collapsed = mgr.list_relations(db_session)
    fam_a = [r for r in collapsed if (r.version_family_id or r.id) == a.id]
    assert len(fam_a) == 1                                     # A collapsed to one rep
    assert getattr(fam_a[0], "_version_count", None) == 2      # count surfaced

    full = mgr.list_relations(db_session, include_history=True)
    fam_a_full = [r for r in full if (r.version_family_id or r.id) == a.id]
    assert len(fam_a_full) == 2                                # both A versions


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
    mgr.compute_dnaco(db_session, rel2.id, rows=[{"actor_identity": "a", "value": 0.0}])  # measured, no divergence
    db_session.commit()
    rep2 = evaluator.evaluate(db_session, entity_type="AuthorityRelation", entity_id=rel2.id, persist=False)
    # object + evidence + measured + within ceiling, but not affirmed -> L3 DNA-Measured
    assert rep2.achieved_level_order == 3


# ---------------------------------------------------------------------------
# MCP tool: ComputeDnaCoefficientTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_dna_coefficient_tool_by_uuid(db_session, monkeypatch):
    """The MCP tool is a thin wrapper over `manager.compute_dnaco`; verify it
    accepts a UUID, returns the persisted run shape, and leaves the AR row's
    cached magnitude updated."""
    from unittest.mock import MagicMock
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.models.authority_resolution import AuthorityRelationCreate, CriterionInput
    from src.tools.authority_resolution import ComputeDnaCoefficientTool
    from src.tools.base import ToolContext

    mgr = AuthorityResolutionManager()
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(
        name="DNAco-tool AR",
        criteria=[CriterionInput(name="cap", rule="obj.value <= 0.15",
                                 failure_message="over", direction=DIR_ACTUAL_EXCEEDS,
                                 weight=1.0, order=0)],
    ))
    db_session.commit()

    tool = ComputeDnaCoefficientTool()
    ctx = ToolContext(db=db_session, settings=MagicMock())
    # Patch the tool's module-level manager so it doesn't read a real Delta table.
    import src.tools.authority_resolution as artools
    monkeypatch.setattr(artools._manager, "_collect_evidence", lambda _rel: [
        {"actor_identity": "a", "value": 0.22},   # breaches
        {"actor_identity": "a", "value": 0.10},   # clean
    ])

    result = await tool.execute(ctx, ar_id=rel.id)
    assert result.success is True, result.error
    assert result.data["relation_id"] == rel.id
    assert result.data["status"] == "succeeded"
    assert result.data["sampled_count"] == 2
    assert result.data["divergent_count"] == 1
    assert result.data["direction"] == DIR_ACTUAL_EXCEEDS
    assert result.data["magnitude"] > 0.0
    assert "people" in (result.data["per_dimension_scores"] or {})


@pytest.mark.asyncio
async def test_compute_dna_coefficient_tool_resolves_slug_and_handles_not_found(db_session, monkeypatch):
    """Slug input is resolved to the family's active version (so this works
    stably across version clones), and an unknown ar_id returns a tool error
    rather than crashing."""
    from unittest.mock import MagicMock
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.models.authority_resolution import AuthorityRelationCreate
    from src.tools.authority_resolution import ComputeDnaCoefficientTool
    from src.tools.base import ToolContext
    import src.tools.authority_resolution as artools

    mgr = AuthorityResolutionManager()
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(
        name="DNAco-tool AR by slug", slug="dnaco-tool-slug",
    ))
    db_session.commit()
    monkeypatch.setattr(artools._manager, "_collect_evidence", lambda _rel: [{"actor_identity": "a", "value": 0.0}])

    tool = ComputeDnaCoefficientTool()
    ctx = ToolContext(db=db_session, settings=MagicMock())

    ok = await tool.execute(ctx, ar_id="dnaco-tool-slug")
    assert ok.success is True, ok.error
    assert ok.data["relation_id"] == rel.id

    missing = await tool.execute(ctx, ar_id="does-not-exist-slug")
    assert missing.success is False
    assert "not found" in (missing.error or "").lower()

    empty = await tool.execute(ctx, ar_id="")
    assert empty.success is False
    assert "required" in (empty.error or "").lower()


# ---------------------------------------------------------------------------
# ARF v2 graph: resource refs + prerequisites (schema + model smoke)
# ---------------------------------------------------------------------------


def test_resource_ref_round_trips_and_enforces_unique_field(db_session):
    """A ref row persists the typed pointer for an AR field, and the DB
    rejects a second row for the same ``(relation_id, field_path)``."""
    import uuid
    from sqlalchemy.exc import IntegrityError
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.db_models.authority_resolution import AuthorityResourceRefDb
    from src.models.authority_resolution import AuthorityRelationCreate

    mgr = AuthorityResolutionManager()
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(name="Ref-test AR"))
    db_session.commit()

    db_session.add(AuthorityResourceRefDb(
        id=str(uuid.uuid4()), relation_id=rel.id,
        field_path="actor_identity", ref_type="mcp_tool",
        mcp_service_name="mcp-services/system.ai.github",
        mcp_tool_name="get_user_by_role",
        mcp_params={"role": "{{ actor_role }}"},
    ))
    db_session.commit()

    stored = db_session.query(AuthorityResourceRefDb).filter_by(
        relation_id=rel.id, field_path="actor_identity",
    ).one()
    assert stored.mcp_result_pointer == "$"           # server default landed
    assert stored.mcp_params == {"role": "{{ actor_role }}"}

    db_session.add(AuthorityResourceRefDb(
        id=str(uuid.uuid4()), relation_id=rel.id,
        field_path="actor_identity", ref_type="literal", literal_value="x",
    ))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_resource_ref_cascades_on_relation_delete(db_session):
    """Deleting the parent AR removes its resource_refs via the FK CASCADE."""
    import uuid
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.db_models.authority_resolution import AuthorityResourceRefDb
    from src.models.authority_resolution import AuthorityRelationCreate

    mgr = AuthorityResolutionManager()
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(name="Cascade-ref AR"))
    db_session.commit()
    rel_id = rel.id

    db_session.add(AuthorityResourceRefDb(
        id=str(uuid.uuid4()), relation_id=rel_id,
        field_path="object_id", ref_type="ontos_entity",
        entity_type="data_product", entity_id="dp-123",
    ))
    db_session.commit()
    assert db_session.query(AuthorityResourceRefDb).filter_by(relation_id=rel_id).count() == 1

    db_session.delete(rel)
    db_session.commit()
    assert db_session.query(AuthorityResourceRefDb).filter_by(relation_id=rel_id).count() == 0


def test_prerequisite_edge_rejects_self_loop(db_session):
    """A self-referential prerequisite is a cycle by definition; the DB
    check-constraint rejects it at write time so the resolve-time cycle
    detector never has to fire for the trivial case."""
    import uuid
    from sqlalchemy.exc import IntegrityError
    from src.db_models.authority_resolution import AuthorityPrerequisiteDb

    db_session.add(AuthorityPrerequisiteDb(
        id=str(uuid.uuid4()),
        relation_family_slug="trade-promotion",
        prerequisite_family_slug="trade-promotion",
    ))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_prerequisite_edge_round_trips(db_session):
    """Two ARs in distinct families can be wired as an A→B prerequisite,
    retrieved by downstream family slug (``list_for_family``), and by
    upstream family slug (``list_dependents`` — used by the write-time
    cycle check)."""
    import uuid
    from src.db_models.authority_resolution import AuthorityPrerequisiteDb
    from src.repositories.authority_resolution_repository import authority_prerequisite_repo

    db_session.add(AuthorityPrerequisiteDb(
        id=str(uuid.uuid4()),
        relation_family_slug="trade-promotion",
        prerequisite_family_slug="market-compliance",
        display_order=0,
    ))
    db_session.add(AuthorityPrerequisiteDb(
        id=str(uuid.uuid4()),
        relation_family_slug="trade-promotion",
        prerequisite_family_slug="budget-delegation",
        display_order=1,
    ))
    db_session.commit()

    deps = authority_prerequisite_repo.list_for_family(
        db_session, relation_family_slug="trade-promotion",
    )
    assert [e.prerequisite_family_slug for e in deps] == [
        "market-compliance", "budget-delegation",
    ]

    rev = authority_prerequisite_repo.list_dependents(
        db_session, prerequisite_family_slug="market-compliance",
    )
    assert [e.relation_family_slug for e in rev] == ["trade-promotion"]


def test_resolver_auth_defaults_to_obo(db_session):
    """New ARs default to OBO; the author pins ``app_sp`` when stability
    matters more than per-caller context."""
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.models.authority_resolution import AuthorityRelationCreate

    mgr = AuthorityResolutionManager()
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(name="Auth-flag AR"))
    db_session.commit()
    assert rel.resolver_auth == "obo"


# ---------------------------------------------------------------------------
# ARF v2: prerequisite chain evaluator
# ---------------------------------------------------------------------------


def _make_ar(mgr, db, *, slug, name, criteria=None, prerequisites=None):
    """Helper for prereq tests — slug is mandatory because edges are keyed by it."""
    from src.models.authority_resolution import (
        AuthorityRelationCreate, CriterionInput, PrerequisiteInput,
    )
    return mgr.create_relation(db, AuthorityRelationCreate(
        name=name, slug=slug,
        criteria=[CriterionInput(**c) for c in (criteria or [])],
        prerequisites=[PrerequisiteInput(**p) for p in (prerequisites or [])],
    ))


def test_resolve_blocked_by_failing_prerequisite(db_session):
    """A required prerequisite that returns a non-approved verdict short-circuits
    the outer AR to ``denied`` with reason ``blocked by prerequisite ar:<slug>``.
    The full chain is attached to the response so the agent can see which gate
    rejected them, and the decision row's ``provenance`` records the walk."""
    from src.controller.authority_resolution_manager import (
        AuthorityResolutionManager, VERDICT_APPROVED, VERDICT_DENIED,
    )
    from src.repositories.authority_resolution_repository import authority_decision_repo

    mgr = AuthorityResolutionManager()
    # Upstream gate: denies anyone not on the allow-list.
    _make_ar(mgr, db_session, slug="market-compliance", name="Market compliance",
             criteria=[dict(name="allow", rule="obj.actor_identity IN ['approved-rsm']",
                             failure_message="actor not approved for this market")])
    # Downstream: trivially approves on its own, but requires market-compliance.
    _make_ar(mgr, db_session, slug="trade-promo", name="Trade promotion",
             prerequisites=[dict(prerequisite_family_slug="market-compliance")])
    db_session.commit()

    # Signer not on the market allow-list → outer is blocked, verdict = denied,
    # chain carries the upstream failure.
    out = mgr.resolve(db_session, "trade-promo",
                       {"actor_identity": "intruder"},
                       record=True, require_active=False)
    assert out["verdict"] == VERDICT_DENIED
    assert out["reason"].startswith("blocked by prerequisite ar:market-compliance")
    chain = out["prerequisite_chain"]
    assert len(chain) == 1
    assert chain[0]["slug"] == "market-compliance"
    assert chain[0]["verdict"] == VERDICT_DENIED
    assert chain[0]["required"] is True

    # Signer on the allow-list → upstream clears, outer approves.
    out = mgr.resolve(db_session, "trade-promo",
                       {"actor_identity": "approved-rsm"},
                       record=True, require_active=False)
    assert out["verdict"] == VERDICT_APPROVED
    assert out["prerequisite_chain"][0]["verdict"] == VERDICT_APPROVED

    # Provenance landed on the persisted decisions.
    decisions = authority_decision_repo.list_for_relation(
        db_session, relation_id=out["relation_id"],
    )
    # Both runs recorded; the blocked one has the chain, the approved one too.
    assert any(d.provenance and d.provenance.get("chain") for d in decisions)


def test_optional_prerequisite_adds_warning_not_block(db_session):
    """A ``required=False`` prerequisite surfaces in the chain for the agent to
    see, but does not block the outer verdict when it fails."""
    from src.controller.authority_resolution_manager import (
        AuthorityResolutionManager, VERDICT_APPROVED, VERDICT_DENIED,
    )

    mgr = AuthorityResolutionManager()
    _make_ar(mgr, db_session, slug="advisory-check", name="Advisory",
             criteria=[dict(name="allow", rule="obj.actor_identity = 'nobody'",
                             failure_message="advisory failed")])
    _make_ar(mgr, db_session, slug="main-gate", name="Main gate",
             prerequisites=[dict(prerequisite_family_slug="advisory-check", required=False)])
    db_session.commit()

    out = mgr.resolve(db_session, "main-gate",
                       {"actor_identity": "anyone"},
                       record=False, require_active=False)
    assert out["verdict"] == VERDICT_APPROVED
    assert len(out["prerequisite_chain"]) == 1
    entry = out["prerequisite_chain"][0]
    assert entry["slug"] == "advisory-check"
    assert entry["verdict"] == VERDICT_DENIED
    assert entry["required"] is False


def test_prerequisite_slug_resolves_to_active_version(db_session):
    """Edges store the family slug, so a prereq version bump + reactivation
    automatically redirects downstream resolves to the new active version
    without rewriting the edge."""
    from src.controller.authority_resolution_manager import (
        AuthorityResolutionManager, STATUS_ACTIVE, VERDICT_DENIED,
    )

    mgr = AuthorityResolutionManager()
    v1 = _make_ar(mgr, db_session, slug="pre-slug", name="Prereq v1",
                   criteria=[dict(name="v1", rule="obj.value <= 10",
                                   failure_message="over cap (v1)")])
    _make_ar(mgr, db_session, slug="dep-slug", name="Dependent",
             prerequisites=[dict(prerequisite_family_slug="pre-slug")])
    v1.status = STATUS_ACTIVE
    db_session.commit()

    # Baseline: resolves against v1's rule (cap = 10).
    first = mgr.resolve(db_session, "dep-slug", {"value": 20},
                         record=False, require_active=False)
    assert first["prerequisite_chain"][0]["version"] == "1.0.0"
    assert first["verdict"] == VERDICT_DENIED

    # Bump to v2 with a tighter rule and activate it; v1 goes draft (anchor keeps slug).
    v2 = mgr.create_new_version(db_session, v1.id, "2.0.0")
    db_session.commit()
    # Re-author v2's criteria to a stricter cap.
    from src.models.authority_resolution import AuthorityRelationUpdate, CriterionInput
    mgr.update_relation(db_session, v2.id, AuthorityRelationUpdate(
        criteria=[CriterionInput(name="v2", rule="obj.value <= 5",
                                   failure_message="over cap (v2)")],
    ))
    v1.status = "draft"
    v2.status = STATUS_ACTIVE
    db_session.commit()

    second = mgr.resolve(db_session, "dep-slug", {"value": 7},
                          record=False, require_active=False)
    # v2 is active; the chain now reports v2's version string.
    assert second["prerequisite_chain"][0]["version"] == "2.0.0"
    assert second["verdict"] == VERDICT_DENIED
    assert "over cap (v2)" in second["reason"]


def test_cycle_in_prerequisite_chain_returns_conflict(db_session):
    """The write-time check normally rejects cycles, but a hand-crafted edge
    (bypassing the manager) is still caught by the resolve-time cycle guard,
    which returns ``conflict`` on the outer verdict."""
    import uuid as _uuid
    from src.controller.authority_resolution_manager import (
        AuthorityResolutionManager, VERDICT_CONFLICT,
    )
    from src.db_models.authority_resolution import AuthorityPrerequisiteDb

    mgr = AuthorityResolutionManager()
    _make_ar(mgr, db_session, slug="a", name="A")
    _make_ar(mgr, db_session, slug="b", name="B",
             prerequisites=[dict(prerequisite_family_slug="a")])
    # Hand-craft the reverse edge so the write-time check doesn't see it.
    db_session.add(AuthorityPrerequisiteDb(
        id=str(_uuid.uuid4()),
        relation_family_slug="a",
        prerequisite_family_slug="b",
    ))
    db_session.commit()

    out = mgr.resolve(db_session, "b", {"actor_identity": "x"},
                       record=False, require_active=False)
    assert out["verdict"] == VERDICT_CONFLICT
    assert "cycle" in out["reason"].lower()


def test_write_rejects_cycle_in_prerequisites(db_session):
    """``_replace_prerequisites`` rejects an edge whose upstream family's
    transitive prereqs already contain the head slug."""
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.models.authority_resolution import AuthorityRelationUpdate, PrerequisiteInput

    mgr = AuthorityResolutionManager()
    # A requires B.
    _make_ar(mgr, db_session, slug="x", name="X")
    y = _make_ar(mgr, db_session, slug="y", name="Y",
                  prerequisites=[dict(prerequisite_family_slug="x")])
    db_session.commit()

    # Now try to make X require Y → closes a cycle.
    x = mgr.get_relation_by_slug(db_session, "x")
    with pytest.raises(ValueError, match="cycle"):
        mgr.update_relation(db_session, x.id, AuthorityRelationUpdate(
            prerequisites=[PrerequisiteInput(prerequisite_family_slug="y")],
        ))
    # And attempting to make a family require itself.
    with pytest.raises(ValueError, match="cannot require itself"):
        mgr.update_relation(db_session, y.id, AuthorityRelationUpdate(
            prerequisites=[PrerequisiteInput(prerequisite_family_slug="y")],
        ))


def test_prerequisites_require_a_family_slug(db_session):
    """``_replace_prerequisites`` rejects when the AR has no slug yet —
    edges can't anchor to an identity that doesn't exist. An empty list
    is still accepted (noop)."""
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.models.authority_resolution import (
        AuthorityRelationCreate, PrerequisiteInput, AuthorityRelationUpdate,
    )

    mgr = AuthorityResolutionManager()
    _make_ar(mgr, db_session, slug="existing", name="Existing")
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(name="Slugless AR"))
    db_session.commit()
    assert rel.slug is None

    with pytest.raises(ValueError, match="slug"):
        mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(
            prerequisites=[PrerequisiteInput(prerequisite_family_slug="existing")],
        ))
    # Empty prereqs on a slugless AR is a noop (not an error).
    mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(prerequisites=[]))
    db_session.commit()


# ---------------------------------------------------------------------------
# ARF v2: resource refs (literal + Ontos entity)
# ---------------------------------------------------------------------------


def test_literal_resource_ref_round_trips_and_resolves(db_session):
    """A ``literal`` ref persists verbatim, surfaces on ``to_read_dict``, and
    comes back in the resolve response's ``resolved_refs`` list with its
    cached label updated."""
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.models.authority_resolution import (
        AuthorityRelationCreate, ResourceRefInput,
    )
    from src.repositories.authority_resolution_repository import authority_resource_ref_repo

    mgr = AuthorityResolutionManager()
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(
        name="Literal AR", slug="lit-ar",
        resource_refs=[ResourceRefInput(
            field_path="actor_identity", ref_type="literal",
            literal_value="rsm-east@example.com",
        )],
    ))
    db_session.commit()

    # Read side: list_resource_refs is wired through to_read_dict.
    read = mgr.to_read_dict(db_session, rel)
    assert len(read["resource_refs"]) == 1
    assert read["resource_refs"][0]["field_path"] == "actor_identity"
    assert read["resource_refs"][0]["ref_type"] == "literal"
    assert read["resource_refs"][0]["literal_value"] == "rsm-east@example.com"

    # Resolve surfaces the materialised value + updates cache.
    out = mgr.resolve(db_session, "lit-ar", {"actor_identity": "x"},
                       record=False, require_active=False)
    assert out["resolved_refs"] == [{
        "field_path": "actor_identity",
        "ref_type": "literal",
        "value": "rsm-east@example.com",
        "source": "literal",
    }]
    row = authority_resource_ref_repo.list_for_relation(db_session, relation_id=rel.id)[0]
    assert row.cached_label is None  # dry runs never write the cache

    mgr.resolve(db_session, "lit-ar", {"actor_identity": "x"}, record=True, require_active=False)
    assert row.cached_label == "rsm-east@example.com"
    assert row.cached_at is not None


def test_ontos_entity_ref_business_concept_falls_back_to_iri(db_session):
    """Without a SemanticModelsManager the business_concept branch still
    produces a stable value — the IRI itself. This is the cold-start /
    unit-test path and must never crash a resolve."""
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.models.authority_resolution import (
        AuthorityRelationCreate, ResourceRefInput,
    )

    mgr = AuthorityResolutionManager()
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(
        name="Concept-backed AR", slug="concept-ar",
        resource_refs=[ResourceRefInput(
            field_path="domain_context.market", ref_type="ontos_entity",
            entity_type="business_concept",
            entity_id="urn:demo:concept:germany",
        )],
    ))
    db_session.commit()

    out = mgr.resolve(db_session, "concept-ar", {},
                       record=False, require_active=False)
    assert len(out["resolved_refs"]) == 1
    entry = out["resolved_refs"][0]
    assert entry["field_path"] == "domain_context.market"
    assert entry["ref_type"] == "ontos_entity"
    assert entry["value"] == "urn:demo:concept:germany"  # IRI fallback
    assert entry["iri"] == "urn:demo:concept:germany"
    assert entry["source"] == "ontos_entity"


def test_ontos_entity_ref_uses_semantic_manager_label_when_available(db_session):
    """When a SemanticModelsManager is supplied, the ontos_entity resolver
    prefers its ``get_concept_details(iri).label`` over the raw IRI."""
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.models.authority_resolution import (
        AuthorityRelationCreate, ResourceRefInput,
    )

    class _FakeConcept:
        def __init__(self, label):
            self.label = label

    class _FakeSemManager:
        def get_concept_details(self, iri):
            return _FakeConcept("Germany")

    mgr = AuthorityResolutionManager()
    mgr.create_relation(db_session, AuthorityRelationCreate(
        name="Concept-labeled AR", slug="concept-labeled",
        resource_refs=[ResourceRefInput(
            field_path="domain_context.market", ref_type="ontos_entity",
            entity_type="business_concept",
            entity_id="urn:demo:concept:germany",
        )],
    ))
    db_session.commit()

    out = mgr.resolve(db_session, "concept-labeled", {},
                       record=False, require_active=False,
                       semantic_models_manager=_FakeSemManager())
    entry = out["resolved_refs"][0]
    assert entry["value"] == "Germany"
    assert entry["iri"] == "urn:demo:concept:germany"


def test_resource_refs_persist_on_decision_provenance(db_session):
    """A recorded decision carries ``provenance.resolved_refs`` alongside the
    chain so the audit trail can replay what the AR was pointing at."""
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.models.authority_resolution import (
        AuthorityRelationCreate, ResourceRefInput,
    )
    from src.repositories.authority_resolution_repository import authority_decision_repo

    mgr = AuthorityResolutionManager()
    mgr.create_relation(db_session, AuthorityRelationCreate(
        name="Provenance AR", slug="prov-ar",
        resource_refs=[ResourceRefInput(
            field_path="actor_identity", ref_type="literal",
            literal_value="rsm-east@example.com",
        )],
    ))
    db_session.commit()

    out = mgr.resolve(db_session, "prov-ar", {"actor_identity": "x"},
                       record=True, require_active=False)
    decisions = authority_decision_repo.list_for_relation(
        db_session, relation_id=out["relation_id"],
    )
    assert len(decisions) == 1
    prov = decisions[0].provenance
    assert prov is not None
    assert prov.get("resolved_refs") == [{
        "field_path": "actor_identity",
        "ref_type": "literal",
        "value": "rsm-east@example.com",
        "source": "literal",
    }]
    # chain is absent because no prerequisites were declared.
    assert "chain" not in prov


def test_resource_ref_write_rejects_malformed_rows(db_session):
    """``_replace_resource_refs`` surfaces author errors as ``ValueError``
    (routes map these to a 400):

    * unknown ``ref_type``
    * ``literal`` without ``literal_value``
    * ``ontos_entity`` without both ``entity_type`` and ``entity_id``
    """
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.models.authority_resolution import (
        AuthorityRelationCreate, AuthorityRelationUpdate, ResourceRefInput,
    )

    mgr = AuthorityResolutionManager()
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(
        name="Bad refs AR", slug="bad-refs",
    ))
    db_session.commit()

    with pytest.raises(ValueError, match="ref_type"):
        mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(
            resource_refs=[ResourceRefInput(field_path="actor_identity", ref_type="bogus")],
        ))
    with pytest.raises(ValueError, match="literal_value"):
        mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(
            resource_refs=[ResourceRefInput(field_path="actor_identity", ref_type="literal")],
        ))
    with pytest.raises(ValueError, match="entity_type"):
        mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(
            resource_refs=[ResourceRefInput(
                field_path="actor_identity", ref_type="ontos_entity",
                entity_type=None, entity_id="urn:x",
            )],
        ))


def test_resource_refs_are_replaced_on_update(db_session):
    """Writing ``resource_refs`` is replace-on-write: the manager drops the
    old rows and recreates the new set, so an author editing the field in
    the dialog gets the shape they chose, not a cumulative union."""
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.models.authority_resolution import (
        AuthorityRelationCreate, AuthorityRelationUpdate, ResourceRefInput,
    )
    from src.repositories.authority_resolution_repository import authority_resource_ref_repo

    mgr = AuthorityResolutionManager()
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(
        name="Replacement AR", slug="replace-ar",
        resource_refs=[
            ResourceRefInput(field_path="actor_identity", ref_type="literal", literal_value="old@example.com"),
            ResourceRefInput(field_path="object_id", ref_type="literal", literal_value="dp-old"),
        ],
    ))
    db_session.commit()
    assert len(authority_resource_ref_repo.list_for_relation(db_session, relation_id=rel.id)) == 2

    # Replace with a single new row — the two old ones must be gone.
    mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(
        resource_refs=[ResourceRefInput(
            field_path="actor_identity", ref_type="literal",
            literal_value="new@example.com",
        )],
    ))
    db_session.commit()
    rows = authority_resource_ref_repo.list_for_relation(db_session, relation_id=rel.id)
    assert len(rows) == 1
    assert rows[0].field_path == "actor_identity"
    assert rows[0].literal_value == "new@example.com"


def test_prereq_slug_containing_cycle_is_denied_not_conflict(db_session):
    """Outer verdict comes from the inner verdict, not a substring of the reason."""
    from src.controller.authority_resolution_manager import (
        AuthorityResolutionManager, VERDICT_DENIED,
    )

    mgr = AuthorityResolutionManager()
    _make_ar(mgr, db_session, slug="cycle-check-approvals", name="Cycle check",
             criteria=[dict(name="never", rule="obj.actor_identity = 'nobody'",
                             failure_message="not allowed")])
    _make_ar(mgr, db_session, slug="downstream", name="Downstream",
             prerequisites=[dict(prerequisite_family_slug="cycle-check-approvals")])
    db_session.commit()

    out = mgr.resolve(db_session, "downstream", {"actor_identity": "x"},
                       record=False, require_active=False)
    assert out["verdict"] == VERDICT_DENIED


def test_write_rejects_dangling_prerequisite_slug(db_session):
    from src.controller.authority_resolution_manager import AuthorityResolutionManager

    mgr = AuthorityResolutionManager()
    with pytest.raises(ValueError, match="does not match"):
        _make_ar(mgr, db_session, slug="orphan-dep", name="Orphan",
                 prerequisites=[dict(prerequisite_family_slug="nonexistent-ar")])


def test_invalid_resource_ref_update_keeps_existing_rows(db_session):
    """Validation runs before the delete, so a rejected update leaves prior refs
    intact even without a transaction rollback; unsupported entity types are
    rejected at write time."""
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.models.authority_resolution import (
        AuthorityRelationCreate, AuthorityRelationUpdate, ResourceRefInput,
    )
    from src.repositories.authority_resolution_repository import authority_resource_ref_repo

    mgr = AuthorityResolutionManager()
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(
        name="Keep refs", slug="keep-refs",
        resource_refs=[ResourceRefInput(field_path="object_id", ref_type="literal",
                                        literal_value="dp-1")],
    ))
    db_session.commit()

    with pytest.raises(ValueError, match="unsupported entity_type"):
        mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(
            resource_refs=[ResourceRefInput(field_path="object_id", ref_type="ontos_entity",
                                            entity_type="kafka_topic", entity_id="x")],
        ))
    rows = authority_resource_ref_repo.list_for_relation(db_session, relation_id=rel.id)
    assert [r.literal_value for r in rows] == ["dp-1"]


def test_list_family_slugs_surfaces_slug_from_sibling_version(db_session):
    from src.controller.authority_resolution_manager import AuthorityResolutionManager

    mgr = AuthorityResolutionManager()
    v1 = _make_ar(mgr, db_session, slug="fam-slug", name="Family")
    mgr.create_new_version(db_session, v1.id, "2.0.0")
    db_session.commit()

    slugs = mgr.list_family_slugs(db_session)
    assert [s["family_slug"] for s in slugs] == ["fam-slug"]


# ---------------------------------------------------------------------------
# ARF v2: MCP-tool resource refs
# ---------------------------------------------------------------------------


class _FakeMcpClient:
    """Stands in for McpHttpClient; records which workspace client was used."""
    instances = []

    def __init__(self, ws, service_name, deadline=None, response=None, raises=None):
        self.ws, self.service_name, self.calls = ws, service_name, []
        self.response, self.raises = response, raises
        _FakeMcpClient.instances.append(self)

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if self.raises:
            raise self.raises
        return self.response


def _mcp_factory(response=None, raises=None):
    _FakeMcpClient.instances = []
    return lambda ws, svc, deadline=None: _FakeMcpClient(ws, svc, deadline, response, raises)


def _make_mcp_ar(mgr, db, *, slug, resolver_auth="obo", criteria=None, pointer="$.approver"):
    from src.models.authority_resolution import (
        AuthorityRelationCreate, CriterionInput, ResourceRefInput,
    )
    return mgr.create_relation(db, AuthorityRelationCreate(
        name=f"MCP AR {slug}", slug=slug, resolver_auth=resolver_auth,
        actor_role="Trade Marketing Director",
        criteria=[CriterionInput(**c) for c in (criteria or [])],
        resource_refs=[ResourceRefInput(
            field_path="actor_identity", ref_type="mcp_tool",
            mcp_service_name="mcp-services/hr.org.ontos_identity",
            mcp_tool_name="get_role_holder",
            mcp_params={"role": "{{ ar.actor_role }}", "market": "{{ market }}"},
            mcp_result_pointer=pointer,
        )],
    ))


def test_mcp_ref_value_feeds_criteria_via_ref_namespace(db_session):
    """The MCP-resolved approver is exposed to criteria as obj.ref_actor_identity;
    params are rendered from the AR + request; OBO is the default client."""
    from src.controller.authority_resolution_manager import (
        AuthorityResolutionManager, VERDICT_APPROVED, VERDICT_DENIED,
    )

    mgr = AuthorityResolutionManager()
    _make_mcp_ar(mgr, db_session, slug="mcp-gate", criteria=[dict(
        name="signer is role holder", rule="obj.actor_identity = obj.ref_actor_identity",
        failure_message="signer does not hold the role",
    )])
    db_session.commit()
    obo_ws, app_ws = object(), object()
    factory = _mcp_factory(response={"approver": "dir@example.com"})

    ok = mgr.resolve(db_session, "mcp-gate", {"actor_identity": "dir@example.com", "market": "DE"},
                     record=False, require_active=False,
                     obo_ws_factory=lambda: obo_ws, app_ws_factory=lambda: app_ws,
                     mcp_client_factory=factory)
    assert ok["verdict"] == VERDICT_APPROVED, ok["reason"]
    assert ok["resolved_refs"][0]["value"] == "dir@example.com"
    assert ok["resolved_refs"][0]["source"] == "mcp_tool"
    client = _FakeMcpClient.instances[0]
    assert client.ws is obo_ws
    assert client.service_name == "mcp-services/hr.org.ontos_identity"
    assert client.calls == [("get_role_holder", {"role": "Trade Marketing Director", "market": "DE"})]

    bad = mgr.resolve(db_session, "mcp-gate", {"actor_identity": "intruder@example.com"},
                      record=False, require_active=False,
                      obo_ws_factory=lambda: obo_ws, mcp_client_factory=_mcp_factory(
                          response={"approver": "dir@example.com"}))
    # market is undefined in the request → StrictUndefined template error → no_authority.
    assert bad["verdict"] != VERDICT_APPROVED


def test_request_cannot_spoof_ref_namespace(db_session):
    from src.controller.authority_resolution_manager import (
        AuthorityResolutionManager, VERDICT_DENIED,
    )

    mgr = AuthorityResolutionManager()
    _make_ar(mgr, db_session, slug="spoof-gate", name="Spoof", criteria=[dict(
        name="needs ref", rule="obj.actor_identity = obj.ref_actor_identity",
        failure_message="no resolved approver",
    )])
    db_session.commit()
    out = mgr.resolve(db_session, "spoof-gate",
                      {"actor_identity": "me", "ref_actor_identity": "me"},
                      record=False, require_active=False)
    assert out["verdict"] == VERDICT_DENIED


def test_app_sp_auth_bypasses_caller_identity(db_session):
    from src.controller.authority_resolution_manager import (
        AuthorityResolutionManager, VERDICT_APPROVED,
    )

    mgr = AuthorityResolutionManager()
    _make_mcp_ar(mgr, db_session, slug="sp-gate", resolver_auth="app_sp")
    db_session.commit()
    obo_ws, app_ws = object(), object()
    out = mgr.resolve(db_session, "sp-gate", {"market": "DE"}, record=False, require_active=False,
                      obo_ws_factory=lambda: obo_ws, app_ws_factory=lambda: app_ws,
                      mcp_client_factory=_mcp_factory(response={"approver": "x"}))
    assert out["verdict"] == VERDICT_APPROVED
    assert _FakeMcpClient.instances[0].ws is app_ws


def test_obo_ref_without_caller_token_fails_closed(db_session):
    from src.controller.authority_resolution_manager import (
        AuthorityResolutionManager, VERDICT_NO_AUTHORITY,
    )

    mgr = AuthorityResolutionManager()
    _make_mcp_ar(mgr, db_session, slug="obo-gate")
    db_session.commit()
    factory = _mcp_factory(response={"approver": "x"})
    out = mgr.resolve(db_session, "obo-gate", {"market": "DE"}, record=False, require_active=False,
                      obo_ws_factory=None, app_ws_factory=lambda: object(),
                      mcp_client_factory=factory)
    assert out["verdict"] == VERDICT_NO_AUTHORITY
    assert "OBO" in out["reason"]
    assert _FakeMcpClient.instances == []


def test_mcp_ref_timeout_falls_back_to_no_authority(db_session):
    from src.common.mcp_resolver import McpResolverError
    from src.controller.authority_resolution_manager import (
        AuthorityResolutionManager, VERDICT_NO_AUTHORITY,
    )

    mgr = AuthorityResolutionManager()
    _make_mcp_ar(mgr, db_session, slug="slow-gate")
    db_session.commit()
    out = mgr.resolve(db_session, "slow-gate", {"market": "DE"}, record=False, require_active=False,
                      obo_ws_factory=lambda: object(),
                      mcp_client_factory=_mcp_factory(
                          raises=McpResolverError("resolver_timeout", kind="timeout")))
    assert out["verdict"] == VERDICT_NO_AUTHORITY
    assert out["reason"] == "resolver_timeout"
    assert out["resolved_refs"][0]["error_kind"] == "timeout"


def test_mcp_failure_in_prerequisite_blocks_outer(db_session):
    from src.common.mcp_resolver import McpResolverError
    from src.controller.authority_resolution_manager import (
        AuthorityResolutionManager, VERDICT_DENIED, VERDICT_NO_AUTHORITY,
    )

    mgr = AuthorityResolutionManager()
    _make_mcp_ar(mgr, db_session, slug="upstream-mcp")
    _make_ar(mgr, db_session, slug="outer-mcp", name="Outer",
             prerequisites=[dict(prerequisite_family_slug="upstream-mcp")])
    db_session.commit()
    out = mgr.resolve(db_session, "outer-mcp", {"market": "DE"}, record=False, require_active=False,
                      obo_ws_factory=lambda: object(),
                      mcp_client_factory=_mcp_factory(
                          raises=McpResolverError("MCP permission denied (403)", kind="permission")))
    # An upstream resolver outage is "can't decide", not a policy denial.
    assert out["verdict"] == VERDICT_NO_AUTHORITY
    assert out["reason"].startswith("blocked by prerequisite ar:upstream-mcp")
    assert out["prerequisite_chain"][0]["verdict"] == VERDICT_NO_AUTHORITY


def test_literal_fallback_when_no_ref_row_present(db_session):
    """No ref rows → no resolved_refs; criteria evaluate against the request alone."""
    from src.controller.authority_resolution_manager import (
        AuthorityResolutionManager, VERDICT_APPROVED,
    )

    mgr = AuthorityResolutionManager()
    _make_ar(mgr, db_session, slug="plain-gate", name="Plain", criteria=[dict(
        name="cap", rule="obj.value <= 10", failure_message="over")])
    db_session.commit()
    out = mgr.resolve(db_session, "plain-gate", {"value": 5}, record=False, require_active=False)
    assert out["verdict"] == VERDICT_APPROVED
    assert out["resolved_refs"] == []


def test_mcp_ref_and_resolver_auth_write_validation(db_session):
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.models.authority_resolution import (
        AuthorityRelationCreate, AuthorityRelationUpdate, ResourceRefInput,
    )

    mgr = AuthorityResolutionManager()
    with pytest.raises(ValueError, match="resolver_auth"):
        mgr.create_relation(db_session, AuthorityRelationCreate(name="x", resolver_auth="root"))
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(name="MCP validate", slug="mcp-val"))
    db_session.commit()
    assert mgr.to_read_dict(db_session, rel)["resolver_auth"] == "obo"
    with pytest.raises(ValueError, match="mcp_service_name"):
        mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(resource_refs=[ResourceRefInput(
            field_path="actor_identity", ref_type="mcp_tool",
            mcp_service_name="system.ai.github", mcp_tool_name="t")]))
    with pytest.raises(ValueError, match="mcp_result_pointer"):
        mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(resource_refs=[ResourceRefInput(
            field_path="actor_identity", ref_type="mcp_tool",
            mcp_service_name="mcp-services/system.ai.github", mcp_tool_name="t",
            mcp_result_pointer="approver")]))


def test_new_version_clones_resource_refs_and_resolver_auth(db_session):
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.repositories.authority_resolution_repository import authority_resource_ref_repo

    mgr = AuthorityResolutionManager()
    v1 = _make_mcp_ar(mgr, db_session, slug="ver-mcp", resolver_auth="app_sp")
    db_session.commit()
    v2 = mgr.create_new_version(db_session, v1.id, "2.0.0")
    db_session.commit()
    refs = authority_resource_ref_repo.list_for_relation(db_session, relation_id=v2.id)
    assert [(r.field_path, r.ref_type, r.mcp_tool_name) for r in refs] == [
        ("actor_identity", "mcp_tool", "get_role_holder")]
    assert v2.resolver_auth == "app_sp"


# ---------------------------------------------------------------------------
# ARF v2: concept-based AR lookup
# ---------------------------------------------------------------------------

TP_IRI = "urn:demo:concept:trade-promotion"
COMMERCIAL_IRI = "urn:demo:concept:commercial-decision"


def _link_concept(db, relation, iri):
    import uuid as _uuid
    from src.db_models.semantic_links import EntitySemanticLinkDb
    db.add(EntitySemanticLinkDb(
        id=_uuid.uuid4(), entity_id=relation.version_family_id or relation.id,
        entity_type="authority_relation", iri=iri,
    ))
    db.flush()


def _concept_ar(mgr, db, *, slug, iri=TP_IRI, context=None, active=True, **kw):
    from src.controller.authority_resolution_manager import STATUS_ACTIVE
    from src.models.authority_resolution import (
        AuthorityRelationCreate, CriterionInput, PrerequisiteInput, ResourceRefInput,
    )
    rel = mgr.create_relation(db, AuthorityRelationCreate(
        name=f"AR {slug}", slug=slug, domain_context=context,
        resource_refs=[ResourceRefInput(**r) for r in kw.get("resource_refs", [])],
        criteria=[CriterionInput(**c) for c in kw.get("criteria", [])],
        prerequisites=[PrerequisiteInput(**p) for p in kw.get("prerequisites", [])],
        domain_ids=kw.get("domain_ids", []),
    ))
    if active:
        rel.status = STATUS_ACTIVE
    for k in ("maturity_level_order", "dna_magnitude"):
        if k in kw:
            setattr(rel, k, kw[k])
    if iri:
        _link_concept(db, rel, iri)
    return rel


def test_find_authority_by_concept_returns_unique_match(db_session):
    from src.controller.authority_resolution_manager import AuthorityResolutionManager

    mgr = AuthorityResolutionManager()
    _concept_ar(mgr, db_session, slug="tp-de", context={"brand": "Alpha Cola", "market": "DE"})
    _concept_ar(mgr, db_session, slug="tp-fr", context={"brand": "Alpha Cola", "market": "FR"})
    _concept_ar(mgr, db_session, slug="tp-draft", active=False)
    _concept_ar(mgr, db_session, slug="unrelated", iri="urn:demo:concept:other")
    db_session.commit()

    out = mgr.find_authority_for_concept(db_session, TP_IRI, {"brand": "alpha cola", "market": "DE"})
    assert out["resolved"] == "tp-de"
    slugs = [c["family_slug"] for c in out["candidates"]]
    assert slugs == ["tp-de", "tp-fr"]  # draft + unrelated excluded, conflict ranked last
    assert out["candidates"][0]["match_score"] == 1.0
    assert out["candidates"][1]["context_conflicts"] == ["market"]


def test_find_authority_by_concept_ambiguous_returns_candidates(db_session):
    from src.controller.authority_resolution_manager import AuthorityResolutionManager

    mgr = AuthorityResolutionManager()
    _concept_ar(mgr, db_session, slug="amb-a", maturity_level_order=3, dna_magnitude=0.1)
    _concept_ar(mgr, db_session, slug="amb-b", maturity_level_order=3, dna_magnitude=0.1)
    db_session.commit()

    out = mgr.find_authority_for_concept(db_session, TP_IRI, {})
    assert out["resolved"] is None
    assert out["reason"] == "ambiguous"
    assert {c["family_slug"] for c in out["candidates"]} == {"amb-a", "amb-b"}


def test_concept_lookup_tiebreaks_on_maturity_then_dna(db_session):
    from src.controller.authority_resolution_manager import AuthorityResolutionManager

    mgr = AuthorityResolutionManager()
    _concept_ar(mgr, db_session, slug="tb-low", maturity_level_order=2, dna_magnitude=0.01)
    _concept_ar(mgr, db_session, slug="tb-high", maturity_level_order=4, dna_magnitude=0.2)
    _concept_ar(mgr, db_session, slug="tb-high-better", maturity_level_order=4, dna_magnitude=0.1)
    db_session.commit()
    assert mgr.find_authority_for_concept(db_session, TP_IRI)["resolved"] == "tb-high-better"


def test_concept_hierarchy_hop_matches_parent_concept(db_session):
    """An AR linked to a broader concept is found one hop out; a direct link wins."""
    from types import SimpleNamespace
    from src.controller.authority_resolution_manager import AuthorityResolutionManager

    class _Sem:
        def get_concept_details(self, iri):
            if iri == TP_IRI:
                return SimpleNamespace(label="Trade Promotion", parent_concepts=[COMMERCIAL_IRI],
                                       related_concepts=[])
            return None

        def find_concept_iris_by_label(self, text, limit=20):
            return []

    mgr = AuthorityResolutionManager()
    _concept_ar(mgr, db_session, slug="broad-gate", iri=COMMERCIAL_IRI)
    db_session.commit()

    assert mgr.find_authority_for_concept(db_session, TP_IRI)["reason"] == "no_authority"
    out = mgr.find_authority_for_concept(db_session, TP_IRI, semantic_models_manager=_Sem())
    assert out["resolved"] == "broad-gate"
    assert out["candidates"][0]["hops"] == 1
    assert out["candidates"][0]["matched_via"] == COMMERCIAL_IRI

    _concept_ar(mgr, db_session, slug="direct-gate")
    db_session.commit()
    assert mgr.find_authority_for_concept(
        db_session, TP_IRI, semantic_models_manager=_Sem())["resolved"] == "direct-gate"


def test_unmet_prerequisite_demotes_but_does_not_remove_candidate(db_session):
    from src.controller.authority_resolution_manager import AuthorityResolutionManager, STATUS_ACTIVE

    mgr = AuthorityResolutionManager()
    gate = _concept_ar(mgr, db_session, slug="cleared-markets", iri=None, criteria=[dict(
        name="market", rule="obj.market IN ['DE']", failure_message="market not cleared")])
    gate.status = STATUS_ACTIVE
    _concept_ar(mgr, db_session, slug="gated-tp", maturity_level_order=5,
                prerequisites=[dict(prerequisite_family_slug="cleared-markets")])
    _concept_ar(mgr, db_session, slug="fallback-tp", maturity_level_order=1)
    db_session.commit()

    blocked = mgr.find_authority_for_concept(db_session, TP_IRI, request={"market": "FR"})
    assert blocked["resolved"] == "fallback-tp"
    assert [c["family_slug"] for c in blocked["candidates"]] == ["fallback-tp", "gated-tp"]
    assert blocked["candidates"][1]["unmet_prerequisites"] == ["cleared-markets"]

    cleared = mgr.find_authority_for_concept(db_session, TP_IRI, request={"market": "DE"})
    assert cleared["resolved"] == "gated-tp"  # viable now; higher maturity wins


def test_concept_lookup_domain_filter_and_label_equivalence(db_session):
    """Requested domain narrows candidates; a caller value that is a concept's
    label matches an AR whose ref points at that concept's IRI."""
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.db_models.data_domains import DataDomain

    class _Sem:
        def get_concept_details(self, iri):
            return None

        def find_concept_iris_by_label(self, text, limit=20):
            return ["urn:demo:market:DE"] if text.lower() == "germany" else []

    db_session.add(DataDomain(id="00000000-0000-4000-8000-0000000000aa", name="Commercial Ops X", created_by="test"))
    db_session.flush()
    mgr = AuthorityResolutionManager()
    _concept_ar(mgr, db_session, slug="dom-other")
    _concept_ar(mgr, db_session, slug="dom-commercial",
                domain_ids=["00000000-0000-4000-8000-0000000000aa"],
                resource_refs=[dict(field_path="domain_context.market", ref_type="ontos_entity",
                                    entity_type="business_concept", entity_id="urn:demo:market:DE")])
    db_session.commit()

    out = mgr.find_authority_for_concept(db_session, TP_IRI, {"market": "Germany"},
                                         domains=["commercial ops x"], semantic_models_manager=_Sem())
    assert out["resolved"] == "dom-commercial"
    top = out["candidates"][0]
    assert top["domain_overlap"] == ["Commercial Ops X"]
    assert top["context_matches"] == ["market"]


@pytest.mark.asyncio
async def test_find_authority_for_concept_tool(db_session):
    from unittest.mock import MagicMock
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.tools.authority_resolution import FindAuthorityForConceptTool
    from src.tools.base import ToolContext

    mgr = AuthorityResolutionManager()
    _concept_ar(mgr, db_session, slug="tool-tp")
    db_session.commit()
    tool = FindAuthorityForConceptTool()
    ctx = ToolContext(db=db_session, settings=MagicMock())
    ok = await tool.execute(ctx, concept_iri=TP_IRI, context={"market": "DE"})
    assert ok.success and ok.data["resolved"] == "tool-tp"
    missing = await tool.execute(ctx)
    assert not missing.success


def test_mcp_client_build_failure_is_no_authority_not_500(db_session):
    from src.controller.authority_resolution_manager import (
        AuthorityResolutionManager, VERDICT_NO_AUTHORITY,
    )

    def _boom():
        raise RuntimeError("cannot verify workspace client")

    mgr = AuthorityResolutionManager()
    _make_mcp_ar(mgr, db_session, slug="boom-gate")
    db_session.commit()
    out = mgr.resolve(db_session, "boom-gate", {"market": "DE"}, record=False, require_active=False,
                      obo_ws_factory=_boom, mcp_client_factory=_mcp_factory(response={"approver": "x"}))
    assert out["verdict"] == VERDICT_NO_AUTHORITY
    assert "cannot verify" in out["reason"]

    def _raising_client(ws, svc, deadline=None):
        raise AttributeError("'list' object has no attribute 'get'")
    out = mgr.resolve(db_session, "boom-gate", {"market": "DE"}, record=False, require_active=False,
                      obo_ws_factory=lambda: object(), mcp_client_factory=_raising_client)
    assert out["verdict"] == VERDICT_NO_AUTHORITY


def test_mcp_cache_policy_never_caches_obo_or_dry_runs(db_session):
    """OBO results are caller-scoped and never cached; app-SP results are cached
    only by recorded (production) resolves, never by dry runs."""
    from src.controller.authority_resolution_manager import AuthorityResolutionManager, STATUS_ACTIVE
    from src.repositories.authority_resolution_repository import authority_resource_ref_repo

    mgr = AuthorityResolutionManager()
    obo = _make_mcp_ar(mgr, db_session, slug="cache-obo")
    sp = _make_mcp_ar(mgr, db_session, slug="cache-sp", resolver_auth="app_sp")
    obo.status = sp.status = STATUS_ACTIVE
    db_session.commit()
    ws = lambda: object()  # noqa: E731
    cached = lambda rel: authority_resource_ref_repo.list_for_relation(  # noqa: E731
        db_session, relation_id=rel.id)[0].cached_label

    mgr.resolve(db_session, "cache-obo", {"market": "DE"}, record=True, obo_ws_factory=ws,
                mcp_client_factory=_mcp_factory(response={"approver": "secret@example.com"}))
    assert cached(obo) is None

    mgr.resolve(db_session, "cache-sp", {"market": "DE"}, record=False, app_ws_factory=ws,
                mcp_client_factory=_mcp_factory(response={"approver": "sp@example.com"}))
    assert cached(sp) is None
    mgr.resolve(db_session, "cache-sp", {"market": "DE"}, record=True, app_ws_factory=ws,
                mcp_client_factory=_mcp_factory(response={"approver": "sp@example.com"}))
    assert cached(sp) == "sp@example.com"


def test_find_concept_iris_by_label_exact_and_case_insensitive():
    from types import SimpleNamespace
    from rdflib import Dataset, Literal, URIRef
    from rdflib.namespace import RDFS, SKOS
    from src.controller.semantic_models_manager import SemanticModelsManager

    ds = Dataset()
    g = ds.graph(URIRef("urn:ctx:demo"))
    g.add((URIRef("urn:demo:market:DE"), SKOS.prefLabel, Literal("DE")))
    g.add((URIRef("urn:demo:market:DE"), RDFS.label, Literal("Germany", lang="en")))
    g.add((URIRef("urn:demo:concept:trade"), RDFS.label, Literal("Trade DE Promotion")))
    fake = SimpleNamespace(_graph=ds)
    find = SemanticModelsManager.find_concept_iris_by_label
    assert find(fake, "DE") == ["urn:demo:market:DE"]
    assert find(fake, "germany") == ["urn:demo:market:DE"]
    assert find(fake, 'De"; DROP') == []



# ---------------------------------------------------------------------------
# Review pass 3: activation integrity, evidence safety, lifecycle
# ---------------------------------------------------------------------------


def _user(email, groups=None):
    from types import SimpleNamespace
    return SimpleNamespace(email=email, username=email, user=email, groups=groups or [])


def test_affirm_requires_the_named_principal(db_session):
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.models.authority_resolution import AuthorityRelationCreate, AffirmationInput

    mgr = AuthorityResolutionManager()
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(name="Affirm AR", affirmations=[
        AffirmationInput(role="Approver", principal="Alice@x.com"),
        AffirmationInput(role="Board", principal="board-group", principal_type="group"),
    ]))
    db_session.commit()
    by_principal = {a["principal"]: a for a in mgr.to_read_dict(db_session, rel)["affirmations"]}
    alice, board = by_principal["Alice@x.com"], by_principal["board-group"]
    with pytest.raises(PermissionError):
        mgr.affirm(db_session, alice["id"], affirmed_by="mallory@x.com", user=_user("mallory@x.com"))
    with pytest.raises(PermissionError):
        mgr.affirm(db_session, board["id"], affirmed_by="mallory@x.com", user=_user("mallory@x.com"))
    assert mgr.affirm(db_session, alice["id"], affirmed_by="alice@x.com", user=_user("alice@x.com")).affirmed
    assert mgr.affirm(db_session, board["id"], affirmed_by="bob@x.com",
                      user=_user("bob@x.com", groups=["Board-Group"])).affirmed


def test_review_context_and_submit_require_the_named_reviewer(db_session):
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.models.authority_resolution import AuthorityRelationCreate, AffirmationInput

    mgr = AuthorityResolutionManager()
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(name="Review AR", affirmations=[
        AffirmationInput(role="business", principal="rev@x.com", is_approver=False, is_reviewer=True),
    ]))
    db_session.commit()
    with pytest.raises(PermissionError):
        mgr.get_review_context(db_session, rel.id, "rev@x.com", user=_user("other@x.com"))
    ctx = mgr.get_review_context(db_session, rel.id, "rev@x.com", user=_user("rev@x.com"))
    with pytest.raises(PermissionError):
        mgr.submit_review(db_session, ctx["participant_id"], {"q": "a"}, user=_user("other@x.com"))
    assert mgr.submit_review(db_session, ctx["participant_id"], {"q": "a"},
                             user=_user("rev@x.com")).review_status == "completed"


def test_empty_evidence_sample_fails_the_run_and_leaves_dna_unmeasured(db_session):
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.models.authority_resolution import AuthorityRelationCreate
    from src.repositories.authority_resolution_repository import authority_dna_run_repo

    mgr = AuthorityResolutionManager()
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(name="No evidence AR"))
    db_session.commit()
    with pytest.raises(ValueError, match="No evidence rows"):
        mgr.compute_dnaco(db_session, rel.id, rows=[])
    runs = authority_dna_run_repo.list_for_relation(db_session, relation_id=rel.id)
    assert runs[0].status == "failed"
    assert rel.dna_magnitude is None
    _, err = mgr.set_status(db_session, rel.id, "active")
    assert "not been measured" in err


def test_collect_evidence_keeps_raw_columns_and_applies_aliases(monkeypatch):
    from types import SimpleNamespace
    from src.controller.authority_resolution_manager import AuthorityResolutionManager

    mgr = AuthorityResolutionManager()
    monkeypatch.setattr(mgr, "_read_evidence_rows", lambda binding: [{"approver": "a@x", "budget_usd": 5}])
    rel = SimpleNamespace(evidence_sources=[{"type": "delta_table", "ref": "c.s.t",
                                             "column_map": {"actor_identity": "approver"}}],
                          evidence_binding=None)
    rows = mgr._collect_evidence(rel)
    assert rows[0]["actor_identity"] == "a@x"
    assert rows[0]["budget_usd"] == 5


def test_zero_dna_ceiling_is_respected(db_session):
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.models.authority_resolution import AuthorityRelationCreate, AffirmationInput

    mgr = AuthorityResolutionManager()
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(
        name="Zero tolerance", dna_max_threshold=0.0,
        affirmations=[AffirmationInput(role="Approver", principal="a@x.com")]))
    db_session.commit()
    aff = mgr.to_read_dict(db_session, rel)["affirmations"][0]
    mgr.affirm(db_session, aff["id"], affirmed_by="a@x.com", user=_user("a@x.com"))
    rel.dna_magnitude = 0.1
    _, err = mgr.set_status(db_session, rel.id, "active")
    assert err and "exceeds the maximum 0.0" in err


def test_set_status_rejects_unknown_status(db_session):
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.models.authority_resolution import AuthorityRelationCreate

    mgr = AuthorityResolutionManager()
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(name="Status AR"))
    _, err = mgr.set_status(db_session, rel.id, "activ")
    assert err and "Unknown status" in err
    assert rel.status == "draft"


def test_replacing_participants_on_active_ar_requires_reaffirmation(db_session):
    from src.controller.authority_resolution_manager import AuthorityResolutionManager, STATUS_ACTIVE
    from src.models.authority_resolution import (
        AuthorityRelationCreate, AuthorityRelationUpdate, AffirmationInput,
    )

    mgr = AuthorityResolutionManager()
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(name="Reaffirm AR"))
    rel.status = STATUS_ACTIVE
    db_session.commit()
    updated = mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(
        affirmations=[AffirmationInput(role="Approver", principal="new@x.com")]))
    assert updated.status == "needs_review"


def test_update_recompute_scores_the_new_criteria(db_session, monkeypatch):
    """After a criteria replace, the recompute must not use the stale collection."""
    from src.controller.authority_resolution_manager import AuthorityResolutionManager, STATUS_ACTIVE
    from src.models.authority_resolution import (
        AuthorityRelationCreate, AuthorityRelationUpdate, CriterionInput, AffirmationInput,
    )

    mgr = AuthorityResolutionManager()
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(
        name="Stale AR", dna_max_threshold=0.5,
        criteria=[CriterionInput(name="loose", rule="obj.value <= 100")],
        affirmations=[AffirmationInput(role="Approver", principal="a@x.com")]))
    db_session.commit()
    _ = list(rel.criteria)  # load the collection
    rel.status = STATUS_ACTIVE
    db_session.commit()
    monkeypatch.setattr(mgr, "_collect_evidence", lambda _rel: [{"actor_identity": "a", "value": 50}])
    updated = mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(
        criteria=[CriterionInput(name="strict", rule="obj.value <= 10", failure_message="over")]))
    assert updated.status == "needs_review"  # the strict rule diverges on every row


@pytest.mark.parametrize("bad", [
    "1=1 UNION SELECT * FROM secrets.hr.salaries",
    "x = 1; DROP TABLE t",
    "x = 1 -- comment",
    "read_files('/Volumes/x') IS NOT NULL",
    "x IN (SELECT y FROM other)",
    "a = 'x\\'' UNION SELECT * FROM other_cat.s.t --'",
])
def test_row_filter_rejects_injection(bad):
    from src.controller.authority_resolution_manager import validate_row_filter
    with pytest.raises(ValueError):
        validate_row_filter(bad)


def test_row_filter_and_fqn_accept_simple_predicates():
    from src.controller.authority_resolution_manager import validate_row_filter, validate_table_fqn
    assert validate_row_filter("region = 'EMEA' AND (amount >= 10 OR flag IS NULL) AND k IN ('a', 'b')")
    assert validate_table_fqn("demo.commercial.promotion_approvals")
    with pytest.raises(ValueError):
        validate_table_fqn("t; DROP TABLE x")


def test_evidence_with_bad_filter_rejected_at_write_time(db_session):
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.models.authority_resolution import AuthorityRelationCreate, EvidenceSource

    with pytest.raises(ValueError):
        AuthorityResolutionManager().create_relation(db_session, AuthorityRelationCreate(
            name="Inject AR", evidence_sources=[EvidenceSource(
                ref="c.s.t", row_filter="1=1 UNION SELECT * FROM x")]))


def test_delete_protects_family_anchor_moves_slug_and_cleans_up(db_session):
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.repositories.authority_resolution_repository import authority_prerequisite_repo

    mgr = AuthorityResolutionManager()
    v1 = _make_ar(mgr, db_session, slug="del-fam", name="Del v1")
    v2 = mgr.create_new_version(db_session, v1.id, "2.0.0")
    db_session.commit()
    with pytest.raises(ValueError, match="first version"):
        mgr.delete_relation(db_session, v1.id)

    # A slug on a non-anchor row moves to a remaining sibling.
    v1.slug = None
    db_session.flush()
    v2.slug = "del-fam"
    db_session.commit()
    assert mgr.delete_relation(db_session, v2.id)
    assert v1.slug == "del-fam"

    # Last version: refused while depended on; afterwards edges + links are gone.
    dep = _make_ar(mgr, db_session, slug="del-dep", name="Dependent",
                   prerequisites=[dict(prerequisite_family_slug="del-fam")])
    _link_concept(db_session, v1, TP_IRI)
    db_session.commit()
    with pytest.raises(ValueError, match="prerequisite of del-dep"):
        mgr.delete_relation(db_session, v1.id)
    mgr.delete_relation(db_session, dep.id)
    assert mgr.delete_relation(db_session, v1.id)
    assert authority_prerequisite_repo.list_dependents(db_session, prerequisite_family_slug="del-fam") == []
    assert mgr.find_authority_for_concept(db_session, TP_IRI)["candidates"] == []


def test_malformed_rule_rejected_on_write_and_conflict_at_resolve(db_session):
    import uuid as _uuid
    from src.common import authority_resolution_dna as dna
    from src.controller.authority_resolution_manager import AuthorityResolutionManager, VERDICT_CONFLICT
    from src.db_models.authority_resolution import AuthorityCriterionDb
    from src.db_models.compliance import CompliancePolicyDb

    mgr = AuthorityResolutionManager()
    with pytest.raises(ValueError, match="does not parse"):
        _make_ar(mgr, db_session, slug="bad-rule", name="Bad", criteria=[dict(name="b", rule="obj.value <=")])

    rel = _make_ar(mgr, db_session, slug="legacy-bad", name="Legacy bad")
    pid = str(_uuid.uuid4())
    db_session.add(CompliancePolicyDb(id=pid, slug=f"p-{pid[:8]}", name="broken", rule="ASSERT obj.value <=",
                                      category="Authority Decision", severity="high", is_active=True))
    db_session.add(AuthorityCriterionDb(id=str(_uuid.uuid4()), relation_id=rel.id, compliance_policy_id=pid,
                                        direction="neutral", weight=1.0, display_order=0, enabled=True))
    db_session.commit()
    out = mgr.resolve(db_session, "legacy-bad", {"value": 1}, record=False, require_active=False)
    assert out["verdict"] == VERDICT_CONFLICT
    crit = dna.Criterion(code="broken", rule="ASSERT obj.value <=", message=None, direction="neutral",
                         weight=1.0, dimension="people")
    assert dna.evaluate_row([crit], {"value": 1}).diverged is False



def test_resaving_unchanged_participants_keeps_signoffs_and_status(db_session):
    from src.controller.authority_resolution_manager import AuthorityResolutionManager, STATUS_ACTIVE
    from src.models.authority_resolution import (
        AuthorityRelationCreate, AuthorityRelationUpdate, AffirmationInput,
    )

    mgr = AuthorityResolutionManager()
    parts = [AffirmationInput(role="Approver", principal="a@x.com")]
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(name="Keep signoffs", affirmations=parts))
    db_session.commit()
    aff = mgr.to_read_dict(db_session, rel)["affirmations"][0]
    mgr.affirm(db_session, aff["id"], affirmed_by="a@x.com", user=_user("a@x.com"))
    rel.status = STATUS_ACTIVE
    db_session.commit()

    updated = mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(
        description="typo fix", affirmations=parts))
    assert updated.status == STATUS_ACTIVE
    assert mgr.is_fully_affirmed(db_session, rel.id)

    updated = mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(
        affirmations=[AffirmationInput(role="Approver", principal="b@x.com")]))
    assert updated.status == "needs_review"


def test_dnaco_run_fails_on_malformed_linked_rule(db_session):
    import uuid as _uuid
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    from src.db_models.compliance import CompliancePolicyDb
    from src.models.authority_resolution import AuthorityRelationCreate, CriterionInput
    from src.repositories.authority_resolution_repository import authority_dna_run_repo

    pid = str(_uuid.uuid4())
    db_session.add(CompliancePolicyDb(id=pid, slug=f"p-{pid[:8]}", name="broken linked", rule="ASSERT obj.value <=",
                                      category="Governance", severity="high", is_active=True))
    db_session.flush()
    mgr = AuthorityResolutionManager()
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(
        name="Linked broken", criteria=[CriterionInput(policy_id=pid)]))
    db_session.commit()
    with pytest.raises(ValueError, match="malformed"):
        mgr.compute_dnaco(db_session, rel.id, rows=[{"value": 1}])
    assert authority_dna_run_repo.list_for_relation(db_session, relation_id=rel.id)[0].status == "failed"
    assert rel.dna_magnitude is None


def test_assert_detection_ignores_literal_text():
    from src.common import authority_resolution_dna as dna
    assert not dna.has_assert_clause("obj.state = 'ASSERTED'")
    assert dna.has_assert_clause("MATCH (p:PromotionProposal) ASSERT p.market IN ['DE']")
    assert dna.rule_parse_error("ASSERT obj.state = 'ASSERTED'") is None


def test_criterion_rule_with_assert_in_literal_is_prefixed_and_accepted(db_session):
    from src.controller.authority_resolution_manager import AuthorityResolutionManager
    mgr = AuthorityResolutionManager()
    rel = _make_ar(mgr, db_session, slug="asserted-ar", name="Asserted",
                   criteria=[dict(name="state", rule="obj.state = 'ASSERTED'")])
    crit = mgr.to_read_dict(db_session, rel)["criteria"][0]
    assert crit["rule"] == "ASSERT obj.state = 'ASSERTED'"


# ------------------------------------------- team / project / search parity

def _team_and_project(db_session):
    import uuid
    from src.db_models.projects import ProjectDb
    from src.db_models.teams import TeamDb
    team = TeamDb(id=str(uuid.uuid4()), name=f"Governance {uuid.uuid4().hex[:6]}", created_by="a@x", updated_by="a@x")
    project = ProjectDb(id=str(uuid.uuid4()), name=f"Promo {uuid.uuid4().hex[:6]}", project_type="TEAM", created_by="a@x", updated_by="a@x")
    db_session.add_all([team, project])
    db_session.flush()
    return team, project


class _RecordingSearch:
    def __init__(self):
        self.upserts, self.removes = [], []

    def upsert_item(self, item):
        self.upserts.append(item)

    def remove_item(self, item_id):
        self.removes.append(item_id)


def test_owner_team_and_project_persist_and_read(db_session):
    """ARs carry an owner team and project like Data Products / Contracts."""
    from src.models.authority_resolution import AuthorityRelationCreate, AuthorityRelationUpdate

    team, project = _team_and_project(db_session)
    mgr = AuthorityResolutionManager()
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(
        name="Scoped AR", owner_team_id=team.id, project_id=project.id))
    db_session.commit()

    read = mgr.to_read_dict(db_session, rel)
    assert (read["owner_team_id"], read["owner_team_name"]) == (team.id, team.name)
    assert (read["project_id"], read["project_name"]) == (project.id, project.name)

    assert [r.id for r in mgr.list_relations(db_session, project_id=project.id)] == [rel.id]
    assert [r.id for r in mgr.list_relations(db_session, owner_team_id=team.id)] == [rel.id]
    assert mgr.list_relations(db_session, project_id="other") == []

    # "" is the dialogs' "none" choice and clears the assignment.
    mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(owner_team_id="", project_id=""))
    db_session.commit()
    read = mgr.to_read_dict(db_session, mgr.get_relation(db_session, rel.id))
    assert read["owner_team_id"] is None and read["project_id"] is None


def test_unknown_team_or_project_is_rejected(db_session):
    from src.models.authority_resolution import AuthorityRelationCreate, AuthorityRelationUpdate

    mgr = AuthorityResolutionManager()
    with pytest.raises(ValueError, match="Team"):
        mgr.create_relation(db_session, AuthorityRelationCreate(name="Bad", owner_team_id="nope"))
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(name="Ok"))
    with pytest.raises(ValueError, match="Project"):
        mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(project_id="nope"))


def test_new_version_keeps_team_and_project(db_session):
    from src.models.authority_resolution import AuthorityRelationCreate

    team, project = _team_and_project(db_session)
    mgr = AuthorityResolutionManager()
    src = mgr.create_relation(db_session, AuthorityRelationCreate(
        name="Versioned scoped AR", owner_team_id=team.id, project_id=project.id))
    db_session.commit()
    v2 = mgr.create_new_version(db_session, src.id, "2.0.0", current_user="a@x")
    assert (v2.owner_team_id, v2.project_id) == (team.id, project.id)


def test_search_index_one_entry_per_family_and_status_timeline(db_session):
    """Create/update/status/new-version/delete keep a single per-family search entry
    fresh, and status changes are written to the Comments timeline."""
    from src.db_models.comments import CommentDb
    from src.models.authority_resolution import AuthorityRelationCreate, AuthorityRelationUpdate

    team, _ = _team_and_project(db_session)
    mgr = AuthorityResolutionManager()
    search = _RecordingSearch()
    mgr.set_search_manager(search)

    rel = mgr.create_relation(db_session, AuthorityRelationCreate(name="Indexed AR", owner_team_id=team.id))
    item = search.upserts[-1]
    assert item.id == f"authority-relation::{rel.id}"
    assert item.type == "authority-relation" and item.feature_id == "authority-resolution"
    assert item.link == f"/authority-resolution/{rel.id}"
    assert item.extra_data["owner"] == team.name and item.extra_data["status"] == "draft"

    mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(description="now searchable"))
    assert search.upserts[-1].description == "now searchable"

    _, err = mgr.set_status(db_session, rel.id, "retired")
    assert err is None and search.upserts[-1].extra_data["status"] == "retired"
    timeline = [c.comment for c in db_session.query(CommentDb).filter(
        CommentDb.entity_type == "authority_relation", CommentDb.entity_id == rel.id)]
    assert any("Status changed from draft to retired" in c for c in timeline)

    db_session.commit()
    v2 = mgr.create_new_version(db_session, rel.id, "2.0.0", current_user="a@x")
    assert {u.id for u in search.upserts} == {f"authority-relation::{rel.id}"}  # same family key
    db_session.commit()

    mgr.delete_relation(db_session, v2.id)
    mgr.delete_relation(db_session, rel.id)
    assert search.removes == [f"authority-relation::{rel.id}"]


def test_get_search_index_items_lists_families(db_session, monkeypatch):
    from contextlib import contextmanager
    from src.models.authority_resolution import AuthorityRelationCreate

    mgr = AuthorityResolutionManager()
    rel = mgr.create_relation(db_session, AuthorityRelationCreate(name="Startup indexed AR"))
    db_session.commit()

    @contextmanager
    def factory():
        yield db_session

    monkeypatch.setattr("src.common.database.get_session_factory", lambda: factory)
    ids = {i.id for i in mgr.get_search_index_items()}
    assert f"authority-relation::{rel.id}" in ids
