"""Access Grants → ODRL Agreements → compiled grants / agreement-scoped releases (Phase 3)."""
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from src.controller import access_agreements
from src.controller.access_agreements import AgreementService, entity_targets
from src.controller.access_grants_manager import AccessGrantsManager
from src.controller.access_policies_manager import AccessPoliciesManager
from src.controller.access_policy_releases_manager import PolicyReleaseManager
from src.controller.delivery_service import DeliveryMode, DeliveryService
from src.db_models.access_grants import AccessGrantRequestDb
from src.db_models.access_policies import AccessPolicyDb
from src.db_models.data_products import DataProductDb, OutputPortDb
from src.models.access_grants import AccessGrantHandlePayload

ADMIN = "admin@example.com"
REQUESTER = "Ana@Example.com"


class FakeGrants:
    def __init__(self):
        self.calls = []

    def apply_grant(self, data, dry_run=False):
        self.calls.append(("grant", data["principal"], data["securable_name"], tuple(data["privileges"])))
        return {"success": True}

    def apply_revoke(self, data, dry_run=False):
        self.calls.append(("revoke", data["principal"], data["securable_name"], tuple(data["privileges"])))
        return {"success": True}


def _delivery(grants):
    svc = DeliveryService(settings=SimpleNamespace(DELIVERY_DIRECT_DRY_RUN=False), grant_manager=grants)
    svc.get_active_modes = lambda: [DeliveryMode.DIRECT]
    return svc


@pytest.fixture
def product(db_session: Session):
    dp = DataProductDb(id=str(uuid.uuid4()), name="Sales", version="1.0.0", status="active",
                       )
    db_session.add(dp)
    db_session.flush()
    for name, ident, status in (("orders", "main.sales.orders", "active"), ("old", "main.sales.old", "deprecated"),
                                ("none", None, "active")):
        db_session.add(OutputPortDb(product_id=dp.id, name=name, version="1.0.0", asset_type="table",
                                    asset_identifier=ident, status=status))
    db_session.flush()
    return dp


def _approve(db, product, duration=30):
    req = AccessGrantRequestDb(requester_email=REQUESTER, entity_type="data_product", entity_id=product.id,
                               entity_name=product.name, requested_duration_days=duration, permission_level="READ",
                               status="pending")
    db.add(req)
    db.flush()
    return AccessGrantsManager().handle_request(db, ADMIN, AccessGrantHandlePayload(request_id=req.id, approved=True))


def test_entity_targets_use_active_output_ports(product, db_session: Session):
    assert entity_targets(db_session, "data_product", product.id) == ["uc:main.sales.orders"]
    assert entity_targets(db_session, "data_contract", "x") == []


def test_approved_grant_becomes_active_agreement_that_compiles_with_expiry(product, db_session: Session):
    _, grant = _approve(db_session, product)
    agreement = db_session.query(AccessPolicyDb).filter(AccessPolicyDb.access_grant_id == str(grant.id)).one()
    assert agreement.policy_type == "Agreement" and agreement.status == "active"
    assert (agreement.submitted_by, agreement.approved_by) == (REQUESTER, ADMIN)
    rule = agreement.body["permission"][0]
    assert rule["assignee"] == f"user:{REQUESTER}" and rule["assigner"] == f"user:{ADMIN}" and rule["action"] == "read"

    compiled = PolicyReleaseManager(AccessPoliciesManager(attribute_sources=[])).compile(db_session, "uc")
    select = [g for g in compiled["plan"]["grants"] if g["privilege"] == "SELECT"]
    assert [(g["principal"], g["securable_name"]) for g in select] == [("ana@example.com", "main.sales.orders")]
    assert select[0]["expires_at"].startswith(grant.expires_at.date().isoformat())


def test_revoking_the_grant_retires_the_agreement(product, db_session: Session, monkeypatch):
    from src.db_models.access_grants import AccessGrantDb
    # SQLite returns naive datetimes; the response's days_until_expiry would fail on them (Postgres is aware).
    monkeypatch.setattr(AccessGrantDb, "days_until_expiry", property(lambda self: None))
    _, grant = _approve(db_session, product)
    AccessGrantsManager().revoke_grant(db_session, grant.id, ADMIN, "no longer needed")
    agreement = db_session.query(AccessPolicyDb).filter(AccessPolicyDb.access_grant_id == str(grant.id)).one()
    assert agreement.status == "retired"


