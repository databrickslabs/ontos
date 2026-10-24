"""Duties on Agreements: the grantee accepts the terms, then the access compiles (Phase 3)."""
import uuid

import pytest
from sqlalchemy.orm import Session

from src.controller import access_agreements
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
from src.models.access_policies import AccessPolicyCreate, CheckAccessRequest

OWNER, APPROVER, GRANTEE = "owner@example.com", "approver@example.com", "ana@example.com"


@pytest.fixture
def policies():
    return AccessPoliciesManager(attribute_sources=[])


@pytest.fixture
def agreement(policies, db_session: Session):
    dp = DataProductDb(id=str(uuid.uuid4()), name="Sales", version="1.0.0", status="active")
    db_session.add(dp)
    db_session.flush()
    db_session.add(OutputPortDb(product_id=dp.id, name="orders", version="1.0.0", asset_type="table",
                                asset_identifier="main.sales.orders", status="active"))
    offer = policies.create(db_session, KIND_POLICY, AccessPolicyCreate(
        name="Terms", policy_type="Offer", subject_entity_type="data_product", subject_entity_id=dp.id,
        rules={"permission": [{"target": "uc:main.sales", "action": "read", "assigner": f"user:{OWNER}",
                               "duty": [{"action": "ontos:acknowledgeTerms"}, {"action": "ontos:recertify"}]}]}), OWNER)
    for st, who in (("under_review", OWNER), ("approved", APPROVER), ("active", OWNER)):
        policies.change_status(db_session, KIND_POLICY, offer.id, st, who)
    req = AccessGrantRequestDb(requester_email=GRANTEE, entity_type="data_product", entity_id=dp.id, entity_name="Sales",
                               requested_duration_days=30, permission_level="READ", status="pending")
    db_session.add(req)
    db_session.flush()
    _, grant = AccessGrantsManager().handle_request(db_session, APPROVER, AccessGrantHandlePayload(request_id=req.id, approved=True))
    return db_session.query(AccessPolicyDb).filter(AccessPolicyDb.access_grant_id == str(grant.id)).one()


def _select(policies, db):
    plan = PolicyReleaseManager(policies).compile(db, "uc")["plan"]
    return [g for g in plan["grants"] if g["privilege"] == "SELECT"]


def test_open_duties_gate_the_grant_and_the_grantee_is_notified(policies, agreement, db_session: Session):
    from src.db_models.notifications import NotificationDb
    assert _select(policies, db_session) == []
    status = {d["action"]: d for d in access_agreements.duty_status(agreement, GRANTEE, False)}
    assert status["ontos:acknowledgeTerms"]["can_fulfill"] and not status["ontos:recertify"]["can_fulfill"]
    assert db_session.query(NotificationDb).filter(NotificationDb.recipient == GRANTEE).count() == 1


def test_only_the_grantee_accepts_terms_and_only_admins_fulfil_the_rest(policies, agreement, db_session: Session):
    with pytest.raises(AccessPolicyError) as e:
        access_agreements.fulfill_duty(db_session, agreement, "ontos:acknowledgeTerms", APPROVER, True)
    assert e.value.status_code == 403
    with pytest.raises(AccessPolicyError) as e:
        access_agreements.fulfill_duty(db_session, agreement, "ontos:recertify", GRANTEE, False)
    assert e.value.status_code == 403
    access_agreements.fulfill_duty(db_session, agreement, "ontos:acknowledgeTerms", "Ana@Example.com", False, "I accept")
    with pytest.raises(AccessPolicyError):
        access_agreements.fulfill_duty(db_session, agreement, "ontos:acknowledgeTerms", GRANTEE, False)


def test_fulfilled_duties_make_the_grant_compile_and_check_access_allow(policies, agreement, db_session: Session):
    access_agreements.fulfill_duty(db_session, agreement, "ontos:acknowledgeTerms", GRANTEE, False)
    req = CheckAccessRequest(principal=GRANTEE, action="read", asset="uc:main.sales.orders", resolve_business_roles=False)
    assert policies.check_access(db_session, req)["verdict"] == "conditional"  # recertify still open
    assert _select(policies, db_session) == []
    access_agreements.fulfill_duty(db_session, agreement, "ontos:recertify", APPROVER, True)
    assert [g["principal"] for g in _select(policies, db_session)] == [GRANTEE]
    assert policies.check_access(db_session, req)["verdict"] == "allow"


def test_duties_only_on_agreements(policies, db_session: Session):
    s = policies.create(db_session, KIND_POLICY, AccessPolicyCreate(
        name="S", rules={"permission": [{"target": "uc:x", "action": "read", "duty": [{"action": "inform"}]}]}), OWNER)
    with pytest.raises(AccessPolicyError):
        access_agreements.fulfill_duty(db_session, s, "inform", OWNER, True)


# ------------------------------------------------------------ /review findings (P3c)

def test_admin_cannot_fulfil_admin_duties_on_their_own_agreement(policies, agreement, db_session: Session):
    with pytest.raises(AccessPolicyError) as e:
        access_agreements.fulfill_duty(db_session, agreement, "ontos:recertify", GRANTEE, True)
    assert e.value.status_code == 403


def test_duty_actions_are_normalized_and_labelled(policies, agreement, db_session: Session):
    access_agreements.fulfill_duty(db_session, agreement, "acknowledgeTerms", GRANTEE, False)
    status = {d["action"]: d for d in access_agreements.duty_status(agreement, GRANTEE, False)}
    assert status["ontos:acknowledgeTerms"]["fulfilled"] and status["ontos:acknowledgeTerms"]["label"] == "Acknowledge terms"


def test_notification_uses_the_stored_email_case(policies, db_session: Session):
    from src.db_models.notifications import NotificationDb
    agreement = AccessPolicyDb(name="A", status="active", policy_type="Agreement", conflict="prohibit", body={
        "permission": [{"target": "uc:x.y.z", "action": "read", "assignee": "user:Ana.Smith@Corp.com",
                        "duty": [{"action": "ontos:acknowledgeTerms"}]}]})
    db_session.add(agreement)
    db_session.flush()
    access_agreements._notify_open_duties(db_session, agreement)
    assert db_session.query(NotificationDb).filter(NotificationDb.recipient == "Ana.Smith@Corp.com").count() == 1


def test_a_failing_notification_does_not_hide_the_agreement(policies, db_session: Session, monkeypatch):
    monkeypatch.setattr(access_agreements, "duty_status", lambda *a, **k: (_ for _ in ()).throw(TypeError("bad body")))
    access_agreements._notify_open_duties(db_session, AccessPolicyDb(name="A", body={}))  # must not raise
