"""ARF 1.2.0 batch 2, review fixes: canonical definitions, provenance, template rules, the
activation cycle gate, delete of DNA-only drafts, the single-hash read path, prerequisites of
slug-less versions, and the maturity builder's affirmation check (review items 1-10)."""
from types import SimpleNamespace

import pytest

from src.common import authority_check_templates as templates
from src.common import authority_definition as definition
from src.controller import authority_resolution_manager as manager_module
from src.controller.authority_resolution_manager import (
    AuthorityResolutionManager,
    AuthorityStatusError,
    STATUS_ACTIVE,
    VERDICT_DENIED,
)
from src.db_models.authority_resolution import AuthorityDnaRunDb, AuthorityPrerequisiteDb
from src.models.authority_resolution import (
    AffirmationInput,
    AuthorityRelationCreate,
    AuthorityRelationUpdate,
    CriterionInput,
    EvidenceSource,
)
from src.repositories.authority_resolution_repository import authority_dna_run_repo


def _user(email):
    return SimpleNamespace(email=email, username=email, user=email, groups=[])


def _complete(mgr, db, slug, **kwargs):
    """A complete definition: object, justification, evidence, one enabled check, one approver."""
    kwargs.setdefault("criteria", [CriterionInput(name="Not blocked", rule="ASSERT TRUE")])
    kwargs.setdefault("affirmations", [AffirmationInput(role="Approver", principal="approver@x.com")])
    rel = mgr.create_relation(db, AuthorityRelationCreate(
        name=f"Review {slug}", slug=slug, object_id="dp-1",
        justification_chain={"policy_id": "pol-1"},
        evidence_sources=[EvidenceSource(type="delta_table", ref="c.s.t", column_map={"actor_identity": "a"})],
        **kwargs,
    ), current_user="author@x.com", caller_is_admin=True)
    db.commit()
    return rel


# ---------------------------------------------------------- item 2: canonical form

def test_canonical_drops_absent_and_empty_nested_values():
    assert definition.canonical({"a": None, "b": {}, "c": [], "d": "", "e": 1}) == {"e": 1.0}


def test_stored_and_resent_unchanged_definition_hash_alike(db_session):
    mgr = AuthorityResolutionManager()
    rel = _complete(mgr, db_session, "rv-same", criteria=[
        CriterionInput(name="Cap", rule="obj.value <= 10", order=1),
        CriterionInput(name="Who", rule="obj.actor_identity != 'x'", order=2),
    ])
    before = mgr.definition_hash(db_session, rel)
    # The dialog re-sends the same definition: display order 0, 1 instead of the stored 1, 2,
    # and evidence without the defaults the stored row holds.
    mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(
        criteria=[CriterionInput(name="Cap", rule="obj.value <= 10", order=0),
                  CriterionInput(name="Who", rule="obj.actor_identity != 'x'", order=1)],
        evidence_sources=[EvidenceSource(type="delta_table", ref="c.s.t", column_map={"actor_identity": "a"})],
    ), current_user="someone@x.com")
    db_session.commit()
    assert mgr.definition_hash(db_session, rel) == before
    assert rel.definition_edited_by == "author@x.com"


def test_description_only_edit_of_an_active_ar_with_evidence_sources_is_not_refused(db_session):
    mgr = AuthorityResolutionManager()
    rel = _complete(mgr, db_session, "rv-meta")
    rel.status = STATUS_ACTIVE
    db_session.commit()
    updated = mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(
        description="a new note",
        evidence_sources=[EvidenceSource(type="delta_table", ref="c.s.t", column_map={"actor_identity": "a"})],
    ))
    assert updated.description == "a new note"
    assert updated.status == STATUS_ACTIVE


def test_a_real_change_to_evidence_is_still_a_definition_change(db_session):
    from src.controller.authority_resolution_manager import AuthorityImmutableError
    mgr = AuthorityResolutionManager()
    rel = _complete(mgr, db_session, "rv-real")
    rel.status = STATUS_ACTIVE
    db_session.commit()
    with pytest.raises(AuthorityImmutableError):
        mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(
            evidence_sources=[EvidenceSource(type="delta_table", ref="c.s.t", column_map={"actor_identity": "b"})]))


# ----------------------------------------------- item 1: provenance from legacy saves

