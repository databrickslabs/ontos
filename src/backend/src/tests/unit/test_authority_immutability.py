"""ARF 1.2.0 batch 2, commit 3: immutable versions, the definition hash and the activation gates
(#859 review B5, B6, S3).

Covers: the canonical hash (what it covers and what it ignores); PUT on an active or older
version is 409 with a New Version pointer while metadata still saves; a draft edit clears the
measurement and makes earlier affirmations stale; activation needs an enabled check, a current
measurement and current approvals; the transition table; needs_review comes back only with
fresh affirmations.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.common import authority_definition as definition
from src.controller.authority_resolution_manager import (
    AuthorityImmutableError,
    AuthorityResolutionManager,
    AuthorityStatusError,
    NO_ENABLED_CHECKS_MESSAGE,
    REASON_NO_ENABLED_CHECKS,
    STATUS_ACTIVE,
    STATUS_DRAFT,
    STATUS_NEEDS_REVIEW,
    STATUS_RETIRED,
    VERDICT_NO_AUTHORITY,
)
from src.models.authority_resolution import (
    AffirmationInput,
    AuthorityRelationCreate,
    EvidenceSlice,
    AuthorityRelationUpdate,
    CriterionInput,
    ResourceRefInput,
)


def _user(email):
    return SimpleNamespace(email=email, username=email, user=email, groups=[])


def _pass():
    return [CriterionInput(name="Not blocked", rule="ASSERT TRUE")]


def _draft(mgr, db, slug=None, **kwargs):
    """A complete draft: object, justification and evidence bound, so its structural score is 0."""
    kwargs.setdefault("criteria", _pass())
    kwargs.setdefault("affirmations", [AffirmationInput(role="Approver", principal="approver@x.com")])
    kwargs.setdefault("object_id", "dp-1")
    kwargs.setdefault("justification_chain", {"policy_id": "pol-1"})
    kwargs.setdefault("evidence_slice", EvidenceSlice(action_codes=["approve"]))
    rel = mgr.create_relation(db, AuthorityRelationCreate(name="Imm AR", slug=slug, **kwargs),
                              current_user="author@x.com", caller_is_admin=True)
    db.commit()
    return rel


def _approve_and_measure(mgr, db, rel, rows=({"actor_identity": "a"},)):
    aff = mgr.to_read_dict(db, rel)["affirmations"][0]
    mgr.affirm(db, aff["id"], affirmed_by="approver@x.com", user=_user("approver@x.com"))
    mgr.compute_dnaco(db, rel.id, rows=list(rows))
    db.commit()


# ------------------------------------------------------------ the canonical hash

def _view(**overrides):
    scalars = {"name": "A", "object_id": "dp-1", "dna_max_threshold": 0.3}
    scalars.update(overrides.pop("scalars", {}))
    base = dict(
        criteria=[{"name": "c", "rule": "ASSERT obj.v <= 1", "failure_message": None, "direction": "neutral",
                   "weight": 1.0, "dimension": "people", "display_order": 0, "enabled": True,
                   "copied_from": {"kind": "compliance", "label": "x"}}],
        prerequisites=[], resource_refs=[],
        participants=[{"principal": "a@x.com", "principal_type": "user", "role": "Approver",
                       "business_role_id": None, "role_category": None, "is_approver": True,
                       "is_reviewer": False, "required": True, "sort_order": 0}],
    )
    base.update(overrides)
    return definition.definition_view(scalars, **base)


def test_hash_is_stable_for_the_same_definition():
    assert definition.definition_hash(_view()) == definition.definition_hash(_view())


def test_hash_changes_with_behaviour_and_ignores_the_name():
    base = definition.definition_hash(_view())
    assert definition.definition_hash(_view(scalars={"object_id": "dp-2"})) != base
    assert definition.definition_hash(_view(scalars={"name": "Renamed"})) == base


def test_hash_covers_checks_prerequisites_refs_and_participants():
    base = definition.definition_hash(_view())
    changed_rule = [dict(_view()["criteria"][0], rule="ASSERT obj.v <= 2")]
    assert definition.definition_hash(_view(criteria=changed_rule)) != base
    assert definition.definition_hash(_view(prerequisites=[
        {"prerequisite_family_slug": "up", "required": True, "display_order": 0}])) != base
    assert definition.definition_hash(_view(resource_refs=[
        {"field_path": "actor_identity", "ref_type": "literal", "literal_value": "x"}])) != base
    assert definition.definition_hash(_view(participants=[
        {"principal": "b@x.com", "principal_type": "user", "role": "Approver"}])) != base


def test_hash_ignores_provenance_and_metadata_only_rows():
    base = definition.definition_hash(_view())
    assert definition.definition_hash(_view(criteria=[dict(_view()["criteria"][0], copied_from=None)])) == base
    # The copied_from field is not in CRITERION_KEYS, so a changed provenance is not a change.
    other = dict(_view()["criteria"][0], copied_from={"kind": "template", "label": "other"})
    assert definition.definition_hash(_view(criteria=[other])) == base


def test_hash_canonicalises_blank_numbers_and_row_order():
    assert definition.definition_hash(_view(scalars={"schedule_cron": ""})) == \
        definition.definition_hash(_view(scalars={"schedule_cron": None}))
    assert definition.definition_hash(_view(scalars={"dna_max_threshold": 1})) == \
        definition.definition_hash(_view(scalars={"dna_max_threshold": 1.0}))
    two = _view()["criteria"] + [dict(_view()["criteria"][0], name="d", display_order=1)]
    assert definition.definition_hash(_view(criteria=list(reversed(two)))) == definition.definition_hash(_view(criteria=two))


def test_timestamps_are_hashed_in_utc():
    aware = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=2)))
    naive = datetime(2026, 1, 2, 1, 4, 5)
    assert definition.canonical(aware) == definition.canonical(naive)


# ------------------------------------------------------ immutable active versions

def test_put_on_an_active_ar_with_a_new_rule_is_409_and_nothing_changes(db_session):
    mgr = AuthorityResolutionManager()
    rel = _draft(mgr, db_session, slug="imm-active")
    _approve_and_measure(mgr, db_session, rel)
    assert mgr.set_status(db_session, rel.id, STATUS_ACTIVE, caller_is_admin=True).status == STATUS_ACTIVE

    with pytest.raises(AuthorityImmutableError) as exc:
        mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(criteria=[
            CriterionInput(name="Anything", rule="ASSERT obj.value <= 1000000")]))
    assert exc.value.code == "authority_immutable"
    assert exc.value.http_status == 409
    assert "New Version" in str(exc.value)
    fresh = mgr.get_relation(db_session, rel.id)
    assert [c.rule for c in fresh.criteria] == ["ASSERT TRUE"]


def test_put_on_an_active_ar_with_criteria_emptied_is_refused(db_session):
    mgr = AuthorityResolutionManager()
    rel = _draft(mgr, db_session, slug="imm-empty")
    _approve_and_measure(mgr, db_session, rel)
    mgr.set_status(db_session, rel.id, STATUS_ACTIVE, caller_is_admin=True)
    with pytest.raises(AuthorityImmutableError):
        mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(criteria=[], dna_max_threshold=1.0),
                            caller_is_admin=True)


def test_metadata_still_saves_on_an_active_ar(db_session):
    """The UI saves the whole form; an unchanged definition with new metadata is not a refusal."""
    mgr = AuthorityResolutionManager()
    rel = _draft(mgr, db_session, slug="imm-meta")
    _approve_and_measure(mgr, db_session, rel)
    mgr.set_status(db_session, rel.id, STATUS_ACTIVE, caller_is_admin=True)
    same = AuthorityRelationUpdate(
        name="Imm AR", description="new description", criteria=_pass(),
        affirmations=[AffirmationInput(role="Approver", principal="approver@x.com")],
    )
    updated = mgr.update_relation(db_session, rel.id, same, current_user="someone@x.com")
    assert updated.description == "new description"
    assert updated.status == STATUS_ACTIVE
    assert updated.definition_edited_by == "author@x.com"  # metadata edits do not change the editor


def test_an_older_version_is_immutable_even_as_a_draft(db_session):
    mgr = AuthorityResolutionManager()
    v1 = _draft(mgr, db_session, slug="imm-old")
    v2 = mgr.create_new_version(db_session, v1.id, "2.0.0", current_user="lars@x.com")
    db_session.commit()
    assert mgr.is_editable(db_session, v2) is True
    assert mgr.is_editable(db_session, v1) is False
    with pytest.raises(AuthorityImmutableError):
        mgr.update_relation(db_session, v1.id, AuthorityRelationUpdate(object_id="other"))


def test_read_model_reports_editable_and_the_definition_hash(db_session):
    mgr = AuthorityResolutionManager()
    rel = _draft(mgr, db_session, slug="imm-flags")
    read = mgr.to_read_dict(db_session, rel)
    assert read["editable"] is True
    assert read["definition_hash"] == mgr.definition_hash(db_session, rel)
    assert read["enabled_check_count"] == 1
    assert read["dna_current"] is False
    _approve_and_measure(mgr, db_session, rel)
    assert mgr.to_read_dict(db_session, rel)["dna_current"] is True


# ------------------------------------------------- draft edits and the hash (B6)

def test_a_draft_definition_change_clears_the_measurement_and_stales_the_affirmations(db_session):
    mgr = AuthorityResolutionManager()
    rel = _draft(mgr, db_session, slug="draft-stale")
    _approve_and_measure(mgr, db_session, rel)
    assert mgr.is_fully_affirmed(db_session, rel.id)

    mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(object_id="dp-changed"),
                        current_user="editor@x.com")
    db_session.commit()
    fresh = mgr.get_relation(db_session, rel.id)
    assert fresh.dna_magnitude is None
    assert fresh.definition_edited_by == "editor@x.com"
    assert not mgr.is_fully_affirmed(db_session, rel.id)
    read = mgr.to_read_dict(db_session, fresh)
    assert read["affirmations"][0]["affirmed"] is True
    assert read["affirmations"][0]["stale"] is True
    assert read["dna_current"] is False


def test_a_draft_rename_keeps_the_measurement_and_the_affirmations(db_session):
    mgr = AuthorityResolutionManager()
    rel = _draft(mgr, db_session, slug="draft-rename")
    _approve_and_measure(mgr, db_session, rel)
    mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(name="Renamed AR"))
    db_session.commit()
    fresh = mgr.get_relation(db_session, rel.id)
    assert fresh.dna_magnitude is not None
    assert mgr.is_fully_affirmed(db_session, rel.id)


def test_affirming_stores_the_hash_of_the_definition_it_vouches_for(db_session):
    mgr = AuthorityResolutionManager()
    rel = _draft(mgr, db_session, slug="draft-hash")
    aff = mgr.affirm(db_session, mgr.to_read_dict(db_session, rel)["affirmations"][0]["id"],
                     affirmed_by="approver@x.com", user=_user("approver@x.com"))
    assert aff.definition_hash == mgr.definition_hash(db_session, rel)


def test_an_affirmation_of_an_earlier_draft_does_not_count(db_session):
    mgr = AuthorityResolutionManager()
    rel = _draft(mgr, db_session, slug="draft-earlier")
    mgr.affirm(db_session, mgr.to_read_dict(db_session, rel)["affirmations"][0]["id"],
               affirmed_by="approver@x.com", user=_user("approver@x.com"))
    mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(
        criteria=[CriterionInput(name="Other", rule="ASSERT obj.actor_identity != 'x'")]))
    db_session.commit()
    assert not mgr.is_fully_affirmed(db_session, rel.id)


# ------------------------------------------------------------- activation gates

def test_activation_needs_an_enabled_check(db_session):
    mgr = AuthorityResolutionManager()
    rel = _draft(mgr, db_session, slug="gate-checks", criteria=[
        CriterionInput(name="Off", rule="ASSERT obj.value <= 1", enabled=False)])
    _approve_and_measure(mgr, db_session, rel)
    with pytest.raises(AuthorityStatusError) as exc:
        mgr.set_status(db_session, rel.id, STATUS_ACTIVE, caller_is_admin=True)
    assert exc.value.params["reason"] == REASON_NO_ENABLED_CHECKS
    assert exc.value.http_status == 409


def test_an_ar_with_no_enabled_check_resolves_to_no_authority(db_session):
    mgr = AuthorityResolutionManager()
    rel = _draft(mgr, db_session, slug="gate-resolve", criteria=[])
    db_session.commit()
    out = mgr.resolve(db_session, "gate-resolve", {"actor_identity": "anyone"}, record=False, require_active=False)
    assert out["verdict"] == VERDICT_NO_AUTHORITY
    assert out["reason"] == NO_ENABLED_CHECKS_MESSAGE
    assert out["reason_code"] == REASON_NO_ENABLED_CHECKS


def test_activation_refused_when_the_measurement_is_from_an_earlier_definition(db_session):
    mgr = AuthorityResolutionManager()
    rel = _draft(mgr, db_session, slug="gate-stale-run")
    _approve_and_measure(mgr, db_session, rel)
    # The definition moves on (its own measurement is cleared), then a stale magnitude is put back.
    mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(object_id="dp-2"))
    _approve_and_measure(mgr, db_session, rel)
    run = mgr.get_relation(db_session, rel.id)
    run.object_id = "dp-3"  # the definition changes without going through update_relation
    run.dna_magnitude = 0.0
    db_session.commit()
    with pytest.raises(AuthorityStatusError) as exc:
        mgr.set_status(db_session, rel.id, STATUS_ACTIVE, caller_is_admin=True)
    assert exc.value.params["reason"] == "dna_stale"


def test_activation_refused_when_an_approver_only_affirmed_an_earlier_draft(db_session):
    mgr = AuthorityResolutionManager()
    rel = _draft(mgr, db_session, slug="gate-stale-aff")
    _approve_and_measure(mgr, db_session, rel)
    row = mgr.get_relation(db_session, rel.id).affirmations[0]
    row.definition_hash = "an-earlier-definition"
    db_session.commit()
    with pytest.raises(AuthorityStatusError) as exc:
        mgr.set_status(db_session, rel.id, STATUS_ACTIVE, caller_is_admin=True)
    assert exc.value.params["reason"] == "affirmations_stale"


def test_activation_succeeds_on_a_current_measurement_and_current_approvals(db_session):
    mgr = AuthorityResolutionManager()
    rel = _draft(mgr, db_session, slug="gate-ok")
    _approve_and_measure(mgr, db_session, rel)
    active = mgr.set_status(db_session, rel.id, STATUS_ACTIVE, caller_is_admin=True)
    assert active.status == STATUS_ACTIVE
    assert active.activated_at is not None


# --------------------------------------------------------- transitions (S3)

def test_retired_goes_back_only_to_active_and_retiring_clears_affirmations(db_session):
    mgr = AuthorityResolutionManager()
    rel = _draft(mgr, db_session, slug="trans-retire")
    _approve_and_measure(mgr, db_session, rel)
    mgr.set_status(db_session, rel.id, STATUS_ACTIVE, caller_is_admin=True)
    mgr.set_status(db_session, rel.id, STATUS_RETIRED, caller_is_admin=True)
    assert not mgr.is_fully_affirmed(db_session, rel.id)
    with pytest.raises(AuthorityStatusError) as exc:
        mgr.set_status(db_session, rel.id, STATUS_DRAFT, caller_is_admin=True)
    assert exc.value.params["reason"] == "transition_not_allowed"


def test_a_needs_review_version_that_was_active_cannot_become_a_draft(db_session):
    mgr = AuthorityResolutionManager()
    rel = _draft(mgr, db_session, slug="trans-was-active")
    _approve_and_measure(mgr, db_session, rel)
    mgr.set_status(db_session, rel.id, STATUS_ACTIVE, caller_is_admin=True)
    mgr.set_status(db_session, rel.id, STATUS_NEEDS_REVIEW, caller_is_admin=True)
    with pytest.raises(AuthorityStatusError) as exc:
        mgr.set_status(db_session, rel.id, STATUS_DRAFT, caller_is_admin=True)
    assert exc.value.params["reason"] == "transition_not_allowed"


def test_a_needs_review_version_never_activated_can_return_to_draft(db_session):
    mgr = AuthorityResolutionManager()
    rel = _draft(mgr, db_session, slug="trans-never-active")
    assert mgr.set_status(db_session, rel.id, STATUS_NEEDS_REVIEW).status == STATUS_NEEDS_REVIEW
    assert mgr.set_status(db_session, rel.id, STATUS_DRAFT).status == STATUS_DRAFT


def test_auto_flag_clears_affirmations_and_return_to_active_needs_fresh_ones(db_session, monkeypatch):
    mgr = AuthorityResolutionManager()
    rel = _draft(mgr, db_session, slug="trans-drift", criteria=[
        CriterionInput(name="Strict", rule="ASSERT obj.value <= 10")])
    _approve_and_measure(mgr, db_session, rel, rows=({"actor_identity": "a", "value": 1},))
    mgr.set_status(db_session, rel.id, STATUS_ACTIVE, caller_is_admin=True)

    # Drift: the next measurement is above the ceiling, so the AR is flagged and its approvals are cleared.
    mgr.compute_dnaco(db_session, rel.id, rows=[{"actor_identity": "a", "value": 99}])
    db_session.commit()
    flagged = mgr.get_relation(db_session, rel.id)
    assert flagged.status == STATUS_NEEDS_REVIEW
    assert not mgr.is_fully_affirmed(db_session, rel.id)

    # A clean measurement and a raised ceiling are not enough: the approvals must be given again.
    flagged.dna_max_threshold = 1.0
    mgr.compute_dnaco(db_session, rel.id, rows=[{"actor_identity": "a", "value": 1}])
    db_session.commit()
    with pytest.raises(AuthorityStatusError) as exc:
        mgr.set_status(db_session, rel.id, STATUS_ACTIVE, caller_is_admin=True)
    assert exc.value.params["reason"] == "affirmations_missing"


def test_a_resource_ref_change_is_a_definition_change(db_session):
    mgr = AuthorityResolutionManager()
    rel = _draft(mgr, db_session, slug="imm-ref", resource_refs=[
        ResourceRefInput(field_path="object_id", ref_type="literal", literal_value="dp-1")])
    _approve_and_measure(mgr, db_session, rel)
    mgr.update_relation(db_session, rel.id, AuthorityRelationUpdate(resource_refs=[
        ResourceRefInput(field_path="object_id", ref_type="literal", literal_value="dp-2")]))
    db_session.commit()
    assert mgr.get_relation(db_session, rel.id).dna_magnitude is None


def test_ak7_backfill_marks_only_versions_that_were_activated():
    """ak7: active and retired versions had been activated. A needs_review version only if a
    production decision (source 'mcp') was recorded for it. Drafts and dry runs don't count."""
    import importlib.util
    from sqlalchemy import create_engine, text
    path = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "ak7_authority_activation_history.py"
    spec = importlib.util.spec_from_file_location("ak7_authority_activation_history", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE authority_relations (id TEXT PRIMARY KEY, status TEXT, "
                          "updated_at TEXT, activated_at TEXT)"))
        conn.execute(text("CREATE TABLE authority_decisions (id TEXT PRIMARY KEY, relation_id TEXT, source TEXT)"))
        rows = [
            ("draft", "draft", None), ("active", "active", None), ("retired", "retired", None),
            ("review-mcp", "needs_review", None), ("review-dry", "needs_review", None),
            ("review-evidence", "needs_review", None), ("kept", "active", "2026-01-15"),
        ]
        for rid, status, act in rows:
            conn.execute(text("INSERT INTO authority_relations VALUES (:id, :st, '2026-02-01', :act)"),
                         {"id": rid, "st": status, "act": act})
        conn.execute(text("INSERT INTO authority_decisions VALUES ('d1', 'review-mcp', 'mcp')"))
        conn.execute(text("INSERT INTO authority_decisions VALUES ('d2', 'review-dry', 'test')"))
        conn.execute(text("INSERT INTO authority_decisions VALUES ('d3', 'review-evidence', 'evidence')"))
        assert migration.backfill_activated_at(conn) == 3
        got = dict(conn.execute(text("SELECT id, activated_at FROM authority_relations")).fetchall())
    assert got["draft"] is None
    assert got["review-dry"] is None and got["review-evidence"] is None
    assert got["active"] == got["retired"] == got["review-mcp"] == "2026-02-01"
    assert got["kept"] == "2026-01-15"  # an existing value is never overwritten
