"""Authority Policy: the justification basis an Authority Relation cites (#1294 slice 2).

Covers the policy lifecycle (draft → approved → superseded / withdrawn), the
AR citation rules, the resolve gate (no valid policy root = no_authority),
clause-cited denial reasons and duties, provenance, the expiry sweep, the
structural score, versioning, and the Metadata document guards (size cap,
SHA-256, approved policies' documents are immutable).
"""
import asyncio
from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, UploadFile

from src.controller import authority_policy_manager as apol
from src.controller.authority_policy_manager import AuthorityPolicyManager
from src.controller.authority_resolution_manager import (
    AuthorityResolutionManager,
    VERDICT_APPROVED,
    VERDICT_CONDITIONAL,
    VERDICT_DENIED,
    VERDICT_NO_AUTHORITY,
)
from src.models.authority_policy import AuthorityPolicyCreate, AuthorityPolicyUpdate, PolicyStatusRequest
from src.models.authority_resolution import AuthorityRelationCreate, AuthorityRelationUpdate, CriterionInput

NOW = datetime.now(timezone.utc)
CLAUSES = [
    {"ref": "§7.1", "title": "Award", "text": "The CPO may award up to EUR 2m.", "limits": {"amount": 2_000_000, "currency": "EUR"}},
    {"ref": "§7.2", "title": "Co-approval", "text": "Above EUR 1m the CFO co-approves."},
]
CEILING = {"leftOperand": "payAmount", "operator": "lteq", "rightOperand": 2_000_000,
           "message": "Award value is above the CPO's limit.", "clause": "§7.1"}
COSIGN = {"action": "arf:obtainCoApproval", "message": "CFO co-approval is pending.", "clause": "§7.2",
          "constraint": [{"leftOperand": "arf:cosignPresent", "operator": "eq", "rightOperand": True}]}


@pytest.fixture
def mgrs():
    rel = AuthorityResolutionManager()
    return rel, AuthorityPolicyManager(relation_manager=rel)


def _policy(pm, db, *, key="POL-DOA", approve=True, start=None, end=None, clauses=CLAUSES):
    p = pm.create_policy(db, AuthorityPolicyCreate(policy_key=key, title=f"{key} policy", clauses=clauses))
    if approve:
        p, err = pm.set_status(db, p.id, PolicyStatusRequest(
            status="approved", approved_by="board@x", effective_from=start or NOW - timedelta(days=1),
            effective_to=end), current_user="admin")
        assert err is None, err
    return p


def _ar(rm, db, policy, *, slug="award", refs=("§7.1",), rule=None, criteria=None):
    return rm.create_relation(db, AuthorityRelationCreate(
        name=f"AR {slug}", slug=slug,
        authority_policy_id=policy.id if policy else None,
        policy_clause_refs=list(refs) if refs else None,
        rule=rule, criteria=[CriterionInput(**c) for c in (criteria or [])],
    ))


def _resolve(rm, db, ar, req):
    return rm.resolve(db, ar.slug, req, record=False, require_active=False)


# ------------------------------------------------------------- policy lifecycle

def test_root_problem_covers_every_invalid_state():
    p = SimpleNamespace(policy_key="P", version="1", status="approved",
                        effective_from=NOW - timedelta(days=2), effective_to=None)
    assert apol.policy_root_problem(p) is None
    assert apol.policy_root_problem(None) == "policy root missing"
    assert "withdrawn" in apol.policy_root_problem(SimpleNamespace(**{**vars(p), "status": "withdrawn"}))
    assert "not approved" in apol.policy_root_problem(SimpleNamespace(**{**vars(p), "status": "draft"}))
    assert "not yet effective" in apol.policy_root_problem(
        SimpleNamespace(**{**vars(p), "effective_from": NOW + timedelta(days=1)}))
    assert "expired" in apol.policy_root_problem(
        SimpleNamespace(**{**vars(p), "effective_to": NOW - timedelta(days=1)}))
    # A superseded version stays a root until its window closes; naive datetimes are UTC.
    assert apol.policy_root_problem(SimpleNamespace(
        **{**vars(p), "status": "superseded", "effective_from": datetime.utcnow() - timedelta(days=2)})) is None


