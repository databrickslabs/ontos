"""``DELETE /api/notifications/{id}`` checks the notification, not only the permission (#675).

The route was guarded by ``notifications: Admin`` alone. A caller holding only that
permission, in no admin role, could delete a ``can_delete=False`` notification (one that
exists to force a response) and notifications addressed to other people or roles. Now:

- a non-admin gets 403 with a coded error for a non-deletable or someone else's notification
  and the row stays;
- an Ontos admin (a role flagged ``is_admin``) may delete either, and deleting a non-deletable
  one is audited as ``admin_override``.
"""
import json
import uuid

import pytest

from src.app import app
from src.common.authorization import get_user_details_from_sdk
from src.db_models.notifications import NotificationDb
from src.db_models.settings import AppRoleDb
from src.models.users import UserInfo

OPS_GROUP = "notification-ops"
OPS_EMAIL = "ops@example.com"
OTHER_EMAIL = "someone.else@example.com"


@pytest.fixture(autouse=True)
def _savepoint(db_session):
    """Open a SAVEPOINT first: a refused request rolls its session back, which must not undo
    the data of the test."""
    db_session.connection().begin_nested()


@pytest.fixture
def ops_role(db_session):
    """A role whose only permission is ``notifications: Admin`` (and which is not an admin role)."""
    role = AppRoleDb(
        id=str(uuid.uuid4()), name=f"Notification Ops {uuid.uuid4().hex[:8]}",
        description="notifications: Admin only",
        feature_permissions=json.dumps({"notifications": "Admin"}),
        assigned_groups=json.dumps([OPS_GROUP]), home_sections="[]",
        approval_privileges="{}", is_admin=False,
    )
    db_session.add(role)
    db_session.flush()
    return role


@pytest.fixture
def audit_entries(client, monkeypatch):
    """The ``log_action`` calls of the audit manager, in order."""
    entries = []
    monkeypatch.setattr(
        app.state.audit_manager, "log_action", lambda **kwargs: entries.append(kwargs)
    )
    return entries


@pytest.fixture
def as_user(client):
    def _switch(email, groups):
        async def _override():
            return UserInfo(username=email, email=email, user=email, ip="127.0.0.1", groups=groups)

        app.dependency_overrides[get_user_details_from_sdk] = _override
        return client

    return _switch


def _notification(db, *, recipient=None, recipient_role_id=None, can_delete=True):
    notification_id = str(uuid.uuid4())
    db.add(NotificationDb(
        id=notification_id, type="info", title="Approval Required", recipient=recipient,
        recipient_role_id=recipient_role_id, can_delete=can_delete, read=False,
    ))
    db.flush()
    return notification_id


def _exists(db, notification_id):
    db.expire_all()
    return db.query(NotificationDb).filter_by(id=notification_id).first() is not None


def test_non_admin_cannot_delete_a_non_deletable_notification(
    as_user, ops_role, db_session, audit_entries
):
    notification_id = _notification(db_session, recipient=OPS_EMAIL, can_delete=False)

    response = as_user(OPS_EMAIL, [OPS_GROUP]).delete(f"/api/notifications/{notification_id}")

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "notification_not_deletable"
    assert detail["params"] == {"notification_id": notification_id}
    assert _exists(db_session, notification_id)
    assert audit_entries[-1]["success"] is False


def test_non_admin_cannot_delete_someone_elses_notification(as_user, ops_role, db_session):
    notification_id = _notification(db_session, recipient=OTHER_EMAIL)

    response = as_user(OPS_EMAIL, [OPS_GROUP]).delete(f"/api/notifications/{notification_id}")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "notification_access_denied"
    assert _exists(db_session, notification_id)


def test_non_admin_cannot_delete_a_role_notification_of_another_role(
    as_user, ops_role, db_session
):
    steward = db_session.query(AppRoleDb).filter_by(name="Data Steward").first()
    notification_id = _notification(
        db_session, recipient_role_id=str(steward.id), can_delete=False
    )

    response = as_user(OPS_EMAIL, [OPS_GROUP]).delete(f"/api/notifications/{notification_id}")

    assert response.status_code == 403
    assert _exists(db_session, notification_id)