def test_agreement_scoped_release_ships_only_its_grants_and_revokes_them(product, db_session: Session):
    policies = AccessPoliciesManager(attribute_sources=[])
    _, grant = _approve(db_session, product)
    # An unrelated, unreleased active policy must not ride along.
    other = AccessPolicyDb(name="Other", status="active", policy_type="Set", conflict="prohibit", body=policies._normalize_rules(
        "Set", "prohibit", [], {"permission": [{"target": "uc:hr", "action": "read", "assignee": "group:hr"}]}))
    db_session.add(other)
    db_session.flush()
    agreement = db_session.query(AccessPolicyDb).filter(AccessPolicyDb.access_grant_id == str(grant.id)).one()
    grants = FakeGrants()
    release = AgreementService(policies).deliver(db_session, [agreement], ADMIN, _delivery(grants))
    assert release.release_kind == "agreement" and release.status == "applied"
    assert {c[2] for c in grants.calls} == {"main", "main.sales", "main.sales.orders"}

    AgreementService(policies).retire_for_grant(db_session, grant.id, ADMIN, "revoked")
    grants.calls.clear()
    rev = AgreementService(policies).deliver(db_session, [agreement], ADMIN, _delivery(grants), revoke=True)
    assert rev.status == "applied" and grants.calls == [("revoke", "ana@example.com", "main.sales.orders", ("SELECT",))]


def test_auto_deliver_is_opt_in(product, db_session: Session, monkeypatch):
    called = []
    monkeypatch.setattr(AgreementService, "prepare_release", lambda *a, **k: called.append(1))
    access_agreements.auto_deliver(db_session, [object()], ADMIN, revoke=False)
    assert called == []
    from src.common.config import get_settings
    assert get_settings().ACCESS_AGREEMENTS_AUTO_REVOKE is True  # revocation ships by default