def test_clauses_are_validated():
    with pytest.raises(ValueError, match="twice"):
        apol.normalize_clauses([{"ref": "§1"}, {"ref": "§1"}])
    with pytest.raises(ValueError, match="reference"):
        apol.normalize_clauses([{"ref": " "}])
    assert apol.normalize_clauses([{"ref": " §1 ", "title": "", "conditions": ["a", " "]}]) == [
        {"ref": "§1", "conditions": ["a"]}]


def test_approval_needs_clauses_an_effective_date_and_draft_status(db_session, mgrs):
    _, pm = mgrs
    empty = pm.create_policy(db_session, AuthorityPolicyCreate(policy_key="E", title="Empty"))
    assert "clause" in pm.set_status(db_session, empty.id, PolicyStatusRequest(status="approved"), "u")[1]
    p = pm.create_policy(db_session, AuthorityPolicyCreate(policy_key="P", title="P", clauses=CLAUSES))
    assert "effective date" in pm.set_status(db_session, p.id, PolicyStatusRequest(status="approved"), "u")[1]
    p, err = pm.set_status(db_session, p.id, PolicyStatusRequest(status="approved", effective_from=NOW), "alice")
    assert err is None and p.status == "approved" and p.approved_by == "alice"
    assert "Only a draft" in pm.set_status(db_session, p.id, PolicyStatusRequest(status="approved", effective_from=NOW), "u")[1]
    assert "directly" in pm.set_status(db_session, p.id, PolicyStatusRequest(status="superseded"), "u")[1]


def test_only_drafts_are_editable_and_keys_are_unique(db_session, mgrs):
    _, pm = mgrs
    p = _policy(pm, db_session)
    with pytest.raises(PermissionError, match="new version"):
        pm.update_policy(db_session, p.id, AuthorityPolicyUpdate(title="x"))
    with pytest.raises(ValueError, match="already exists"):
        pm.create_policy(db_session, AuthorityPolicyCreate(policy_key="POL-DOA", title="dup"))


def test_approving_a_successor_supersedes_its_parent_and_closes_its_window(db_session, mgrs):
    rm, pm = mgrs
    v1 = _policy(pm, db_session)
    ar = _ar(rm, db_session, v1)
    v2 = pm.create_new_version(db_session, v1.id, "2", change_summary="raise limit")
    assert (v2.status, v2.parent_policy_id, v2.version_family_id) == ("draft", v1.id, v1.id)
    assert v2.clauses == v1.clauses
    starts = NOW + timedelta(days=30)
    v2, err = pm.set_status(db_session, v2.id, PolicyStatusRequest(status="approved", effective_from=starts), "u")
    assert err is None
    db_session.refresh(v1)
    assert v1.status == "superseded"
    assert apol._aware(v1.effective_to) == starts
    # Until v2 takes effect the AR still has a valid root through v1.
    assert apol.policy_root_problem(v1) is None
    assert _resolve(rm, db_session, ar, {"value": 10})["verdict"] == VERDICT_APPROVED
    # The family list shows the approved version.
    [rep] = pm.list_policies(db_session)
    assert rep.id == v2.id and rep._version_count == 2


def test_withdrawing_flags_active_citing_ars_for_review(db_session, mgrs):
    rm, pm = mgrs
    p = _policy(pm, db_session)
    ar = _ar(rm, db_session, p)
    ar.status = "active"
    draft_ar = _ar(rm, db_session, p, slug="other")
    db_session.flush()
    p, err = pm.set_status(db_session, p.id, PolicyStatusRequest(status="withdrawn", reason="replaced"), "u")
    assert err is None and p.withdrawn_reason == "replaced"
    db_session.refresh(ar)
    db_session.refresh(draft_ar)
    assert ar.status == "needs_review" and draft_ar.status == "draft"


def test_expiry_sweep_flags_active_ars(db_session, mgrs):
    rm, pm = mgrs
    p = _policy(pm, db_session, start=NOW - timedelta(days=10), end=NOW + timedelta(days=1))
    ar = _ar(rm, db_session, p)
    ar.status = "active"
    db_session.flush()
    assert pm.sweep_expired(db_session)["flagged_relations"] == []
    out = pm.sweep_expired(db_session, at=NOW + timedelta(days=2))
    assert out["flagged_relations"] == [ar.id]
    db_session.refresh(ar)
    assert ar.status == "needs_review"


