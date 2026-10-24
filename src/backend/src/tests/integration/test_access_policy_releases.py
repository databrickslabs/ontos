"""DB-backed tests for policy releases: compile → review → deliver (Delivery Modes) → Grant Ledger."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from src.controller.access_policies_manager import (
    KIND_POLICY,
    AccessPoliciesManager,
    AccessPolicyError,
)
from src.controller.access_policy_releases_manager import PolicyReleaseManager
from src.controller.delivery_service import DeliveryMode, DeliveryService
from src.models.access_policies import AccessPolicyCreate

AUTHOR = "author@example.com"
APPROVER = "approver@example.com"
ADMIN = "admin@example.com"


class FakeGrants:
    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on or set()

    def apply_grant(self, data, dry_run=False):
        self.calls.append(("grant", data["principal"], data["securable_name"], tuple(data["privileges"])))
        if data["securable_name"] in self.fail_on:
            return {"success": False, "error": "PERMISSION_DENIED"}
        return {"success": True}

    def apply_revoke(self, data, dry_run=False):
        self.calls.append(("revoke", data["principal"], data["securable_name"], tuple(data["privileges"])))
        return {"success": True}


class FakeGit:
    is_cloned = True

    def __init__(self):
        self.saved = []

    def save_yaml(self, filename, data, subdir=None):
        self.saved.append((subdir, filename, data))
        return True


class Delivery(DeliveryService):
    def __init__(self, modes, grants=None, git=None):
        super().__init__(settings=SimpleNamespace(DELIVERY_DIRECT_DRY_RUN=False), git_service=git, grant_manager=grants)
        self.modes = modes

    def get_active_modes(self):
        return list(self.modes)


@pytest.fixture
def policies():
    return AccessPoliciesManager(attribute_sources=[])


@pytest.fixture
def rm(policies):
    return PolicyReleaseManager(policies)


def _active_policy(policies, db, rules, name="Sales read"):
    p = policies.create(db, KIND_POLICY, AccessPolicyCreate(name=name, rules=rules), AUTHOR)
    policies.change_status(db, KIND_POLICY, p.id, "under_review", AUTHOR)
    policies.change_status(db, KIND_POLICY, p.id, "approved", APPROVER)
    return policies.change_status(db, KIND_POLICY, p.id, "active", AUTHOR)


def _approved_release(rm, db):
    r = rm.create_release(db, "uc", AUTHOR)
    rm.change_status(db, r.id, "under_review", AUTHOR)
    return rm.change_status(db, r.id, "approved", APPROVER)


SALES = {"permission": [{"target": "uc:main.sales.orders", "action": "read", "assignee": "group:analysts"}]}


def test_compile_creates_draft_with_diff_and_runbook(policies, rm, db_session: Session):
    _active_policy(policies, db_session, SALES)
    r = rm.create_release(db_session, "uc", AUTHOR)
    d = rm.to_read_dict(r)
    assert d["status"] == "draft" and d["sequence"] == 1 and d["counts"]["add"] == 3
    assert "GRANT SELECT ON TABLE `main`.`sales`.`orders` TO `analysts`;" in r.changes["sql"]
    assert d["source_policies"][0]["name"] == "Sales read"


def test_separation_of_duties_and_error_gate(policies, rm, db_session: Session):
    _active_policy(policies, db_session, SALES)
    r = rm.create_release(db_session, "uc", AUTHOR)
    rm.change_status(db_session, r.id, "under_review", AUTHOR)
    with pytest.raises(AccessPolicyError) as e:
        rm.change_status(db_session, r.id, "approved", AUTHOR)
    assert e.value.status_code == 403
    assert rm.change_status(db_session, r.id, "approved", APPROVER).approved_by == APPROVER

    _active_policy(policies, db_session, {
        "permission": [{"target": "uc:hr", "action": "read", "assignee": "group:all"}],
        "prohibition": [{"target": "uc:hr.salaries", "action": "read", "assignee": "group:all"}]}, name="Bad")
    bad = rm.create_release(db_session, "uc", AUTHOR)
    with pytest.raises(AccessPolicyError) as e:
        rm.change_status(db_session, bad.id, "under_review", AUTHOR)
    assert "compile errors" in str(e.value)


def test_direct_delivery_applies_and_tracks_in_ledger(policies, rm, db_session: Session):
    _active_policy(policies, db_session, SALES)
    grants = FakeGrants()
    r = rm.deliver(db_session, _approved_release(rm, db_session).id, ADMIN, Delivery([DeliveryMode.DIRECT], grants))
    assert r.status == "applied" and r.applied_by == ADMIN
    assert {c[2] for c in grants.calls} == {"main", "main.sales", "main.sales.orders"}
    ledger = rm.ledger(db_session, "uc")
    assert {(x["securable_name"], x["privilege"]) for x in ledger} == {
        ("main", "USE_CATALOG"), ("main.sales", "USE_SCHEMA"), ("main.sales.orders", "SELECT")}
    # Nothing changed since: the next release is empty and can't be submitted.
    nxt = rm.create_release(db_session, "uc", AUTHOR)
    with pytest.raises(AccessPolicyError):
        rm.change_status(db_session, nxt.id, "under_review", AUTHOR)


def test_indirect_writes_ontos_yaml_and_waits_for_confirmation(policies, rm, db_session: Session):
    _active_policy(policies, db_session, SALES)
    git = FakeGit()
    r = rm.deliver(db_session, _approved_release(rm, db_session).id, ADMIN, Delivery([DeliveryMode.INDIRECT], git=git))
    assert r.status == "delivered" and rm.ledger(db_session, "uc") == []
    subdir, filename, doc = git.saved[0]
    assert subdir == "access-policies/releases" and filename == "uc-release-00001.yaml"
    assert doc["kind"] == "AccessPolicyRelease" and len(doc["spec"]["changes"]["grant"]) == 3 and doc["spec"]["sql"]
    r = rm.confirm_applied(db_session, r.id, ADMIN, "merged PR #42")
    assert r.status == "applied" and len(rm.ledger(db_session, "uc")) == 3


def test_deprecating_policy_revokes_only_managed_grants(policies, rm, db_session: Session):
    p = _active_policy(policies, db_session, SALES)
    grants = FakeGrants()
    rm.deliver(db_session, _approved_release(rm, db_session).id, ADMIN, Delivery([DeliveryMode.DIRECT], grants))
    policies.change_status(db_session, KIND_POLICY, p.id, "deprecated", AUTHOR)
    grants.calls.clear()
    r = rm.deliver(db_session, _approved_release(rm, db_session).id, ADMIN, Delivery([DeliveryMode.DIRECT], grants))
    # Live state unreadable (fake has no get_grants): implied USE grants are treated as pre-existing.
    assert r.status == "applied" and grants.calls == [("revoke", "analysts", "main.sales.orders", ("SELECT",))]
    assert rm.ledger(db_session, "uc") == []
    assert len(rm.ledger(db_session, "uc", status="revoked")) == 1
    assert len(rm.ledger(db_session, "uc", status="released")) == 2


def test_partial_direct_failure_then_redeliver_remaining(policies, rm, db_session: Session):
    _active_policy(policies, db_session, SALES)
    r = rm.deliver(db_session, _approved_release(rm, db_session).id, ADMIN,
                   Delivery([DeliveryMode.DIRECT], FakeGrants(fail_on={"main.sales.orders"})))
    assert r.status == "failed" and len(rm.ledger(db_session, "uc")) == 2
    retry = FakeGrants()
    r = rm.deliver(db_session, r.id, ADMIN, Delivery([DeliveryMode.DIRECT], retry))
    assert r.status == "applied" and [c[2] for c in retry.calls] == ["main.sales.orders"]


def test_mode_must_be_enabled_and_stale_release_superseded(policies, rm, db_session: Session):
    _active_policy(policies, db_session, SALES)
    a = _approved_release(rm, db_session)
    with pytest.raises(AccessPolicyError):
        rm.deliver(db_session, a.id, ADMIN, Delivery([DeliveryMode.INDIRECT], git=FakeGit()), modes=["direct"])
    b = rm.create_release(db_session, "uc", AUTHOR)
    rm.deliver(db_session, a.id, ADMIN, Delivery([DeliveryMode.DIRECT], FakeGrants()))
    db_session.refresh(b)
    assert b.status == "superseded"


def test_expired_grants_are_revoked_through_a_revocation_release(policies, rm, db_session: Session):
    _active_policy(policies, db_session, {"permission": [{
        "target": "uc:main.sales", "action": "read", "assignee": "user:temp@example.com",
        "constraint": [{"leftOperand": "dateTime", "operator": "lteq", "rightOperand": "2099-01-01T00:00:00Z"}]}]})
    rm.deliver(db_session, _approved_release(rm, db_session).id, ADMIN, Delivery([DeliveryMode.DIRECT], FakeGrants()))
    assert {x["expires_at"] for x in rm.ledger(db_session, "uc")} == {"2099-01-01T00:00:00Z"}
    assert rm.revoke_expired(db_session, "uc", "system", Delivery([DeliveryMode.DIRECT], FakeGrants())) is None
    later = datetime(2099, 1, 2, tzinfo=timezone.utc)
    grants = FakeGrants()
    rev = rm.revoke_expired(db_session, "uc", "system", Delivery([DeliveryMode.DIRECT], grants), now=later)
    assert rev.release_kind == "revocation" and rev.status == "applied"
    assert {c[0] for c in grants.calls} == {"revoke"} and rm.ledger(db_session, "uc") == []


def test_live_diff_reports_drift(policies, rm, db_session: Session):
    _active_policy(policies, db_session, SALES)
    r = rm.create_release(db_session, "uc", AUTHOR)
    live = {("table", "main.sales.orders"): [{"principal": "analysts", "privileges": ["SELECT"]},
                                             {"principal": "someone", "privileges": ["MODIFY"]}]}
    report = rm.live_diff(db_session, r.id, lambda t, n: {"success": True, "grants": live.get((t, n), [])})
    assert {m["privilege"] for m in report["missing"]} == {"USE_CATALOG", "USE_SCHEMA"}
    assert report["unmanaged"] == [{"principal": "someone", "securable_type": "table",
                                    "securable_name": "main.sales.orders", "privilege": "MODIFY"}]


# ------------------------------------------------------------ review findings

class LiveGrants(FakeGrants):
    """Fake with readable live state: ``live[(type, name)] = [{"principal", "privileges"}]``."""

    def __init__(self, live):
        super().__init__()
        self.live = live

    def get_grants(self, securable_type, securable_name):
        return {"success": True, "grants": self.live.get((securable_type, securable_name), [])}


def test_grants_that_existed_before_ontos_are_never_revoked(policies, rm, db_session: Session):
    p = _active_policy(policies, db_session, {"permission": [{"target": "uc:main.sales.orders", "action": "read"}]})
    grants = LiveGrants({("catalog", "main"): [{"principal": "account users", "privileges": ["USE_CATALOG"]}],
                         ("schema", "main.sales"): [], ("table", "main.sales.orders"): []})
    rm.deliver(db_session, _approved_release(rm, db_session).id, ADMIN, Delivery([DeliveryMode.DIRECT], grants))
    flags = {x["privilege"]: x["preexisting"] for x in rm.ledger(db_session, "uc")}
    assert flags == {"USE_CATALOG": True, "USE_SCHEMA": False, "SELECT": False}
    policies.change_status(db_session, KIND_POLICY, p.id, "deprecated", AUTHOR)
    grants.calls.clear()
    rm.deliver(db_session, _approved_release(rm, db_session).id, ADMIN, Delivery([DeliveryMode.DIRECT], grants))
    assert {c[3][0] for c in grants.calls} == {"USE_SCHEMA", "SELECT"}  # USE CATALOG left alone


def test_revoke_expired_writes_nothing_when_delivery_is_unavailable_and_never_stacks(policies, rm, db_session: Session):
    from src.db_models.access_policies import AccessPolicyReleaseDb
    _active_policy(policies, db_session, {"permission": [{
        "target": "uc:main.sales", "action": "read", "assignee": "group:temps",
        "constraint": [{"leftOperand": "dateTime", "operator": "lteq", "rightOperand": "2099-01-01T00:00:00Z"}]}]})
    rm.deliver(db_session, _approved_release(rm, db_session).id, ADMIN, Delivery([DeliveryMode.DIRECT], FakeGrants()))
    later = datetime(2099, 1, 2, tzinfo=timezone.utc)
    before = db_session.query(AccessPolicyReleaseDb).count()
    with pytest.raises(AccessPolicyError):
        rm.revoke_expired(db_session, "uc", "system", Delivery([]), now=later)
    assert db_session.query(AccessPolicyReleaseDb).count() == before
    git = FakeGit()
    first = rm.revoke_expired(db_session, "uc", "system", Delivery([DeliveryMode.INDIRECT], git=git), now=later)
    second = rm.revoke_expired(db_session, "uc", "system", Delivery([DeliveryMode.INDIRECT], git=git), now=later)
    assert first.id == second.id and first.status == "delivered" and len(git.saved) == 1


def test_delivered_release_can_be_discarded(policies, rm, db_session: Session):
    _active_policy(policies, db_session, SALES)
    r = rm.deliver(db_session, _approved_release(rm, db_session).id, ADMIN, Delivery([DeliveryMode.INDIRECT], git=FakeGit()))
    assert rm.change_status(db_session, r.id, "discarded", ADMIN).status == "discarded"


def test_indirect_redelivery_ships_only_remaining_changes(policies, rm, db_session: Session):
    _active_policy(policies, db_session, SALES)
    r = rm.deliver(db_session, _approved_release(rm, db_session).id, ADMIN,
                   Delivery([DeliveryMode.DIRECT], FakeGrants(fail_on={"main.sales.orders"})))
    git = FakeGit()
    rm.deliver(db_session, r.id, ADMIN, Delivery([DeliveryMode.INDIRECT], git=git))
    spec = git.saved[0][2]["spec"]
    assert [g["securable_name"] for g in spec["changes"]["grant"]] == ["main.sales.orders"]
    assert spec["sql"] == ["GRANT SELECT ON TABLE `main`.`sales`.`orders` TO `analysts`;"]


def test_ledger_principal_filter_is_exact(policies, rm, db_session: Session):
    _active_policy(policies, db_session, {"permission": [
        {"target": "uc:main.s.t", "action": "read", "assignee": "group:data_eng"},
        {"target": "uc:main.s.t", "action": "read", "assignee": "group:dataXeng"}]})
    rm.deliver(db_session, _approved_release(rm, db_session).id, ADMIN, Delivery([DeliveryMode.DIRECT], FakeGrants()))
    assert {x["principal"] for x in rm.ledger(db_session, "uc", principal="DATA_ENG")} == {"data_eng"}
    assert rm.ledger(db_session, "uc", principal="%") == []


def test_timeline_logging_does_not_commit(policies, rm, db_session: Session, monkeypatch):
    _active_policy(policies, db_session, SALES)
    commits = []
    monkeypatch.setattr(db_session, "commit", lambda: commits.append(1))
    r = rm.create_release(db_session, "uc", AUTHOR)
    assert commits == []
    from src.db_models.comments import CommentDb
    assert db_session.query(CommentDb).filter(CommentDb.entity_id == r.id).count() == 1


# ------------------------------------------------------------ /review findings (2nd pass)

def test_applying_a_release_keeps_delivered_releases_confirmable(policies, rm, db_session: Session):
    _active_policy(policies, db_session, SALES)
    git = FakeGit()
    delivered = rm.deliver(db_session, _approved_release(rm, db_session).id, ADMIN, Delivery([DeliveryMode.INDIRECT], git=git))
    _active_policy(policies, db_session, {"permission": [{"target": "uc:other", "action": "read", "assignee": "group:x"}]}, name="Other")
    draft = rm.create_release(db_session, "uc", AUTHOR)
    rm.change_status(db_session, draft.id, "under_review", AUTHOR)
    rm.change_status(db_session, draft.id, "approved", APPROVER)
    rm.deliver(db_session, draft.id, ADMIN, Delivery([DeliveryMode.DIRECT], FakeGrants()))
    db_session.refresh(delivered)
    assert delivered.status == "delivered"
    assert rm.confirm_applied(db_session, delivered.id, ADMIN).status == "applied"


def test_revoke_expired_ships_newly_expired_grants_despite_pending_delivered_revocation(policies, rm, db_session: Session):
    _active_policy(policies, db_session, {"permission": [
        {"target": "uc:main.a", "action": "read", "assignee": "group:t",
         "constraint": [{"leftOperand": "dateTime", "operator": "lteq", "rightOperand": "2098-01-01T00:00:00Z"}]},
        {"target": "uc:other.b", "action": "read", "assignee": "group:t",
         "constraint": [{"leftOperand": "dateTime", "operator": "lteq", "rightOperand": "2099-01-01T00:00:00Z"}]}]})
    rm.deliver(db_session, _approved_release(rm, db_session).id, ADMIN, Delivery([DeliveryMode.DIRECT], FakeGrants()))
    git = FakeGit()
    first = rm.revoke_expired(db_session, "uc", "system", Delivery([DeliveryMode.INDIRECT], git=git),
                              now=datetime(2098, 1, 2, tzinfo=timezone.utc))
    second = rm.revoke_expired(db_session, "uc", "system", Delivery([DeliveryMode.INDIRECT], git=git),
                               now=datetime(2099, 1, 2, tzinfo=timezone.utc))
    assert first.id != second.id and first.status == second.status == "delivered"
    first_keys = {g["securable_name"] for g in first.changes["remove"] + first.changes["untrack"]}
    second_keys = {g["securable_name"] for g in second.changes["remove"] + second.changes["untrack"]}
    assert "other.b" in second_keys and not (first_keys & second_keys)


def test_manual_delivery_does_not_commit_the_request(policies, rm, db_session: Session, monkeypatch):
    from src.controller.notifications_manager import NotificationsManager
    _active_policy(policies, db_session, SALES)
    release = _approved_release(rm, db_session)
    commits = []
    monkeypatch.setattr(db_session, "commit", lambda: commits.append(1))
    svc = Delivery([DeliveryMode.MANUAL])
    svc.set_notifications_manager(NotificationsManager(settings_manager=None))
    r = rm.deliver(db_session, release.id, ADMIN, svc)
    assert r.status == "delivered" and commits == []
    assert r.delivery_results[-1]["results"][0]["success"] is True


# ------------------------------------------------------------ UC ABAC (P3d)

class AbacGrants(FakeGrants):
    def apply_abac_policy(self, spec, dry_run=False):
        self.calls.append(("abac_create", spec["name"], spec["on_securable_fullname"], ()))
        return {"success": True}

    def drop_abac_policy(self, ref, dry_run=False):
        self.calls.append(("abac_drop", ref["name"], ref["on_securable_fullname"], ()))
        return {"success": True}


def test_abac_policies_are_delivered_tracked_and_dropped(policies, rm, db_session: Session, monkeypatch):
    from src.common.config import get_settings
    st = get_settings()
    monkeypatch.setattr(st, "ACCESS_POLICIES_ABAC_ROW_FILTER_FUNCTION", "gov.abac.region_eq", raising=False)
    import src.controller.access_policy_releases_manager as arm
    monkeypatch.setattr(arm, "column_tag_checker", lambda settings: (lambda table, tag: True))
    p = _active_policy(policies, db_session, {"permission": [{
        "target": "uc:main.sales.orders", "action": "read", "assignee": "group:eu",
        "constraint": [{"leftOperand": "spatial", "operator": "eq", "rightOperand": "EU"}]}]})
    grants = AbacGrants()
    r = rm.deliver(db_session, _approved_release(rm, db_session).id, ADMIN, Delivery([DeliveryMode.DIRECT], grants))
    assert r.status == "applied" and grants.calls[0][0] == "abac_create"
    abac_rows = [x for x in rm.ledger(db_session, "uc") if x["securable_type"] == "abac_policy"]
    assert abac_rows
    assert "ABAC policies to create" in rm._summary(r)
    assert any(s.startswith("CREATE POLICY") for s in r.changes["sql"])
    policies.change_status(db_session, KIND_POLICY, p.id, "deprecated", AUTHOR)
    grants.calls.clear()
    rm.deliver(db_session, _approved_release(rm, db_session).id, ADMIN, Delivery([DeliveryMode.DIRECT], grants))
    assert grants.calls[-1][0] == "abac_drop" and rm.ledger(db_session, "uc") == []
