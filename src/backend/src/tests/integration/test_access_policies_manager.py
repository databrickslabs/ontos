"""DB-backed tests for AccessPoliciesManager: lifecycle, versioning, references, evaluation."""
import pytest
from sqlalchemy.orm import Session

from src.controller.access_policies_manager import (
    KIND_ASSET_COLLECTION,
    KIND_AUDIENCE,
    KIND_POLICY,
    AccessPoliciesManager,
    AccessPolicyError,
    PrincipalAttributeSource,
)
from src.models.access_policies import (
    AccessPolicyCreate,
    AccessPolicyUpdate,
    CheckAccessRequest,
    CollectionCreate,
    PolicyImportRequest,
)

USER = "steward@example.com"
APPROVER = "approver@example.com"


class StaticRoles(PrincipalAttributeSource):
    name = "static"

    def __init__(self, roles):
        self.roles = roles

    def attributes(self, db, principal):
        return {"ontos:businessRole": self.roles.get(principal, [])}


@pytest.fixture
def mgr():
    return AccessPoliciesManager(attribute_sources=[StaticRoles({"ana@example.com": ["Analyst"]})])


def _activate(mgr, db, kind, row):
    row = mgr.change_status(db, kind, row.id, "under_review", USER)
    row = mgr.change_status(db, kind, row.id, "approved", APPROVER)
    return mgr.change_status(db, kind, row.id, "active", USER)


def _approve(mgr, db, kind, row):
    mgr.change_status(db, kind, row.id, "under_review", USER)
    return mgr.change_status(db, kind, row.id, "approved", APPROVER)


def _audience(mgr, db, **kw):
    data = {"name": "Analysts", "members": [], "refinement": [
        {"leftOperand": "ontos:businessRole", "operator": "eq", "rightOperand": "Analyst"}]}
    data.update(kw)
    return mgr.create(db, KIND_AUDIENCE, CollectionCreate(**data), USER)


def _policy(mgr, db, rules, **kw):
    return mgr.create(db, KIND_POLICY, AccessPolicyCreate(name=kw.pop("name", "Sales read"), rules=rules, **kw), USER)


def test_create_assigns_family_uid_and_defaults(mgr, db_session: Session):
    p = _policy(mgr, db_session, {"permission": [{"target": "uc:main.sales", "action": "read"}]})
    assert p.status == "draft" and p.version == "1.0.0"
    assert p.uid == f"urn:ontos:policy:{p.version_family_id}"
    assert p.conflict == "prohibit"  # Ontos-authored default (spec default would be invalid)
    d = mgr.to_read_dict(db_session, KIND_POLICY, p)
    assert d["rule_counts"]["permission"] == 1 and d["allowed_transitions"] == ["under_review"]


def test_status_transitions_and_edit_lock(mgr, db_session: Session):
    p = _policy(mgr, db_session, {"permission": [{"target": "uc:main.sales", "action": "read"}]})
    with pytest.raises(AccessPolicyError) as e:
        mgr.change_status(db_session, KIND_POLICY, p.id, "active", USER)
    assert e.value.status_code == 409
    p = _activate(mgr, db_session, KIND_POLICY, p)
    assert p.status == "active"
    with pytest.raises(AccessPolicyError):
        mgr.update(db_session, KIND_POLICY, p.id, AccessPolicyUpdate(rules={}), USER)
    # Metadata edits remain possible.
    p = mgr.update(db_session, KIND_POLICY, p.id, AccessPolicyUpdate(description="clarified"), USER)
    assert p.description == "clarified"
    with pytest.raises(AccessPolicyError):
        mgr.delete(db_session, KIND_POLICY, p.id, USER)


def test_activation_requires_valid_body_and_active_references(mgr, db_session: Session):
    aud = _audience(mgr, db_session)
    p = _policy(mgr, db_session, {"permission": [{"target": "uc:main.sales", "action": "read", "assignee": aud.uid}]})
    _approve(mgr, db_session, KIND_POLICY, p)
    with pytest.raises(AccessPolicyError) as e:
        mgr.change_status(db_session, KIND_POLICY, p.id, "active", USER)
    assert "has no active version" in str(e.value)
    _activate(mgr, db_session, KIND_AUDIENCE, aud)
    assert mgr.change_status(db_session, KIND_POLICY, p.id, "active", USER).status == "active"

    bad = _policy(mgr, db_session, {"permission": [{"target": "uc:x", "action": "teleport"}]}, name="Bad")
    _approve(mgr, db_session, KIND_POLICY, bad)
    with pytest.raises(AccessPolicyError) as e:
        mgr.change_status(db_session, KIND_POLICY, bad.id, "active", USER)
    assert "Unknown action" in str(e.value)