def test_delete_refuses_approved_and_cited_policies(db_session, mgrs):
    rm, pm = mgrs
    p = _policy(pm, db_session)
    with pytest.raises(ValueError, match="withdraw it first"):
        pm.delete_policy(db_session, p.id)
    draft = _policy(pm, db_session, key="D", approve=False)
    _ar(rm, db_session, draft, refs=None)
    with pytest.raises(ValueError, match="cited by"):
        pm.delete_policy(db_session, draft.id)
    lone = _policy(pm, db_session, key="L", approve=False)
    assert pm.delete_policy(db_session, lone.id) is True


def test_a_cited_clause_cannot_be_dropped_from_a_draft(db_session, mgrs):
    rm, pm = mgrs
    draft = _policy(pm, db_session, approve=False)
    _ar(rm, db_session, draft, refs=("§7.2",))
    with pytest.raises(ValueError, match="§7.2"):
        pm.update_policy(db_session, draft.id, AuthorityPolicyUpdate(clauses=[CLAUSES[0]]))


# ------------------------------------------------------------- AR citation

def test_ar_citations_must_name_existing_clauses(db_session, mgrs):
    rm, pm = mgrs
    p = _policy(pm, db_session)
    with pytest.raises(ValueError, match="no clause §9"):
        _ar(rm, db_session, p, refs=("§9",))
    with pytest.raises(ValueError, match="no clause §8"):
        _ar(rm, db_session, p, rule={"permission": {"constraint": [{**CEILING, "clause": "§8"}]}})
    with pytest.raises(ValueError, match="no clause §6"):
        _ar(rm, db_session, p, criteria=[{"name": "c", "rule": "obj.value > 0", "policy_clause_ref": "§6"}])
    with pytest.raises(ValueError, match="Cite an Authority Policy"):
        _ar(rm, db_session, None, refs=("§7.1",))


def test_withdrawn_policy_cannot_be_newly_cited_but_an_existing_citation_stays(db_session, mgrs):
    rm, pm = mgrs
    p = _policy(pm, db_session)
    ar = _ar(rm, db_session, p)
    pm.set_status(db_session, p.id, PolicyStatusRequest(status="withdrawn"), "u")
    with pytest.raises(ValueError, match="withdrawn"):
        _ar(rm, db_session, p, slug="new")
    # Editing the AR without re-pointing keeps working.
    rm.update_relation(db_session, ar.id, AuthorityRelationUpdate(policy_clause_refs=["§7.1", "§7.2"]))
    assert ar.policy_clause_refs == ["§7.1", "§7.2"]


def test_dropping_the_policy_drops_its_clause_citations(db_session, mgrs):
    rm, pm = mgrs
    ar = _ar(rm, db_session, _policy(pm, db_session))
    rm.update_relation(db_session, ar.id, AuthorityRelationUpdate(authority_policy_id=None))
    assert ar.authority_policy_id is None and ar.policy_clause_refs is None


# ------------------------------------------------------------- resolve gate

@pytest.mark.parametrize("state", ["missing", "draft", "withdrawn", "not_yet", "expired"])
def test_resolve_without_a_valid_policy_root_is_no_authority(db_session, mgrs, state):
    rm, pm = mgrs
    start = NOW + timedelta(days=5) if state == "not_yet" else NOW - timedelta(days=10)
    end = NOW - timedelta(days=1) if state == "expired" else None
    p = _policy(pm, db_session, approve=state != "draft", start=start, end=end)
    ar = _ar(rm, db_session, p)
    if state == "withdrawn":
        pm.set_status(db_session, p.id, PolicyStatusRequest(status="withdrawn"), "u")
    if state == "missing":
        ar.authority_policy_id = "gone"
        db_session.flush()
    out = _resolve(rm, db_session, ar, {"value": 1})
    assert out["verdict"] == VERDICT_NO_AUTHORITY
    assert out["reason"].startswith("policy root")


def test_ar_without_a_policy_resolves_as_before(db_session, mgrs):
    rm, _ = mgrs
    ar = _ar(rm, db_session, None, refs=None, rule={"permission": {"constraint": [{**CEILING, "clause": None}]}})
    out = _resolve(rm, db_session, ar, {"value": 1})
    assert out["verdict"] == VERDICT_APPROVED and out["policy"] is None