def test_agreement_failure_never_blocks_approval(product, db_session: Session, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(AgreementService, "create_for_grant", boom)
    request, grant = _approve(db_session, product)
    assert grant is not None and request.status.lower() == "approved"



# ------------------------------------------------------------ /review findings (P3a)

def _agreement(db, grant):
    return db.query(AccessPolicyDb).filter(AccessPolicyDb.access_grant_id == str(grant.id)).order_by(
        AccessPolicyDb.created_at).all()[-1]


def test_permission_levels_are_cumulative(product, db_session: Session):
    req = AccessGrantRequestDb(requester_email=REQUESTER, entity_type="data_product", entity_id=product.id,
                               entity_name=product.name, requested_duration_days=30, permission_level="WRITE",
                               status="pending")
    db_session.add(req)
    db_session.flush()
    _, grant = AccessGrantsManager().handle_request(db_session, ADMIN, AccessGrantHandlePayload(request_id=req.id, approved=True))
    assert sorted(r["action"] for r in _agreement(db_session, grant).body["permission"]) == ["modify", "read"]


def test_targets_are_strict_about_uc_names(product, db_session: Session):
    db_session.add(OutputPortDb(product_id=product.id, name="topic", version="1.0.0", asset_type="kafka_topic",
                                asset_identifier="a.b.c", status="active"))
    db_session.add(OutputPortDb(product_id=product.id, name="flat", version="1.0.0", asset_type="table",
                                asset_identifier="sales", status="active"))
    db_session.flush()
    assert entity_targets(db_session, "data_product", product.id) == ["uc:main.sales.orders"]
    assert entity_targets(db_session, "asset", str(uuid.uuid4())) == []
    assert entity_targets(db_session, "schema", "main.sales") == ["uc:main.sales"]
    assert entity_targets(db_session, "catalog", "main.sales") == []


def test_renewal_ships_the_later_expiry(product, db_session: Session):
    policies = AccessPoliciesManager(attribute_sources=[])
    _, first = _approve(db_session, product, duration=10)
    AgreementService(policies).deliver(db_session, [_agreement(db_session, first)], ADMIN, _delivery(FakeGrants()))
    _, second = _approve(db_session, product, duration=60)
    release = AgreementService(policies).deliver(db_session, [_agreement(db_session, second)], ADMIN, _delivery(FakeGrants()))
    assert release is not None and release.changes["update"]
    rm = PolicyReleaseManager(policies)
    select = [x for x in rm.ledger(db_session, "uc") if x["privilege"] == "SELECT"][0]
    assert select["expires_at"].startswith(second.expires_at.date().isoformat())


def test_new_agreement_version_stays_linked_to_its_grant(product, db_session: Session):
    policies = AccessPoliciesManager(attribute_sources=[])
    _, grant = _approve(db_session, product)
    v2 = policies.create_new_version(db_session, "policy", _agreement(db_session, grant).id, "1.1.0", None, ADMIN)
    assert v2.access_grant_id == str(grant.id)
    AgreementService(policies).retire_for_grant(db_session, grant.id, ADMIN, "revoked")
    assert {a.status for a in AgreementService(policies).for_grant(db_session, grant.id)} == {"retired"}


def test_agreement_release_neither_supersedes_nor_breaks_a_reviewed_policy_release(product, db_session: Session):
    policies = AccessPoliciesManager(attribute_sources=[])
    rm = PolicyReleaseManager(policies)
    other = AccessPolicyDb(name="HR", status="active", policy_type="Set", conflict="prohibit", body=policies._normalize_rules(
        "Set", "prohibit", [], {"permission": [{"target": "uc:hr.people.t", "action": "read", "assignee": "group:hr"}]}))
    db_session.add(other)
    db_session.flush()
    _, grant = _approve(db_session, product)
    reviewed = rm.create_release(db_session, "uc", "steward@example.com")  # includes the Agreement's grants too
    rm.change_status(db_session, reviewed.id, "under_review", "steward@example.com")
    rm.change_status(db_session, reviewed.id, "approved", "approver@example.com")
    AgreementService(policies).deliver(db_session, [_agreement(db_session, grant)], ADMIN, _delivery(FakeGrants()))
    db_session.refresh(reviewed)
    assert reviewed.status == "approved"
    grants = FakeGrants()
    out = rm.deliver(db_session, reviewed.id, ADMIN, _delivery(grants))  # re-based: only the HR grants remain
    assert out.status == "applied" and {c[1] for c in grants.calls} == {"hr"}


def test_scoped_release_does_not_refresh_unrelated_ledger_rows(product, db_session: Session):
    policies = AccessPoliciesManager(attribute_sources=[])
    rm = PolicyReleaseManager(policies)
    hr = AccessPolicyDb(name="HR", status="active", policy_type="Set", conflict="prohibit", body=policies._normalize_rules(
        "Set", "prohibit", [], {"permission": [{"target": "uc:hr.people.t", "action": "read", "assignee": "group:hr"}]}))
    db_session.add(hr)
    db_session.flush()
    r = rm.create_release(db_session, "uc", "steward@example.com")
    rm.change_status(db_session, r.id, "under_review", "steward@example.com")
    rm.change_status(db_session, r.id, "approved", "approver@example.com")
    rm.deliver(db_session, r.id, ADMIN, _delivery(FakeGrants()))
    # Unreleased edit: the HR policy now expires.
    hr.body = policies._normalize_rules("Set", "prohibit", [], {"permission": [{
        "target": "uc:hr.people.t", "action": "read", "assignee": "group:hr",
        "constraint": [{"leftOperand": "dateTime", "operator": "lteq", "rightOperand": "2099-01-01T00:00:00Z"}]}]})
    db_session.flush()
    _, grant = _approve(db_session, product)
    AgreementService(policies).deliver(db_session, [_agreement(db_session, grant)], ADMIN, _delivery(FakeGrants()))
    assert {x["expires_at"] for x in rm.ledger(db_session, "uc", principal="hr")} == {None}


def test_revoke_expired_skips_grants_pending_in_an_agreement_revocation(product, db_session: Session):
    from datetime import datetime, timezone

    from src.controller.access_policy_releases_manager import R_DELIVERED
    policies = AccessPoliciesManager(attribute_sources=[])
    rm = PolicyReleaseManager(policies)
    _, grant = _approve(db_session, product, duration=1)
    agreement = _agreement(db_session, grant)
    AgreementService(policies).deliver(db_session, [agreement], ADMIN, _delivery(FakeGrants()))
    AgreementService(policies).retire_for_grant(db_session, grant.id, ADMIN, "expired")
    pending = AgreementService(policies).prepare_release(db_session, [agreement], ADMIN, revoke=True)
    pending.status = R_DELIVERED
    db_session.flush()
    later = datetime(2099, 1, 1, tzinfo=timezone.utc)
    assert rm.revoke_expired(db_session, "uc", "system", _delivery(FakeGrants()), now=later).id == pending.id


def test_failed_auto_delivery_keeps_the_release_as_failed(product, db_session: Session, monkeypatch):
    from src.common.config import get_settings
    _, grant = _approve(db_session, product)
    monkeypatch.setattr(get_settings(), "ACCESS_AGREEMENTS_AUTO_DELIVER", True, raising=False)
    monkeypatch.setattr(access_agreements, "_delivery_service", lambda: _delivery(FakeGrants()))
    monkeypatch.setattr(PolicyReleaseManager, "deliver", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ledger flush")))
    # The fixture's outer transaction makes commit non-durable; emulate a real commit + rollback.
    monkeypatch.setattr(db_session, "rollback", db_session.expire_all)
    access_agreements.auto_deliver(db_session, [_agreement(db_session, grant)], ADMIN, revoke=False)
    from src.db_models.access_policies import AccessPolicyReleaseDb
    rows = db_session.query(AccessPolicyReleaseDb).filter(AccessPolicyReleaseDb.release_kind == "agreement").all()
    assert [r.status for r in rows] == ["failed"]