def test_new_version_and_single_active_per_family(mgr, db_session: Session):
    p1 = _activate(mgr, db_session, KIND_POLICY,
                   _policy(mgr, db_session, {"permission": [{"target": "uc:main.sales", "action": "read"}]}))
    p2 = mgr.create_new_version(db_session, KIND_POLICY, p1.id, "1.1.0", "add modify", USER)
    assert p2.uid == p1.uid and p2.parent_id == p1.id and p2.status == "draft"
    with pytest.raises(AccessPolicyError):
        mgr.create_new_version(db_session, KIND_POLICY, p1.id, "1.1.0", None, USER)
    mgr.update(db_session, KIND_POLICY, p2.id, AccessPolicyUpdate(
        rules={"permission": [{"target": "uc:main.sales", "action": ["read", "modify"]}]}), USER)
    _activate(mgr, db_session, KIND_POLICY, p2)
    db_session.refresh(p1)
    assert p1.status == "deprecated"
    listed = mgr.list(db_session, KIND_POLICY)
    assert [r.id for r in listed] == [p2.id] and listed[0]._version_count == 2


def test_check_access_with_dynamic_audience_and_business_roles(mgr, db_session: Session):
    aud = _activate(mgr, db_session, KIND_AUDIENCE, _audience(mgr, db_session))
    col = _activate(mgr, db_session, KIND_ASSET_COLLECTION, mgr.create(db_session, KIND_ASSET_COLLECTION, CollectionCreate(
        name="Restricted", members=["uc:main"],
        refinement=[{"leftOperand": "ontos:classification", "operator": "eq", "rightOperand": "restricted"}]), USER))
    _activate(mgr, db_session, KIND_POLICY, _policy(mgr, db_session, {
        "permission": [{"target": "uc:main.sales", "action": "read", "assignee": aud.uid}],
        "prohibition": [{"target": col.uid, "action": "use", "assignee": aud.uid}],
    }))
    ok = mgr.check_access(db_session, CheckAccessRequest(principal="ana@example.com", action="read", asset="uc:main.sales.orders"))
    assert ok["verdict"] == "allow" and ok["resolved_principal_attributes"] == {"ontos:businessRole": ["Analyst"]}
    other = mgr.check_access(db_session, CheckAccessRequest(principal="bob@example.com", action="read", asset="uc:main.sales.orders"))
    assert other["verdict"] == "not_applicable"
    restricted = mgr.check_access(db_session, CheckAccessRequest(
        principal="ana@example.com", action="read", asset="uc:main.sales.orders",
        asset_attributes={"ontos:classification": "restricted"}))
    assert restricted["verdict"] == "deny"


def test_what_if_evaluates_drafts(mgr, db_session: Session):
    p = _policy(mgr, db_session, {"permission": [{"target": "uc:main", "action": "use"}]})
    req = dict(principal="x@example.com", action="modify", asset="uc:main.a.b")
    assert mgr.check_access(db_session, CheckAccessRequest(**req))["verdict"] == "not_applicable"
    assert mgr.check_access(db_session, CheckAccessRequest(**req, policy_ids=[p.id]))["verdict"] == "allow"


def test_referenced_audience_cannot_be_deleted_or_retired(mgr, db_session: Session):
    aud = _audience(mgr, db_session)
    _policy(mgr, db_session, {"permission": [{"target": "uc:main", "action": "read", "assignee": aud.uid}]})
    with pytest.raises(AccessPolicyError) as e:
        mgr.delete(db_session, KIND_AUDIENCE, aud.id, USER)
    assert "Still referenced" in str(e.value)
    used = mgr.to_read_dict(db_session, KIND_AUDIENCE, aud)["used_by"]
    assert len(used) == 1


def test_jsonld_export_import_round_trip(mgr, db_session: Session):
    p = _policy(mgr, db_session, {"permission": [{
        "target": "uc:main.sales", "action": "read",
        "constraint": [{"leftOperand": "purpose", "operator": "eq", "rightOperand": "analytics"}]}]})
    doc = mgr.to_jsonld(db_session, p)
    assert doc["@type"] == "Set" and doc["uid"] == p.uid and doc["conflict"] == "prohibit"
    imported = mgr.import_jsonld(db_session, PolicyImportRequest(document=doc), USER)
    assert imported.body == p.body and imported.name == p.name and imported.uid != p.uid
    with pytest.raises(AccessPolicyError):
        mgr.import_jsonld(db_session, PolicyImportRequest(document={**doc, "profile": "http://other/profile"}), USER)