def test_denials_and_duties_cite_their_clause(db_session, mgrs):
    rm, pm = mgrs
    p = _policy(pm, db_session)
    ar = _ar(rm, db_session, p, refs=("§7.1", "§7.2"),
             rule={"permission": {"constraint": [CEILING], "duty": [COSIGN]}},
             criteria=[{"name": "Bidders", "rule": "obj.bidders >= 3", "failure_message": "Too few bidders.",
                        "policy_clause_ref": "§7.1"}])
    out = _resolve(rm, db_session, ar, {"value": 3_000_000, "bidders": 3})
    assert out["verdict"] == VERDICT_DENIED
    assert out["reason"] == "Award value is above the CPO's limit. [POL-DOA v1 §7.1]"
    out = _resolve(rm, db_session, ar, {"value": 10, "bidders": 1})
    assert out["reason"] == "Too few bidders. [POL-DOA v1 §7.1]"
    out = _resolve(rm, db_session, ar, {"value": 10, "bidders": 3, "cosign_present": False})
    assert out["verdict"] == VERDICT_CONDITIONAL
    assert out["pending_duties"] == [{"duty": "arf:obtainCoApproval", "message": "CFO co-approval is pending.",
                                      "clause": "§7.2"}]


def test_provenance_records_the_policy_version_clauses_and_document_hashes(db_session, mgrs):
    from src.db_models.authority_resolution import AuthorityDecisionDb
    from src.db_models.metadata import DocumentMetadataDb
    rm, pm = mgrs
    p = _policy(pm, db_session, approve=False)
    db_session.add(DocumentMetadataDb(entity_type="authority_policy", entity_id=p.id, title="DoA",
                                      original_filename="doa.pdf", storage_path="/v/doa.pdf",
                                      content_sha256="ab" * 32))
    db_session.flush()
    pm.set_status(db_session, p.id, PolicyStatusRequest(status="approved", effective_from=NOW - timedelta(days=1)), "u")
    ar = _ar(rm, db_session, p, refs=("§7.1",))
    rm.resolve(db_session, ar.slug, {"value": 1}, record=True, require_active=False)
    decision = db_session.query(AuthorityDecisionDb).filter_by(relation_id=ar.id).one()
    cited = decision.provenance["policy"]
    assert (cited["policy_key"], cited["version"], cited["clause_refs"]) == ("POL-DOA", "1", ["§7.1"])
    assert cited["documents"] == [{"id": cited["documents"][0]["id"], "filename": "doa.pdf", "sha256": "ab" * 32}]
    assert cited["clauses"][0]["text"].startswith("The CPO")
    assert isinstance(cited["effective_from"], str)


def test_activation_needs_a_valid_policy_root(db_session, mgrs):
    rm, pm = mgrs
    ar = _ar(rm, db_session, _policy(pm, db_session, approve=False))
    ar.dna_magnitude = 0.0
    db_session.flush()
    _, err = rm.set_status(db_session, ar.id, "active")
    assert err and "policy root not approved" in err


def test_structural_score_counts_a_valid_cited_policy(db_session, mgrs):
    rm, pm = mgrs
    cited = _ar(rm, db_session, _policy(pm, db_session))
    uncited_clauses = _ar(rm, db_session, _policy(pm, db_session, key="B"), slug="b", refs=None)
    draft = _ar(rm, db_session, _policy(pm, db_session, key="C", approve=False), slug="c")
    assert rm._has_justification(cited) is True
    assert rm._has_justification(uncited_clauses) is False
    assert rm._has_justification(draft) is False


def test_new_ar_version_keeps_the_citation(db_session, mgrs):
    rm, pm = mgrs
    ar = _ar(rm, db_session, _policy(pm, db_session),
             criteria=[{"name": "c", "rule": "obj.value > 0", "policy_clause_ref": "§7.2"}])
    v2 = rm.create_new_version(db_session, ar.id, "1.1.0")
    assert (v2.authority_policy_id, v2.policy_clause_refs) == (ar.authority_policy_id, ["§7.1"])
    assert [c["policy_clause_ref"] for c in rm.to_read_dict(db_session, v2)["criteria"]] == ["§7.2"]