def test_a_legacy_migrated_check_survives_a_save_and_keeps_its_provenance(db_session):
    mgr = AuthorityResolutionManager()
    rel = _complete(mgr, db_session, "rv-legacy", criteria=[CriterionInput(
        id=None, name="Migrated", rule="obj.value <= 1",
        copied_from={"kind": "migrated", "label": "Old policy", "id": "p-1"})])
    echoed = mgr.to_read_dict(db_session, rel)["criteria"][0]
    mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(criteria=[CriterionInput(
        id=echoed["id"], name="Migrated", rule="obj.value <= 1", copied_from=echoed["copied_from"])]))
    db_session.commit()
    assert mgr.to_read_dict(db_session, rel)["criteria"][0]["copied_from"]["kind"] == "migrated"


# ------------------------------------------------- item 6: template rules are copied once

def test_a_template_rule_change_in_the_registry_does_not_alter_a_saved_ar_or_its_hash(db_session, monkeypatch):
    mgr = AuthorityResolutionManager()
    rel = _complete(mgr, db_session, "rv-tpl", criteria=[CriterionInput(template_key="mfa_required")])
    stored_rule = mgr.to_read_dict(db_session, rel)["criteria"][0]["rule"]
    before = mgr.definition_hash(db_session, rel)

    changed = templates.CheckTemplate(key="mfa_required", name="MFA required", description="x",
                                      rule="ASSERT obj.mfa_verified = False", failure_message="changed",
                                      dimension="policy")
    monkeypatch.setattr(manager_module, "get_template", lambda key: changed if key == "mfa_required" else None)
    # The dialog re-sends the saved check by its template key.
    mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(
        criteria=[CriterionInput(template_key="mfa_required")]))
    db_session.commit()
    row = mgr.to_read_dict(db_session, rel)["criteria"][0]
    assert row["rule"] == stored_rule
    assert mgr.definition_hash(db_session, rel) == before

    # A check added now takes the registry's current text.
    fresh = _complete(mgr, db_session, "rv-tpl-new", criteria=[CriterionInput(template_key="mfa_required")])
    assert mgr.to_read_dict(db_session, fresh)["criteria"][0]["rule"] == "ASSERT obj.mfa_verified = False"


# ------------------------------------------------ item 7: the activation cycle gate

def test_activating_a_version_that_closes_a_cycle_through_another_active_version_is_refused(db_session):
    """A v2 requires B. B's active version is changed to require A. Activating A v2 would close A→B→A."""
    mgr = AuthorityResolutionManager()
    a1 = _complete(mgr, db_session, "cyc-a")
    _complete(mgr, db_session, "cyc-b")
    a2 = mgr.create_new_version(db_session, a1.id, "2.0.0", current_user="author@x.com")
    db_session.commit()
    mgr.update_relation(db_session, a2.id, AuthorityRelationUpdate(
        prerequisites=[{"prerequisite_family_slug": "cyc-b"}]))
    db_session.commit()
    # B becomes active with an edge back to A (saved while A's active version had no edges).
    b = mgr.resolve_relation_ref(db_session, "cyc-b")
    mgr.update_relation(db_session, b.id, AuthorityRelationUpdate(
        prerequisites=[{"prerequisite_family_slug": "cyc-a"}]))
    b.status = STATUS_ACTIVE
    db_session.commit()
    mgr.compute_dnaco(db_session, a2.id, rows=[{"actor_identity": "a"}])
    db_session.commit()
    with pytest.raises(AuthorityStatusError) as exc:
        mgr._check_activation(db_session, mgr.get_relation(db_session, a2.id))
    assert exc.value.params["reason"] == "prerequisite_cycle"
    assert exc.value.params["prerequisite"] == "cyc-b"


def test_without_the_cycle_the_gate_moves_on_to_the_approvals(db_session):
    mgr = AuthorityResolutionManager()
    a1 = _complete(mgr, db_session, "nocyc-a")
    _complete(mgr, db_session, "nocyc-b")
    a2 = mgr.create_new_version(db_session, a1.id, "2.0.0", current_user="author@x.com")
    db_session.commit()
    mgr.update_relation(db_session, a2.id, AuthorityRelationUpdate(
        prerequisites=[{"prerequisite_family_slug": "nocyc-b"}]))
    mgr.compute_dnaco(db_session, a2.id, rows=[{"actor_identity": "a"}])
    db_session.commit()
    with pytest.raises(AuthorityStatusError) as exc:
        mgr._check_activation(db_session, mgr.get_relation(db_session, a2.id))
    assert exc.value.params["reason"] == "affirmations_missing"


# ------------------------------------------------- item 9: one hash, no DNA lookups in lists

