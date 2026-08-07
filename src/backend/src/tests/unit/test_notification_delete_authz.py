"""Unit tests for notification delete authorization (#675).

Two checks were missing from `DELETE /api/notifications/{id}`, both of which
already existed in the codebase and were simply not called here:

1. **`can_delete` was never enforced server-side.** Approval requests, access
   grants, contract deploy requests and role access requests are created with
   `can_delete=False` to mean "you must respond to this". The flag was
   persisted correctly but only the frontend honoured it, so a direct API call
   dismissed the notification anyway.

2. **No recipient check.** The endpoint was guarded only by
   `PermissionChecker('notifications', ADMIN)`, so any principal holding that
   feature permission could delete another user's notification — including one
   scoped to a role they are not in. Mark-as-read, the weaker operation,
   already called `can_user_access_notification()`.

Admins may override `can_delete`, matching `get_notifications`, which reports
`can_delete=True` on everything an admin can see. These tests pin both the
enforcement and the override.
"""

# Set test environment variables BEFORE any app imports
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session
from src.controller.notifications_manager import (
    NotificationNotDeletableError,
    NotificationNotFoundError,
    NotificationsManager,
)
from src.db_models.notifications import NotificationDb
from src.models.users import UserInfo

ADMIN_GROUP = "ontos_admins"
USER_GROUP = "data_consumers"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _role(role_id: str, name: str, groups):
    role = Mock()
    role.id = role_id
    role.name = name
    role.assigned_groups = groups
    return role


@pytest.fixture
def settings_manager():
    """Settings manager exposing an Admin role bound to ADMIN_GROUP."""
    mgr = Mock()
    mgr.list_app_roles.return_value = [
        _role("role-admin", "Admin", [ADMIN_GROUP]),
        _role("role-consumer", "Data Consumer", [USER_GROUP]),
    ]
    return mgr


@pytest.fixture
def manager(settings_manager) -> NotificationsManager:
    return NotificationsManager(settings_manager=settings_manager)


@pytest.fixture
def admin_user() -> UserInfo:
    return UserInfo(
        username="admin", email="admin@example.com", user="admin",
        ip="127.0.0.1", groups=[ADMIN_GROUP],
    )


@pytest.fixture
def normal_user() -> UserInfo:
    return UserInfo(
        username="alice", email="alice@example.com", user="alice",
        ip="127.0.0.1", groups=[USER_GROUP],
    )


def _make_notification(db: Session, *, recipient=None, can_delete=True, role_id=None) -> str:
    notification_id = str(uuid.uuid4())
    db.add(NotificationDb(
        id=notification_id,
        type="info",
        title="Approval required",
        recipient=recipient,
        recipient_role_id=role_id,
        can_delete=can_delete,
        read=False,
    ))
    db.commit()
    return notification_id


# ---------------------------------------------------------------------------
# can_delete enforcement
# ---------------------------------------------------------------------------


def test_deletable_notification_is_deleted(manager, db_session: Session):
    notification_id = _make_notification(db_session, recipient="alice@example.com")

    assert manager.delete_notification(db_session, notification_id) is True
    assert db_session.query(NotificationDb).filter_by(id=notification_id).first() is None


def test_non_deletable_notification_is_refused(manager, db_session: Session):
    """The core of #675: this used to go straight to _repo.remove()."""
    notification_id = _make_notification(
        db_session, recipient="alice@example.com", can_delete=False
    )

    with pytest.raises(NotificationNotDeletableError):
        manager.delete_notification(db_session, notification_id)

    assert db_session.query(NotificationDb).filter_by(id=notification_id).first() is not None


def test_admin_may_override_can_delete(manager, db_session: Session):
    """Mirrors get_notifications, which reports can_delete=True to admins.

    Without the override an admin's UI offers a delete button that always
    fails, and notifications orphaned by a dead workflow can never be cleaned
    up.
    """
    notification_id = _make_notification(
        db_session, recipient="alice@example.com", can_delete=False
    )

    assert manager.delete_notification(db_session, notification_id, is_admin=True) is True
    assert db_session.query(NotificationDb).filter_by(id=notification_id).first() is None


def test_missing_notification_raises_not_found(manager, db_session: Session):
    with pytest.raises(NotificationNotFoundError):
        manager.delete_notification(db_session, str(uuid.uuid4()))


def test_delete_defaults_to_non_admin(manager, db_session: Session):
    """`is_admin` must default to False so any caller that forgets to pass it
    gets the safe behaviour."""
    notification_id = _make_notification(db_session, can_delete=False)

    with pytest.raises(NotificationNotDeletableError):
        manager.delete_notification(db=db_session, notification_id=notification_id)


# ---------------------------------------------------------------------------
# is_app_admin
# ---------------------------------------------------------------------------


def test_is_app_admin_true_for_admin_group(manager, admin_user):
    assert manager.is_app_admin(admin_user) is True


def test_is_app_admin_false_for_normal_user(manager, normal_user):
    assert manager.is_app_admin(normal_user) is False


def test_is_app_admin_false_without_user(manager):
    assert manager.is_app_admin(None) is False