def test_read_dict_carries_the_citation(db_session, mgrs):
    rm, pm = mgrs
    ar = _ar(rm, db_session, _policy(pm, db_session))
    cited = rm.to_read_dict(db_session, ar)["policy"]
    assert cited["problem"] is None and [c["ref"] for c in cited["clauses"]] == ["§7.1"]


def test_concept_lookup_excludes_ars_without_a_valid_root(db_session, mgrs, monkeypatch):
    rm, pm = mgrs
    ar = _ar(rm, db_session, _policy(pm, db_session, approve=False))
    ar.status = "active"
    db_session.flush()
    from src.repositories import semantic_links_repository as slr
    monkeypatch.setattr(slr.entity_semantic_links_repo, "list_for_iri",
                        lambda db, iri: [SimpleNamespace(entity_type="authority_relation", entity_id=ar.id)])
    out = rm.find_authority_for_concept(db_session, "urn:c")
    assert out["resolved"] is None and out["candidates"][0]["policy_problem"]


# ------------------------------------------------------------- documents

def _upload(content: bytes):
    return UploadFile(file=BytesIO(content), filename="doa.pdf")


def _call_upload(db, entity_type, entity_id, content, manager):
    from src.routes.metadata_routes import upload_document
    ws = MagicMock()
    return asyncio.run(upload_document(
        entity_type=entity_type, entity_id=entity_id, request=SimpleNamespace(client=None),
        db=db, audit_manager=MagicMock(), current_user=None, title="DoA", short_description=None,
        file=_upload(content), manager=manager, settings=MagicMock(), ws=ws, _=True,
    )), ws


def test_upload_stores_the_sha256_and_accepts_policy_documents(db_session, mgrs):
    import hashlib
    _, pm = mgrs
    draft = _policy(pm, db_session, approve=False)
    manager = MagicMock()
    manager.ensure_volume_path.return_value = "/Volumes/c/s/v"
    _, ws = _call_upload(db_session, "authority_policy", draft.id, b"%PDF-1.7 doa", manager)
    assert manager.create_document_record.call_args.kwargs["content_sha256"] == hashlib.sha256(b"%PDF-1.7 doa").hexdigest()
    ws.files.upload.assert_called_once()


def test_oversized_upload_is_refused_before_the_volume_write(db_session, mgrs, monkeypatch):
    from src.routes import metadata_routes
    monkeypatch.setattr(metadata_routes, "MAX_DOCUMENT_BYTES", 4)
    manager = MagicMock()
    draft = _policy(mgrs[1], db_session, approve=False)
    with pytest.raises(HTTPException) as e:
        _call_upload(db_session, "authority_policy", draft.id, b"12345", manager)
    assert e.value.status_code == 413
    manager.ensure_volume_path.assert_not_called()


def test_approved_policy_documents_are_immutable(db_session, mgrs):
    _, pm = mgrs
    p = _policy(pm, db_session)
    manager = MagicMock()
    with pytest.raises(HTTPException) as e:
        _call_upload(db_session, "authority_policy", p.id, b"x", manager)
    assert e.value.status_code == 409
    manager.ensure_volume_path.assert_not_called()


def test_metadata_entity_types_include_the_authority_entities():
    from src.models.metadata import DocumentCreate
    for kind in ("authority_relation", "authority_policy", "concept", "compliance_policy"):
        DocumentCreate(entity_id="x", entity_type=kind, title="t")


# ------------------------------------------------------------- review regressions

def test_approving_any_version_supersedes_every_approved_sibling(db_session, mgrs):
    _, pm = mgrs
    v1 = _policy(pm, db_session)
    v2 = pm.create_new_version(db_session, v1.id, "2")
    pm.set_status(db_session, v2.id, PolicyStatusRequest(status="approved", effective_from=NOW), "u")
    # A successor drafted from the old v1 still supersedes the approved v2.
    v3 = pm.create_new_version(db_session, v1.id, "3")
    pm.set_status(db_session, v3.id, PolicyStatusRequest(status="approved", effective_from=NOW + timedelta(days=5)), "u")
    db_session.refresh(v2)
    assert v2.status == "superseded"
    assert [p.version for p in pm.get_versions(db_session, v1.id) if p.status == "approved"] == ["3"]


