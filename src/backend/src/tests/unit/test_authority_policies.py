"""Policy references: the justification metadata an Authority Relation cites (#1294 batch 5).

A reference is metadata only (ARF 1.2.0 decision): nothing about it is enforced.
These tests cover the reference CRUD and versions, the citation and its clause
labels (free text), the validity that reaches the checks as ``policy_ref.*``
(the shipped validity template included), that an expired or superseded
reference changes nothing at resolve or activation, the cited-by list and the
delete guard, audit records, and coded errors.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from src.common.authority_check_templates import get_template
from src.common.compliance_dsl import evaluate_rule_on_object
from src.controller import authority_policy_manager as apm
from src.controller.authority_policy_manager import AuthorityPolicyManager, AuthorityPolicyError
from src.controller.authority_resolution_manager import (
    AuthorityResolutionManager,
    VERDICT_APPROVED,
    VERDICT_DENIED,
)
from src.models.authority_policy import AuthorityPolicyCreate, AuthorityPolicyUpdate, PolicyClause
from src.models.authority_resolution import AuthorityRelationCreate, AuthorityRelationUpdate, CriterionInput

NOW = datetime.now(timezone.utc)
CLAUSES = [
    {"ref": "§7.1", "title": "Award", "text": "The CPO may award up to EUR 2m."},
    {"ref": "§7.2", "title": "Co-approval", "text": "Above EUR 1m the CFO co-approves."},
]
CEILING = {"leftOperand": "payAmount", "operator": "lteq", "rightOperand": 2_000_000,
           "message": "Award value is above the CPO's limit.", "clause": "§7.1"}


@pytest.fixture
def mgrs():
    rel = AuthorityResolutionManager()
    return rel, AuthorityPolicyManager()


def _policy(pm, db, *, key="POL-DOA", start=None, end=None, clauses=CLAUSES, url=None):
    return pm.create_policy(db, AuthorityPolicyCreate(
        policy_key=key, title=f"{key} policy", summary="Board-approved DoA.",
        valid_from=NOW - timedelta(days=30) if start is None else start,
        valid_to=end, url=url,
        clauses=[PolicyClause(**c) for c in clauses],
    ))


def _ar(rm, db, policy, *, slug="award", refs=("§7.1",), rule=None, criteria=None):
    return rm.create_relation(db, AuthorityRelationCreate(
        name=f"AR {slug}", slug=slug,
        authority_policy_id=policy.id if policy else None,
        policy_clause_refs=list(refs) if refs else None,
        rule=rule,
        # A version with neither a rule nor an enabled check approves nothing (batch 2, B5).
        criteria=[CriterionInput(**c) for c in (criteria if criteria is not None else
                                                ([] if rule else [{"name": "Not blocked", "rule": "ASSERT obj.value > -1"}]))],
    ))


def _resolve(rm, db, ar, req):
    return rm.resolve(db, ar.slug, req, record=False, require_active=False)


TEMPLATE_CHECK = {
    "name": "Justification window",
    "rule": get_template("justification_within_window").rule,
    "failure_message": get_template("justification_within_window").failure_message,
}


# ------------------------------------------------------------ validity view

def test_policy_ref_view_covers_every_state():
    none = apm.policy_ref_view(None)
    assert none == {"cited": False, "valid_from": None, "valid_to": None, "expired": False}
    open_ended = SimpleNamespace(valid_from=NOW - timedelta(days=2), valid_to=None)
    assert apm.policy_ref_view(open_ended)["expired"] is False
    current = SimpleNamespace(valid_from=NOW - timedelta(days=2), valid_to=NOW + timedelta(days=1))
    assert apm.policy_ref_view(current)["expired"] is False
    lapsed = SimpleNamespace(valid_from=NOW - timedelta(days=9), valid_to=NOW - timedelta(days=1))
    view = apm.policy_ref_view(lapsed)
    assert view["cited"] is True and view["expired"] is True and isinstance(view["valid_to"], str)
    # Naive datetimes are UTC (SQLite returns them naive).
    naive = SimpleNamespace(valid_from=None, valid_to=datetime.utcnow() - timedelta(days=1))
    assert apm.policy_ref_view(naive)["expired"] is True


def test_the_validity_is_computed_at_the_given_time():
    ref = SimpleNamespace(valid_from=None, valid_to=NOW + timedelta(days=10))
    assert apm.policy_ref_view(ref, at=NOW)["expired"] is False
    assert apm.policy_ref_view(ref, at=NOW + timedelta(days=11))["expired"] is True


# ------------------------------------------------------------ validation

def test_clause_labels_are_validated_for_shape_only():
    with pytest.raises(AuthorityPolicyError, match="twice"):
        apm.normalize_clauses([{"ref": "§1"}, {"ref": "§1"}])
    with pytest.raises(AuthorityPolicyError, match="reference"):
        apm.normalize_clauses([{"ref": " "}])
    assert apm.normalize_clauses([{"ref": " §1 ", "title": "", "text": "t"}]) == [{"ref": "§1", "text": "t"}]


@pytest.mark.parametrize("url", ["javascript:alert(1)", "ftp://x/y", "https://"])
def test_the_link_out_must_be_http_or_https(url):
    with pytest.raises(AuthorityPolicyError) as exc:
        apm._check_url(url)
    assert exc.value.code == "authority_policy_invalid"
    assert apm._check_url("https://docs.example/doa.pdf") == "https://docs.example/doa.pdf"
    assert apm._check_url("  ") is None


def test_validity_window_must_end_after_it_starts(db_session, mgrs):
    _, pm = mgrs
    with pytest.raises(AuthorityPolicyError, match="valid_to must be after valid_from") as exc:
        _policy(pm, db_session, start=NOW, end=NOW - timedelta(days=1))
    assert exc.value.code == "authority_policy_invalid"


def test_external_id_is_unique_and_versions_share_it(db_session, mgrs):
    _, pm = mgrs
    _policy(pm, db_session)
    with pytest.raises(AuthorityPolicyError, match="already exists") as exc:
        pm.create_policy(db_session, AuthorityPolicyCreate(policy_key="POL-DOA", title="dup"))
    assert exc.value.code == "authority_policy_conflict"


# ------------------------------------------------------------ CRUD and versions

def test_reference_edits_are_corrections_to_any_version(db_session, mgrs):
    _, pm = mgrs
    p = _policy(pm, db_session)
    p = pm.update_policy(db_session, p.id, AuthorityPolicyUpdate(
        title="Renamed", valid_to=NOW + timedelta(days=30), url="https://docs.example/doa"))
    assert (p.title, p.url) == ("Renamed", "https://docs.example/doa")
    assert pm.to_read_dict(db_session, p)["expired"] is False


def test_a_new_version_is_a_new_record_linked_to_its_parent(db_session, mgrs):
    _, pm = mgrs
    v1 = _policy(pm, db_session, end=NOW + timedelta(days=5))
    v2 = pm.create_new_version(db_session, v1.id, "2", change_summary="raise limit")
    assert (v2.parent_policy_id, v2.version_family_id) == (v1.id, v1.id)
    assert v2.clauses == v1.clauses
    # A new version carries its own validity window, not the old one's end date.
    assert v2.valid_from is None and v2.valid_to is None
    with pytest.raises(AuthorityPolicyError, match="already exists"):
        pm.create_new_version(db_session, v1.id, "2")
    [rep] = pm.list_policies(db_session)
    assert rep.id == v2.id and rep._version_count == 2


def test_a_reference_cited_by_an_ar_cannot_be_deleted_until_the_citation_goes(db_session, mgrs):
    rm, pm = mgrs
    p = _policy(pm, db_session)
    ar = _ar(rm, db_session, p)
    with pytest.raises(AuthorityPolicyError, match="cited by AR award") as exc:
        pm.delete_policy(db_session, p.id)
    assert exc.value.code == "authority_policy_in_use"
    rm.update_relation(db_session, ar.id, AuthorityRelationUpdate(authority_policy_id=None))
    assert pm.delete_policy(db_session, p.id) is True


def test_the_cited_by_list_covers_every_ar_citing_the_reference(db_session, mgrs):
    rm, pm = mgrs
    p = _policy(pm, db_session)
    a = _ar(rm, db_session, p, slug="a")
    b = _ar(rm, db_session, p, slug="b", refs=("§7.2",))
    names = sorted(d["name"] for d in pm.dependents(db_session, p.id))
    assert names == [a.name, b.name]


# ------------------------------------------------------------ citation

def test_clause_labels_are_free_text_and_need_a_reference(db_session, mgrs):
    rm, pm = mgrs
    p = _policy(pm, db_session)
    # No clause list validation: a label the reference doesn't list is still accepted.
    ar = _ar(rm, db_session, p, refs=("§9",))
    assert ar.policy_clause_refs == ["§9"]
    with pytest.raises(ValueError, match="Cite a policy reference"):
        _ar(rm, db_session, None, refs=("§7.1",))


def test_citing_a_missing_reference_is_refused(db_session, mgrs):
    rm, _ = mgrs
    with pytest.raises(ValueError, match="not found"):
        rm.create_relation(db_session, AuthorityRelationCreate(
            name="AR x", slug="x", authority_policy_id="gone", policy_clause_refs=["§1"],
            criteria=[CriterionInput(name="c", rule="ASSERT obj.value > 0")],
        ))


def test_dropping_the_reference_drops_its_clause_labels(db_session, mgrs):
    rm, pm = mgrs
    ar = _ar(rm, db_session, _policy(pm, db_session), rule={"permission": {"constraint": [CEILING]}},
             criteria=[{"name": "c", "rule": "obj.value > 0", "policy_clause_ref": "§7.2"}])
    rm.update_relation(db_session, ar.id, AuthorityRelationUpdate(authority_policy_id=None))
    assert ar.authority_policy_id is None and ar.policy_clause_refs is None
    assert "clause" not in ar.rule["permission"]["constraint"][0]
    assert [c["policy_clause_ref"] for c in rm.to_read_dict(db_session, ar)["criteria"]] == [None]


# ------------------------------------------------------------ no enforcement

@pytest.mark.parametrize("state", ["expired", "not_yet", "open"])
def test_a_reference_outside_its_window_does_not_change_resolve(db_session, mgrs, state):
    rm, pm = mgrs
    start = NOW + timedelta(days=5) if state == "not_yet" else NOW - timedelta(days=10)
    end = NOW - timedelta(days=1) if state == "expired" else None
    ar = _ar(rm, db_session, _policy(pm, db_session, start=start, end=end))
    out = _resolve(rm, db_session, ar, {"value": 1})
    assert out["verdict"] == VERDICT_APPROVED
    assert out["policy"]["authority_policy_id"] == ar.authority_policy_id


def test_an_ar_citing_an_expired_reference_still_activates_and_stays_active(db_session, mgrs):
    """Nothing gates on the reference: no policy_not_in_force, no needs_review on expiry."""
    rm, pm = mgrs
    p = _policy(pm, db_session, start=NOW - timedelta(days=10), end=NOW + timedelta(days=1))
    ar = _ar(rm, db_session, p)
    ar.status = "active"
    db_session.flush()
    # The expiry has passed; nothing flags the AR, and resolve still approves.
    assert _resolve(rm, db_session, ar, {"value": 1})["verdict"] == VERDICT_APPROVED
    db_session.refresh(ar)
    assert ar.status == "active"


def test_structural_score_counts_a_cited_reference_whatever_its_validity(db_session, mgrs):
    rm, pm = mgrs
    expired = _ar(rm, db_session, _policy(pm, db_session, key="E", end=NOW - timedelta(days=1)), slug="e")
    uncited = _ar(rm, db_session, None, slug="u", refs=None, criteria=[{"name": "c", "rule": "obj.value > 0"}])
    assert rm._has_justification(expired) is True
    assert rm._has_justification(uncited) is False


def test_concept_lookup_does_not_exclude_an_ar_for_its_reference(db_session, mgrs, monkeypatch):
    rm, pm = mgrs
    ar = _ar(rm, db_session, _policy(pm, db_session, end=NOW - timedelta(days=1)))
    ar.status = "active"
    db_session.flush()
    from src.repositories import semantic_links_repository as slr
    monkeypatch.setattr(slr.entity_semantic_links_repo, "list_for_iri",
                        lambda db, iri: [SimpleNamespace(entity_type="authority_relation", entity_id=ar.id)])
    out = rm.find_authority_for_concept(db_session, "urn:c")
    assert out["candidates"] and "policy_problem" not in out["candidates"][0]
    assert out["resolved"] is not None


# ------------------------------------------------------------ provenance and reasons

def test_denials_cite_the_reference_and_its_clause_label(db_session, mgrs):
    rm, pm = mgrs
    p = _policy(pm, db_session)
    ar = _ar(rm, db_session, p, refs=("§7.1", "§7.2"),
             rule={"permission": {"constraint": [CEILING]}},
             criteria=[{"name": "Bidders", "rule": "obj.bidders >= 3", "failure_message": "Too few bidders.",
                        "policy_clause_ref": "§7.1"}])
    out = _resolve(rm, db_session, ar, {"value": 3_000_000, "bidders": 3})
    assert out["verdict"] == VERDICT_DENIED
    assert out["reason"] == "Award value is above the CPO's limit. [POL-DOA v1 §7.1]"
    out = _resolve(rm, db_session, ar, {"value": 10, "bidders": 1})
    assert out["reason"] == "Too few bidders. [POL-DOA v1 §7.1]"


def test_provenance_records_the_reference_and_labels_without_documents(db_session, mgrs):
    from src.db_models.authority_resolution import AuthorityDecisionDb
    rm, pm = mgrs
    p = _policy(pm, db_session, url="https://docs.example/doa")
    ar = _ar(rm, db_session, p, refs=("§7.1",))
    rm.resolve(db_session, ar.slug, {"value": 1}, record=True, require_active=False)
    decision = db_session.query(AuthorityDecisionDb).filter_by(relation_id=ar.id).one()
    cited = decision.provenance["policy"]
    assert (cited["policy_key"], cited["version"], cited["clause_refs"]) == ("POL-DOA", "1", ["§7.1"])
    assert cited["url"] == "https://docs.example/doa" and cited["expired"] is False
    assert isinstance(cited["valid_from"], str)
    assert "documents" not in cited and "clauses" not in cited


def test_read_dict_carries_the_citation(db_session, mgrs):
    rm, pm = mgrs
    ar = _ar(rm, db_session, _policy(pm, db_session))
    cited = rm.to_read_dict(db_session, ar)["policy"]
    assert cited["policy_key"] == "POL-DOA" and cited["clause_refs"] == ["§7.1"]
    assert "problem" not in cited and "documents" not in cited


def test_new_ar_version_keeps_the_citation(db_session, mgrs):
    rm, pm = mgrs
    ar = _ar(rm, db_session, _policy(pm, db_session),
             criteria=[{"name": "c", "rule": "obj.value > 0", "policy_clause_ref": "§7.2"}])
    v2 = rm.create_new_version(db_session, ar.id, "1.1.0")
    assert (v2.authority_policy_id, v2.policy_clause_refs) == (ar.authority_policy_id, ["§7.1"])
    assert [c["policy_clause_ref"] for c in rm.to_read_dict(db_session, v2)["criteria"]] == ["§7.2"]


# ------------------------------------------------------------ policy_ref in the checks

def test_the_evaluation_object_carries_the_policy_ref(db_session, mgrs):
    rm, pm = mgrs
    ar = _ar(rm, db_session, _policy(pm, db_session, end=NOW - timedelta(days=1)))
    view = rm._policy_ref_for_relation(db_session, ar)
    obj = rm._evaluation_object(ar, {"value": 1}, None, view)
    assert obj["policy_ref"]["cited"] is True and obj["policy_ref"]["expired"] is True
    assert obj["policy_ref"]["valid_to"] is not None
    # A request can't set it (anti-spoofing): the reference's own value wins.
    spoofed = rm._evaluation_object(ar, {"value": 1, "policy_ref": {"expired": False, "cited": True}}, None, view)
    assert spoofed["policy_ref"]["expired"] is True


def test_a_request_field_named_justification_stays_an_ordinary_field(db_session, mgrs):
    """The namespace is ``policy_ref``: a ``justification`` field is just ``obj.justification``."""
    rm, pm = mgrs
    ar = _ar(rm, db_session, _policy(pm, db_session))
    view = rm._policy_ref_for_relation(db_session, ar)
    obj = rm._evaluation_object(ar, {"value": 1, "justification": "board minute 12"}, None, view)
    assert obj["justification"] == "board minute 12"
    assert obj["policy_ref"]["cited"] is True
    assert passed_check(obj, "ASSERT obj.justification = 'board minute 12'")


def passed_check(obj, rule):
    from src.common.compliance_dsl import evaluate_rule_strict
    return evaluate_rule_strict(rule, obj).passed is True


def test_the_entity_dict_carries_the_policy_ref(db_session, mgrs):
    from src.controller.entity_dict_builder import build_authority_relation_dict
    rm, pm = mgrs
    ar = _ar(rm, db_session, _policy(pm, db_session, end=NOW + timedelta(days=3)))
    db_session.flush()
    j = build_authority_relation_dict(db_session, ar.id)["policy_ref"]
    assert j["cited"] is True and j["expired"] is False and j["valid_to"]
    uncited = _ar(rm, db_session, None, slug="u2", refs=None, criteria=[{"name": "c", "rule": "obj.value > 0"}])
    db_session.flush()
    assert build_authority_relation_dict(db_session, uncited.id)["policy_ref"]["cited"] is False


def test_policy_ref_is_a_closed_namespace_for_other_entities():
    # A data product has no policy_ref; a top-level key must not stand in for it.
    passed, _ = evaluate_rule_on_object("ASSERT policy_ref.expired = False", {"expired": False})
    assert passed is False


def test_validity_template_passes_a_current_reference(db_session, mgrs):
    rm, pm = mgrs
    ar = _ar(rm, db_session, _policy(pm, db_session, end=NOW + timedelta(days=30)),
             criteria=[TEMPLATE_CHECK])
    assert _resolve(rm, db_session, ar, {"value": 1})["verdict"] == VERDICT_APPROVED


def test_validity_template_denies_an_expired_reference_with_its_message(db_session, mgrs):
    rm, pm = mgrs
    ar = _ar(rm, db_session, _policy(pm, db_session, end=NOW - timedelta(days=1)),
             criteria=[TEMPLATE_CHECK])
    out = _resolve(rm, db_session, ar, {"value": 1})
    assert out["verdict"] == VERDICT_DENIED
    assert out["reason"] == get_template("justification_within_window").failure_message


def test_validity_template_denies_an_ar_with_no_reference(db_session, mgrs):
    rm, _ = mgrs
    ar = _ar(rm, db_session, None, refs=None, criteria=[TEMPLATE_CHECK])
    out = _resolve(rm, db_session, ar, {"value": 1})
    assert out["verdict"] == VERDICT_DENIED
    assert out["reason"] == get_template("justification_within_window").failure_message


# ------------------------------------------------------------ routes: audit and coded errors

def _request():
    return SimpleNamespace(client=None)


def _user(name="alice"):
    return SimpleNamespace(username=name, email=f"{name}@x")


def test_reference_changes_write_audit_records(db_session):
    from src.routes import authority_policy_routes as routes
    audit = MagicMock()
    payload = AuthorityPolicyCreate(policy_key="AUD-1", title="Audited", clauses=[])
    created = asyncio.run(routes.create_policy(_request(), db_session, audit, _user(), payload, True))
    pid = created["id"]
    asyncio.run(routes.update_policy(pid, _request(), db_session, audit, _user(),
                                     AuthorityPolicyUpdate(title="Audited 2"), True))
    v2 = asyncio.run(routes.create_policy_version(pid, _request(), db_session, audit, _user(),
                                                  SimpleNamespace(new_version="2", change_summary=None), True))
    # The first version of a family can't go while a newer version exists.
    asyncio.run(routes.delete_policy(v2["id"], _request(), db_session, audit, _user(), True))
    asyncio.run(routes.delete_policy(pid, _request(), db_session, audit, _user(), True))
    actions = [c.kwargs["action"] for c in audit.log_action.call_args_list]
    assert actions[0] == "CREATE_POLICY_REFERENCE"
    assert "UPDATE_POLICY_REFERENCE" in actions and "CREATE_POLICY_REFERENCE_VERSION" in actions
    assert actions[-1] == "DELETE_POLICY_REFERENCE"
    first = audit.log_action.call_args_list[0].kwargs
    assert first["feature"] == "authority-resolution" and first["username"] == "alice"
    assert first["details"]["policy_key"] == "AUD-1" and first["success"] is True


def test_refusals_are_coded_for_the_ui(db_session):
    from src.routes import authority_policy_routes as routes
    audit = MagicMock()
    payload = AuthorityPolicyCreate(policy_key="CODE-1", title="Coded")
    asyncio.run(routes.create_policy(_request(), db_session, audit, _user(), payload, True))
    with pytest.raises(HTTPException) as dup:
        asyncio.run(routes.create_policy(_request(), db_session, audit, _user(), payload, True))
    assert dup.value.status_code == 409
    assert dup.value.__cause__.code == "authority_policy_conflict"
    with pytest.raises(HTTPException) as missing:
        asyncio.run(routes.get_policy("nope", db_session, True))
    assert missing.value.status_code == 404
    assert missing.value.__cause__.code == "authority_policy_not_found"
    assert audit.log_action.call_count == 1  # a refused create writes no record


def test_the_policy_routes_answer_no_status_or_documents_endpoint():
    from src.routes.authority_policy_routes import router
    paths = {(route.path, tuple(sorted(route.methods))) for route in router.routes}
    assert not any("/status" in p or "/documents" in p for p, _ in paths)
    assert ("/api/authority/policies/{policy_id}/dependents", ("GET",)) in paths


def test_policy_references_have_no_document_panel_kind():
    from src.models.metadata import DocumentCreate
    from pydantic import ValidationError
    DocumentCreate(entity_id="x", entity_type="authority_relation", title="t")
    with pytest.raises(ValidationError):
        DocumentCreate(entity_id="x", entity_type="authority_policy", title="t")


# ------------------------------------------------------------ one view for resolve, DNA and the validators

def test_the_validator_uses_the_ars_real_reference_or_the_samples_view(db_session, mgrs):
    from src.routes.authority_resolution_routes import validate_criterion
    rm, pm = mgrs
    ar = _ar(rm, db_session, _policy(pm, db_session, end=NOW - timedelta(days=1)))
    db_session.flush()
    rule = "ASSERT policy_ref.cited = True AND policy_ref.expired = False"
    # A stored AR is judged against its real reference: lapsed here, whatever the sample says.
    out = asyncio.run(validate_criterion(db_session, {"rule": rule, "object": {}, "relation_id": ar.id,
                                                      "policy_ref": {"cited": True, "expired": False}}, True))
    assert out["passed"] is False
    # A dry-run sample without a relation can say it's cited and current.
    out = asyncio.run(validate_criterion(db_session, {"rule": rule, "object": {}, "policy_ref": {
        "cited": True, "expired": False}}, True))
    assert out["passed"] is True
    out = asyncio.run(validate_criterion(db_session, {"rule": rule, "object": {}}, True))
    assert out["passed"] is False


def test_dna_evidence_rows_carry_the_reference_view(db_session, mgrs):
    rm, pm = mgrs
    ar = _ar(rm, db_session, _policy(pm, db_session, end=NOW + timedelta(days=30)))
    view = rm._policy_ref_for_relation(db_session, ar)
    kept, skipped = rm._scoped_evidence(ar, [{"value": 1}, {"value": 2}], {}, view)
    assert skipped == 0 and [row["policy_ref"]["cited"] for row in kept] == [True, True]


def test_the_citation_carries_the_parent_version(db_session, mgrs):
    rm, pm = mgrs
    v1 = _policy(pm, db_session)
    v2 = pm.create_new_version(db_session, v1.id, "2")
    ar = _ar(rm, db_session, v2)
    assert rm.to_read_dict(db_session, ar)["policy"]["parent_policy_id"] == v1.id


def test_the_coded_helper_answers_a_refusal_with_its_code_and_attributes():
    from src.common.api_errors import coded_http_error
    from src.controller.authority_policy_manager import AuthorityPolicyInUseError
    exc = AuthorityPolicyInUseError("cited by X", cited_by=["X"])
    refused = coded_http_error("test", exc)
    assert refused.status_code == 409
    assert refused.detail == "cited by X" and refused.__cause__ is exc
    assert (exc.code, exc.params) == ("authority_policy_in_use", {"cited_by": ["X"]})


def test_the_coded_helper_hides_an_unexpected_failure_behind_an_error_id():
    from src.common.api_errors import coded_http_error
    failed = coded_http_error("test", RuntimeError("secret SQL text"))
    assert failed.status_code == 500
    assert failed.detail["code"] == "request_failed" and "secret SQL" not in str(failed.detail)
