"""Product Offers: a Data Product's terms of use bind every Agreement concluded for it (Phase 3)."""
import uuid

import pytest
from sqlalchemy.orm import Session

from src.controller.access_grants_manager import AccessGrantsManager
from src.controller.access_policies_manager import (
    KIND_POLICY,
    AccessPoliciesManager,
    AccessPolicyError,
)
from src.controller.access_policy_releases_manager import PolicyReleaseManager
from src.db_models.access_grants import AccessGrantRequestDb
from src.db_models.access_policies import AccessPolicyDb
from src.db_models.data_products import DataProductDb, OutputPortDb
from src.models.access_grants import AccessGrantHandlePayload
from src.models.access_policies import AccessPolicyCreate

OWNER = "owner@example.com"
APPROVER = "approver@example.com"


@pytest.fixture
def policies():
    return AccessPoliciesManager(attribute_sources=[])


@pytest.fixture
def product(db_session: Session):
    dp = DataProductDb(id=str(uuid.uuid4()), name="Sales", version="1.0.0", status="active")
    db_session.add(dp)
    db_session.flush()
    db_session.add(OutputPortDb(product_id=dp.id, name="orders", version="1.0.0", asset_type="table",
                                asset_identifier="main.sales.orders", status="active"))
    db_session.flush()
    return dp


def _offer(policies, db, product, status="active"):
    o = policies.create(db, KIND_POLICY, AccessPolicyCreate(
        name="Sales terms", policy_type="Offer", subject_entity_type="data_product", subject_entity_id=product.id,
        rules={"permission": [{"target": "uc:main.sales", "action": "read", "assigner": f"user:{OWNER}"}],
               "prohibition": [{"target": "uc:main.sales", "action": "distribute", "assigner": f"user:{OWNER}"}]}), OWNER)
    if status == "active":
        policies.change_status(db, KIND_POLICY, o.id, "under_review", OWNER)
        policies.change_status(db, KIND_POLICY, o.id, "approved", APPROVER)
        o = policies.change_status(db, KIND_POLICY, o.id, "active", OWNER)
    return o


def _approve(db, product, email="ana@example.com"):
    req = AccessGrantRequestDb(requester_email=email, entity_type="data_product", entity_id=product.id,
                               entity_name=product.name, requested_duration_days=30, permission_level="READ",
                               status="pending")
    db.add(req)
    db.flush()
    _, grant = AccessGrantsManager().handle_request(db, APPROVER, AccessGrantHandlePayload(request_id=req.id, approved=True))
    return db.query(AccessPolicyDb).filter(AccessPolicyDb.access_grant_id == str(grant.id)).one()


def test_offer_is_scoped_to_a_product_and_listed(policies, product, db_session: Session):
    offer = _offer(policies, db_session, product)
    d = policies.to_read_dict(db_session, KIND_POLICY, offer)
    assert (d["subject_entity_type"], d["subject_name"]) == ("data_product", "Sales")
    assert [o.id for o in policies.offers_for(db_session, "data_product", product.id)] == [offer.id]


def test_subject_must_exist(policies, db_session: Session):
    with pytest.raises(AccessPolicyError):
        policies.create(db_session, KIND_POLICY, AccessPolicyCreate(
            name="x", policy_type="Offer", subject_entity_type="data_product", subject_entity_id="nope"), OWNER)
    with pytest.raises(AccessPolicyError):
        policies.create(db_session, KIND_POLICY, AccessPolicyCreate(
            name="x", policy_type="Offer", subject_entity_type="team", subject_entity_id="t"), OWNER)


def test_agreement_snapshots_the_offer_terms_bound_to_the_grantee(policies, product, db_session: Session):
    offer = _offer(policies, db_session, product)
    agreement = _approve(db_session, product)
    assert agreement.inherit_from == [] and "Sales terms" in agreement.description
    assert [(r["action"], r["assignee"]) for r in agreement.body["prohibition"]] == [("distribute", "user:ana@example.com")]
    assert [r["target"] for r in agreement.body["permission"]] == ["uc:main.sales.orders"]
    # Retiring the Offer later doesn't rewrite or break the concluded Agreement.
    policies.change_status(db_session, KIND_POLICY, offer.id, "deprecated", OWNER)
    compiled = PolicyReleaseManager(policies).compile(db_session, "uc")
    assert not compiled["has_errors"]
    assert {(g["principal"], g["privilege"]) for g in compiled["plan"]["grants"] if g["privilege"] == "SELECT"} == {
        ("ana@example.com", "SELECT")}


def test_the_offer_itself_entitles_nobody(policies, product, db_session: Session):
    _offer(policies, db_session, product)
    compiled = PolicyReleaseManager(policies).compile(db_session, "uc")
    assert compiled["plan"]["grants"] == []
    assert [g["gate"] for g in compiled["plan"]["gated"]] == ["workflow"]


def test_draft_offers_are_not_applied(policies, product, db_session: Session):
    _offer(policies, db_session, product, status="draft")
    assert _approve(db_session, product).body.get("prohibition") == []


# ------------------------------------------------------------ /review findings (P3b)