def test_backdated_successor_flags_dependents_at_once(db_session, mgrs):
    rm, pm = mgrs
    v1 = _policy(pm, db_session, start=NOW - timedelta(days=100))
    ar = _ar(rm, db_session, v1)
    ar.status = "active"
    db_session.flush()
    v2 = pm.create_new_version(db_session, v1.id, "2")
    pm.set_status(db_session, v2.id, PolicyStatusRequest(status="approved", effective_from=NOW - timedelta(days=10)), "u")
    db_session.refresh(ar)
    assert ar.status == "needs_review"


def test_new_version_does_not_inherit_the_end_date_and_null_clears_it(db_session, mgrs):
    _, pm = mgrs
    v1 = _policy(pm, db_session, start=NOW - timedelta(days=10), end=NOW + timedelta(days=10))
    v2 = pm.create_new_version(db_session, v1.id, "2")
    assert v2.effective_to is None
    v2.effective_to = NOW - timedelta(days=30)
    db_session.flush()
    v2, err = pm.set_status(db_session, v2.id, PolicyStatusRequest(
        status="approved", effective_from=NOW, effective_to=None), "u")
    assert err is None and v2.effective_to is None


def test_approval_records_who_recorded_it(db_session, mgrs, monkeypatch):
    _, pm = mgrs
    notes = []
    monkeypatch.setattr(pm, "_log_timeline", lambda db, et, eid, msg: notes.append(msg))
    p = _policy(pm, db_session, approve=False)
    pm.set_status(db_session, p.id, PolicyStatusRequest(status="approved", approved_by="board@x", effective_from=NOW), "alice")
    assert any("Approved by board@x (recorded by alice)" in n for n in notes)


def test_dropping_the_policy_drops_rule_and_check_clause_citations(db_session, mgrs):
    rm, pm = mgrs
    ar = _ar(rm, db_session, _policy(pm, db_session), rule={"permission": {"constraint": [CEILING]}},
             criteria=[{"name": "c", "rule": "obj.value > 0", "policy_clause_ref": "§7.2"}])
    rm.update_relation(db_session, ar.id, AuthorityRelationUpdate(authority_policy_id=None))
    assert "clause" not in ar.rule["permission"]["constraint"][0]
    assert [c["policy_clause_ref"] for c in rm.to_read_dict(db_session, ar)["criteria"]] == [None]


def test_active_ar_repointed_at_a_draft_goes_to_review(db_session, mgrs):
    rm, pm = mgrs
    ar = _ar(rm, db_session, _policy(pm, db_session))
    ar.status = "active"
    db_session.flush()
    draft = _policy(pm, db_session, key="D", approve=False)
    rm.update_relation(db_session, ar.id, AuthorityRelationUpdate(authority_policy_id=draft.id, policy_clause_refs=[]))
    assert ar.status == "needs_review"


def test_deleting_a_policy_removes_its_documents(db_session, mgrs, monkeypatch):
    from src.controller.metadata_manager import MetadataManager
    from src.db_models.metadata import DocumentMetadataDb
    _, pm = mgrs
    monkeypatch.setattr(MetadataManager, "delete_document_files_after_commit", lambda self, db, paths, ws=None: None)
    draft = _policy(pm, db_session, approve=False)
    db_session.add(DocumentMetadataDb(entity_type="authority_policy", entity_id=draft.id, title="d",
                                      original_filename="d.pdf", storage_path="/v/d.pdf"))
    db_session.flush()
    assert pm.delete_policy(db_session, draft.id) is True
    assert db_session.query(DocumentMetadataDb).filter_by(entity_id=draft.id).count() == 0


def test_size_cap_applies_to_policy_documents_only(db_session, mgrs, monkeypatch):
    from src.routes import metadata_routes
    monkeypatch.setattr(metadata_routes, "MAX_DOCUMENT_BYTES", 4)
    manager = MagicMock()
    manager.ensure_volume_path.return_value = "/Volumes/c/s/v"
    _call_upload(db_session, "data_product", "dp1", b"12345", manager)
    manager.create_document_record.assert_called_once()
    _, pm = mgrs
    draft = _policy(pm, db_session, approve=False)
    with pytest.raises(HTTPException) as e:
        _call_upload(db_session, "authority_policy", draft.id, b"12345", MagicMock())
    assert e.value.status_code == 413