# ------------------------------------------------------------ review findings

def test_author_cannot_approve_own_version_but_admin_can(mgr, db_session: Session):
    p = _policy(mgr, db_session, {"permission": [{"target": "uc:main", "action": "read"}]})
    mgr.change_status(db_session, KIND_POLICY, p.id, "under_review", USER)
    with pytest.raises(AccessPolicyError) as e:
        mgr.change_status(db_session, KIND_POLICY, p.id, "approved", USER)
    assert e.value.status_code == 403
    row = mgr.change_status(db_session, KIND_POLICY, p.id, "approved", USER, is_admin=True)
    assert row.status == "approved"


def test_content_only_editable_in_draft(mgr, db_session: Session):
    p = _policy(mgr, db_session, {"permission": [{"target": "uc:main", "action": "read"}]})
    mgr.change_status(db_session, KIND_POLICY, p.id, "under_review", USER)
    with pytest.raises(AccessPolicyError):
        mgr.update(db_session, KIND_POLICY, p.id, AccessPolicyUpdate(rules={}), USER)
    p = _activate(mgr, db_session, KIND_POLICY, mgr.change_status(db_session, KIND_POLICY, p.id, "draft", USER))
    mgr.change_status(db_session, KIND_POLICY, p.id, "needs_review", USER)
    with pytest.raises(AccessPolicyError):
        mgr.update(db_session, KIND_POLICY, p.id, AccessPolicyUpdate(rules={}), USER)


def test_referenced_audience_cannot_be_deprecated(mgr, db_session: Session):
    aud = _activate(mgr, db_session, KIND_AUDIENCE, _audience(mgr, db_session))
    _activate(mgr, db_session, KIND_POLICY, _policy(mgr, db_session, {
        "prohibition": [{"target": "uc:hr", "action": "read", "assignee": aud.uid}]}))
    with pytest.raises(AccessPolicyError) as e:
        mgr.change_status(db_session, KIND_AUDIENCE, aud.id, "deprecated", USER)
    assert "Still used by active policies" in str(e.value)


def test_personal_drafts_hidden_from_other_users(mgr, db_session: Session):
    p = mgr.create(db_session, KIND_POLICY, AccessPolicyCreate(
        name="Mine", personal_draft=True, rules={"permission": [{"target": "uc:main", "action": "use"}]}), USER)
    assert mgr.require_visible(db_session, KIND_POLICY, p.id, USER, False).id == p.id
    with pytest.raises(AccessPolicyError) as e:
        mgr.require_visible(db_session, KIND_POLICY, p.id, "other@example.com", False)
    assert e.value.status_code == 404
    req = CheckAccessRequest(principal="x@example.com", action="read", asset="uc:main.a", policy_ids=[p.id])
    assert mgr.check_access(db_session, req, viewer="other@example.com", is_admin=False)["evaluated_policies"] == []


def test_stored_logical_constraints_and_refinements_survive_resave(mgr, db_session: Session):
    doc = {"@type": "Set", "uid": "http://example.com/p:1", "conflict": "prohibit", "permission": [{
        "target": "uc:main", "assignee": "group:analysts",
        "action": [{"rdf:value": {"@id": "odrl:read"}, "refinement": [
            {"leftOperand": "purpose", "operator": "eq", "rightOperand": "analytics"}]}],
        "constraint": [{"or": {"@list": [
            {"leftOperand": "spatial", "operator": "eq", "rightOperand": "EU"},
            {"leftOperand": "spatial", "operator": "eq", "rightOperand": "UK"}]}}]}]}
    p = mgr.import_jsonld(db_session, PolicyImportRequest(document=doc), USER)
    rule = p.body["permission"][0]
    assert rule["constraint"][0]["logical"] == "or" and len(rule["constraint"][0]["constraints"]) == 2
    assert rule["action_refinement"][0]["leftOperand"] == "purpose"
    p = mgr.update(db_session, KIND_POLICY, p.id, AccessPolicyUpdate(rules=p.body), USER)  # JSON-tab round trip
    assert p.body["permission"][0] == rule