def test_offer_permission_duties_reach_the_agreement_and_approval_counts_as_obtained(policies, product, db_session: Session):
    o = policies.create(db_session, KIND_POLICY, AccessPolicyCreate(
        name="Terms", policy_type="Offer", subject_entity_type="data_product", subject_entity_id=product.id,
        rules={"permission": [{"target": "uc:main.sales", "action": "read", "assigner": f"user:{OWNER}",
                               "duty": [{"action": "ontos:acknowledgeTerms"}, {"action": "ontos:obtainApproval"}]}]}), OWNER)
    for st, who in (("under_review", OWNER), ("approved", APPROVER), ("active", OWNER)):
        policies.change_status(db_session, KIND_POLICY, o.id, st, who)
    agreement = _approve(db_session, product)
    assert [d["action"] for d in agreement.body["permission"][0]["duty"]] == ["ontos:acknowledgeTerms"]
    compiled = PolicyReleaseManager(policies).compile(db_session, "uc")
    assert compiled["plan"]["grants"] == []  # gated until the terms are acknowledged


def test_terms_the_offer_inherits_are_snapshotted_too(policies, product, db_session: Session):
    base = policies.create(db_session, KIND_POLICY, AccessPolicyCreate(
        name="Baseline", policy_type="Set",
        rules={"prohibition": [{"target": "uc:main", "action": "distribute"}]}), OWNER)
    for st, who in (("under_review", OWNER), ("approved", APPROVER), ("active", OWNER)):
        policies.change_status(db_session, KIND_POLICY, base.id, st, who)
    o = policies.create(db_session, KIND_POLICY, AccessPolicyCreate(
        name="Terms", policy_type="Offer", subject_entity_type="data_product", subject_entity_id=product.id,
        inherit_from=[base.uid],
        rules={"permission": [{"target": "uc:main.sales", "action": "read", "assigner": f"user:{OWNER}"}]}), OWNER)
    for st, who in (("under_review", OWNER), ("approved", APPROVER), ("active", OWNER)):
        policies.change_status(db_session, KIND_POLICY, o.id, st, who)
    assert [r["action"] for r in _approve(db_session, product).body["prohibition"]] == ["distribute"]


def test_unbound_offer_prohibitions_bind_only_agreement_holders(policies, product, db_session: Session):
    _offer(policies, db_session, product)
    s = policies.create(db_session, KIND_POLICY, AccessPolicyCreate(
        name="Team", rules={"permission": [{"target": "uc:main.sales", "action": "distribute", "assignee": "group:x"}]}), OWNER)
    for st, who in (("under_review", OWNER), ("approved", APPROVER), ("active", OWNER)):
        policies.change_status(db_session, KIND_POLICY, s.id, st, who)
    from src.common import odrl_compiler  # noqa: F401
    compiled = PolicyReleaseManager(policies).compile(db_session, "uc")
    assert not compiled["has_errors"]  # the Offer's distribute prohibition doesn't deny group:x


def test_subject_only_on_offers_and_cleared_when_type_changes(policies, product, db_session: Session):
    from src.models.access_policies import AccessPolicyUpdate
    with pytest.raises(AccessPolicyError):
        policies.create(db_session, KIND_POLICY, AccessPolicyCreate(
            name="x", policy_type="Set", subject_entity_type="data_product", subject_entity_id=product.id), OWNER)
    o = _offer(policies, db_session, product, status="draft")
    o = policies.update(db_session, KIND_POLICY, o.id, AccessPolicyUpdate(policy_type="Set"), OWNER)
    assert (o.subject_entity_type, o.subject_entity_id) == (None, None)


def test_only_product_owners_can_state_its_terms(policies, product, db_session: Session):
    with pytest.raises(AccessPolicyError) as e:
        policies.create(db_session, KIND_POLICY, AccessPolicyCreate(
            name="x", policy_type="Offer", subject_entity_type="data_product", subject_entity_id=product.id),
            OWNER, can_manage_subject=lambda p: False)
    assert e.value.status_code == 403


def test_offers_with_inactive_collapse_per_family(policies, product, db_session: Session):
    o = _offer(policies, db_session, product)
    policies.create_new_version(db_session, KIND_POLICY, o.id, "1.1.0", None, OWNER)
    assert len(policies.offers_for(db_session, "data_product", product.id, active_only=False)) == 1


def test_assignee_binding_is_independent_of_parent_order():
    from src.common import odrl
    offer = {"@type": "Offer", "uid": "o", "conflict": "prohibit",
             "prohibition": [{"target": "uc:m", "action": "distribute", "assigner": "user:o@x"}]}
    base = {"@type": "Set", "uid": "b", "conflict": "prohibit",
            "permission": [{"target": "uc:m", "action": "read", "assignee": "group:all"}]}
    child = odrl.normalize_policy({"@type": "Set", "uid": "c", "conflict": "prohibit",
                                   "permission": [{"target": "uc:m", "action": "read", "assignee": "user:a@x"}]})
    look = {"o": offer, "b": base}.get
    bound = []
    for order in (["b", "o"], ["o", "b"]):
        merged, _ = odrl.resolve_inheritance({**child, "inheritFrom": order}, look)
        bound.append(sorted(r["assignee"] for r in merged["prohibition"]))
    assert bound[0] == bound[1] == ["user:a@x"]