def test_the_list_read_path_loads_no_dna_runs_and_the_detail_path_hashes_once(db_session, monkeypatch):
    mgr = AuthorityResolutionManager()
    rel = _complete(mgr, db_session, "rv-list")
    mgr.compute_dnaco(db_session, rel.id, rows=[{"actor_identity": "a"}])
    db_session.commit()

    def no_runs(*args, **kwargs):
        raise AssertionError("the list view must not load DNA runs per row")
    monkeypatch.setattr(authority_dna_run_repo, "list_for_relation", no_runs)
    row = mgr.to_read_dict(db_session, rel, include_state=False)
    assert row["dna_current"] is None and row["editable"] is None
    assert row["definition_hash"]

    monkeypatch.undo()
    calls = []
    original = mgr.definition_hash
    monkeypatch.setattr(mgr, "definition_hash", lambda *a, **k: calls.append(1) or original(*a, **k))
    detail = mgr.to_read_dict(db_session, rel)
    assert len(calls) == 1
    assert detail["dna_current"] is True


# -------------------------------------------- item 10: slug-less versions walk their edges

def test_a_version_without_a_slug_still_walks_its_own_prerequisites(db_session):
    mgr = AuthorityResolutionManager()
    _complete(mgr, db_session, "rv-up", criteria=[CriterionInput(name="Cap", rule="obj.value <= 1")])
    upstream = mgr.resolve_relation_ref(db_session, "rv-up")
    upstream.status = STATUS_ACTIVE
    loose = _complete(mgr, db_session, "rv-loose")
    loose.slug = None
    db_session.add(AuthorityPrerequisiteDb(id="rv-edge", relation_id=loose.id,
                                           prerequisite_family_slug="rv-up", required=True, display_order=0))
    db_session.commit()
    out = mgr.resolve(db_session, loose.id, {"value": 5}, record=False, require_active=False)
    assert out["verdict"] == VERDICT_DENIED
    assert "blocked by prerequisite ar:rv-up" in out["reason"]


# -------------------------------------------- item 5: the maturity builder agrees

def test_the_maturity_dict_treats_an_earlier_draft_affirmation_as_not_affirmed(db_session):
    from src.controller.entity_dict_builder import build_authority_relation_dict
    mgr = AuthorityResolutionManager()
    rel = _complete(mgr, db_session, "rv-mat")
    aff = mgr.to_read_dict(db_session, rel)["affirmations"][0]
    mgr.affirm(db_session, aff["id"], affirmed_by="approver@x.com", user=_user("approver@x.com"))
    db_session.commit()
    assert build_authority_relation_dict(db_session, rel.id)["fully_affirmed"] is True
    mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(object_id="dp-2"))
    db_session.commit()
    assert build_authority_relation_dict(db_session, rel.id)["fully_affirmed"] is False


# ---------------------------------------------------- item 3: the demo pack matches the models

def _pack_inserts(text):
    import re
    out = {}
    for m in re.finditer(r"INSERT INTO (\w+) \(([^)]*)\)", text):
        out.setdefault(m.group(1), []).append([c.strip() for c in m.group(2).split(",")])
    return out


def test_the_arf_demo_pack_matches_the_authority_models():
    from pathlib import Path
    import src.db_models.authority_resolution  # noqa: F401 - registers the tables
    import src.db_models.compliance  # noqa: F401
    import src.db_models.maturity  # noqa: F401
    from src.common.database import Base

    pack = (Path(__file__).resolve().parents[2] / "data" / "demo_data_arf.sql").read_text()
    inserts = _pack_inserts(pack)
    for table in ("authority_criteria", "authority_prerequisites", "compliance_policies"):
        model = Base.metadata.tables[table]
        for columns in inserts[table]:
            unknown = set(columns) - {c.name for c in model.columns}
            assert not unknown, f"{table} inserts unknown columns {unknown}"
            required = {c.name for c in model.columns
                        if not c.nullable and c.default is None and c.server_default is None}
            assert required <= set(columns), f"{table} misses required {required - set(columns)}"
    # The retired shapes are gone from the pack.
    assert all("compliance_policy_id" not in cols for cols in inserts["authority_criteria"])
    assert all("relation_family_slug" not in cols for cols in inserts["authority_prerequisites"])
    # Every check a maturity gate points at is still defined in the pack.
    import re
    gate_policies = set(re.findall(r"'(0110[0-9a-f-]{32})', true", pack))
    defined = set(re.findall(r"^\('(0110[0-9a-f-]{32})'", pack, re.M))
    assert gate_policies and gate_policies <= defined