def test_non_admin_can_delete_their_own_deletable_notification(as_user, ops_role, db_session):
    notification_id = _notification(db_session, recipient=OPS_EMAIL)

    response = as_user(OPS_EMAIL, [OPS_GROUP]).delete(f"/api/notifications/{notification_id}")

    assert response.status_code == 204
    assert not _exists(db_session, notification_id)


def test_missing_notification_is_404(as_user, ops_role):
    response = as_user(OPS_EMAIL, [OPS_GROUP]).delete(f"/api/notifications/{uuid.uuid4()}")

    assert response.status_code == 404


def test_admin_can_delete_a_non_deletable_notification_and_it_is_audited(
    as_user, db_session, audit_entries
):
    notification_id = _notification(db_session, recipient=OTHER_EMAIL, can_delete=False)

    response = as_user("admin@example.com", ["test_admins"]).delete(
        f"/api/notifications/{notification_id}"
    )

    assert response.status_code == 204
    assert not _exists(db_session, notification_id)
    entry = audit_entries[-1]
    assert entry["action"] == "DELETE" and entry["success"] is True
    assert entry["details"]["params"] == {
        "notification_id": notification_id, "admin_override": True,
    }


def test_admin_deleting_a_deletable_notification_is_not_an_override(
    as_user, db_session, audit_entries
):
    notification_id = _notification(db_session, recipient=OTHER_EMAIL)

    response = as_user("admin@example.com", ["test_admins"]).delete(
        f"/api/notifications/{notification_id}"
    )

    assert response.status_code == 204
    assert audit_entries[-1]["details"]["params"]["admin_override"] is False


def test_custom_admin_role_sees_and_uses_the_delete_it_is_offered(
    as_user, db_session, audit_entries
):
    """A role flagged is_admin that is not named Admin: GET reports can_delete and DELETE agrees."""
    db_session.add(AppRoleDb(
        id=str(uuid.uuid4()), name=f"Custodian {uuid.uuid4().hex[:8]}", description="custom admin",
        feature_permissions=json.dumps({"notifications": "Admin"}),
        assigned_groups=json.dumps(["custodians"]), home_sections="[]",
        approval_privileges="{}", is_admin=True,
    ))
    notification_id = _notification(db_session, recipient=None, can_delete=False)
    client = as_user("custodian@example.com", ["custodians"])

    listed = {n["id"]: n for n in client.get("/api/notifications").json()}
    assert listed[notification_id]["can_delete"] is True

    assert client.delete(f"/api/notifications/{notification_id}").status_code == 204
    assert audit_entries[-1]["details"]["params"]["admin_override"] is True


def test_non_admin_is_not_offered_a_delete_on_a_non_deletable_notification(
    as_user, ops_role, db_session
):
    notification_id = _notification(db_session, recipient=None, can_delete=False)

    listed = {
        n["id"]: n for n in as_user(OPS_EMAIL, [OPS_GROUP]).get("/api/notifications").json()
    }

    assert listed[notification_id]["can_delete"] is False


def test_role_named_admin_without_the_flag_cannot_delete_someone_elses_notification(
    as_user, db_session
):
    """Only the Ontos admin check (is_admin) overrides; the role's name does not."""
    role = db_session.query(AppRoleDb).filter_by(name="Admin").one()
    role.is_admin = False
    role.assigned_groups = json.dumps(["named-admins"])
    role.feature_permissions = json.dumps({"notifications": "Admin"})
    db_session.flush()
    notification_id = _notification(db_session, recipient=OTHER_EMAIL)

    response = as_user("named@example.com", ["named-admins"]).delete(
        f"/api/notifications/{notification_id}"
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "notification_access_denied"
    assert _exists(db_session, notification_id)