def test_is_app_admin_false_when_admin_role_has_no_groups(admin_user):
    """A role with no assigned groups must not silently promote everyone."""
    settings_manager = Mock()
    settings_manager.list_app_roles.return_value = [_role("role-admin", "Admin", [])]
    manager = NotificationsManager(settings_manager=settings_manager)

    assert manager.is_app_admin(admin_user) is False


def test_is_app_admin_false_when_role_lookup_fails(admin_user):
    """Role-lookup failure must fail closed, not grant admin."""
    settings_manager = Mock()
    settings_manager.list_app_roles.side_effect = RuntimeError("settings unavailable")
    manager = NotificationsManager(settings_manager=settings_manager)

    assert manager.is_app_admin(admin_user) is False


# ---------------------------------------------------------------------------
# Recipient access — the check the delete endpoint now calls
# ---------------------------------------------------------------------------


def test_other_users_notification_is_not_accessible(manager, db_session: Session, normal_user):
    """A notification addressed to someone else is off-limits to a non-admin."""
    notification_id = _make_notification(db_session, recipient="bob@example.com")
    notification = manager.get_notification_by_id(db_session, notification_id)

    assert manager.can_user_access_notification(
        db=db_session, notification=notification, user_info=normal_user
    ) is False


def test_own_notification_is_accessible(manager, db_session: Session, normal_user):
    notification_id = _make_notification(db_session, recipient="alice@example.com")
    notification = manager.get_notification_by_id(db_session, notification_id)

    assert manager.can_user_access_notification(
        db=db_session, notification=notification, user_info=normal_user
    ) is True


def test_role_scoped_notification_needs_role_membership(manager, db_session: Session, normal_user, admin_user):
    """Role-scoped notifications reach members of that role, not outsiders."""
    notification_id = _make_notification(db_session, role_id="role-consumer")
    notification = manager.get_notification_by_id(db_session, notification_id)

    assert manager.can_user_access_notification(
        db=db_session, notification=notification, user_info=normal_user
    ) is True

    outsider = UserInfo(
        username="carol", email="carol@example.com", user="carol",
        ip="127.0.0.1", groups=["unrelated_group"],
    )
    assert manager.can_user_access_notification(
        db=db_session, notification=notification, user_info=outsider
    ) is False


def test_broadcast_notification_is_accessible_to_everyone(manager, db_session: Session, normal_user):
    notification_id = _make_notification(db_session, recipient=None)
    notification = manager.get_notification_by_id(db_session, notification_id)

    assert manager.can_user_access_notification(
        db=db_session, notification=notification, user_info=normal_user
    ) is True


# ---------------------------------------------------------------------------
# Route wiring — DELETE /api/notifications/{id}
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_manager_client(client, db_session: Session):
    """TestClient whose notifications manager is a stub we can steer.

    Lets us exercise the endpoint's mapping from manager outcome to HTTP
    status without standing up a full role/permission fixture.
    """
    from src.app import app
    from src.common.manager_dependencies import get_audit_manager, get_notifications_manager

    stub = Mock()

    app.dependency_overrides[get_notifications_manager] = lambda: stub
    # Startup tasks are skipped in tests, so app.state has no audit manager and
    # the real dependency 503s before the route body runs.
    app.dependency_overrides[get_audit_manager] = lambda: Mock()
    yield client, stub
    app.dependency_overrides.pop(get_notifications_manager, None)
    app.dependency_overrides.pop(get_audit_manager, None)


def test_delete_route_403_for_other_users_notification(stub_manager_client, db_session: Session):
    client, stub = stub_manager_client
    notification_id = _make_notification(db_session, recipient="bob@example.com")

    stub.get_notification_by_id.return_value = Mock(can_delete=True)
    stub.can_user_access_notification.return_value = False

    response = client.delete(f"/api/notifications/{notification_id}")

    assert response.status_code == 403
    assert response.json()["detail"] == "Cannot delete other user's notifications"
    stub.delete_notification.assert_not_called()


def test_delete_route_403_when_not_deletable(stub_manager_client, db_session: Session):
    client, stub = stub_manager_client
    notification_id = _make_notification(db_session, can_delete=False)

    stub.get_notification_by_id.return_value = Mock(can_delete=False)
    stub.can_user_access_notification.return_value = True
    stub.is_app_admin.return_value = False
    stub.delete_notification.side_effect = NotificationNotDeletableError("nope")

    response = client.delete(f"/api/notifications/{notification_id}")

    assert response.status_code == 403
    assert "requires a response" in response.json()["detail"]


def test_delete_route_404_for_missing_notification(stub_manager_client):
    client, stub = stub_manager_client
    stub.get_notification_by_id.return_value = None

    response = client.delete(f"/api/notifications/{uuid.uuid4()}")

    assert response.status_code == 404
    stub.delete_notification.assert_not_called()


def test_delete_route_204_on_success(stub_manager_client, db_session: Session):
    client, stub = stub_manager_client
    notification_id = _make_notification(db_session, recipient="alice@example.com")

    stub.get_notification_by_id.return_value = Mock(can_delete=True)
    stub.can_user_access_notification.return_value = True
    stub.is_app_admin.return_value = False
    stub.delete_notification.return_value = True

    response = client.delete(f"/api/notifications/{notification_id}")

    assert response.status_code == 204
    assert stub.delete_notification.call_args.kwargs["is_admin"] is False
