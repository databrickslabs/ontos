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
`can_delete=True` on everything an admin can see. These tests pin the manager's
enforcement and override and the recipient check; the route is covered through
the API in `integration/test_notification_delete_authz_routes.py`.
"""

# Set test environment variables BEFORE any app imports
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from types import SimpleNamespace
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
    return SimpleNamespace(id=role_id, name=name, assigned_groups=groups, assigned_users=[])


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


def test_role_scoped_notification_needs_role_membership(
    manager, db_session: Session, normal_user
):
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


def test_broadcast_notification_is_accessible_to_everyone(
    manager, db_session: Session, normal_user
):
    notification_id = _make_notification(db_session, recipient=None)
    notification = manager.get_notification_by_id(db_session, notification_id)

    assert manager.can_user_access_notification(
        db=db_session, notification=notification, user_info=normal_user
    ) is True
