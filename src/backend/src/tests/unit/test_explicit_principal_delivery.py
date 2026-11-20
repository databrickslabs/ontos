"""Explicit principals keep their meaning on delivery (#1151 item 5).

The workflow resolver stores ``group:<name>`` / ``user:<x>`` for the explicit
forms. NotificationsManager must read them as that group / user, never as the
app role of the same name; a bare name (stored before the prefix) still goes
to the role.
"""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from src.controller.notifications_manager import NotificationsManager
from src.models.notifications import Notification, NotificationType
from src.models.users import UserInfo


def _role(name, groups):
    return SimpleNamespace(id=f'role-{name}', name=name, assigned_groups=groups)


@pytest.fixture
def manager():
    settings = Mock()
    settings.list_app_roles.return_value = [
        _role('Admin', ['admins']),
        _role('Data Steward', ['stewards']),
    ]
    return NotificationsManager(settings_manager=settings)


def _user(email, username=None, groups=()):
    return UserInfo(
        email=email, username=username or email.split('@')[0], user=email,
        ip='127.0.0.1', groups=list(groups),
    )


# A member of the group "Data Steward" with no role
GROUP_MEMBER = _user('gina@example.com', groups=['Data Steward'])
# A Data Steward role member outside that group
ROLE_MEMBER = _user('rolf@example.com', groups=['stewards'])
# The user named DataSteward
NAMED_USER = _user('ds@example.com', username='DataSteward')


def _note(recipient):
    return Notification(
        id=f'n-{recipient}', recipient=recipient, title='Approval Required',
        type=NotificationType.ACTION_REQUIRED, created_at=datetime(2026, 1, 1),
        read=False, can_delete=False,
    )


def _visible(manager, recipient, user):
    with patch.object(manager._repo, 'get_multi', return_value=[_note(recipient)]):
        return bool(manager.get_notifications(Mock(), user_info=user))


def _access(manager, recipient, user):
    return manager.can_user_access_notification(Mock(), _note(recipient), user)


@pytest.mark.parametrize('check', [_visible, _access], ids=['list', 'access'])
@pytest.mark.parametrize('recipient, user, expected', [
    ('group:Data Steward', GROUP_MEMBER, True),
    ('group:Data Steward', ROLE_MEMBER, False),
    ('user:DataSteward', NAMED_USER, True),
    ('user:datasteward', NAMED_USER, True),
    ('user:DataSteward', ROLE_MEMBER, False),
    ('user:DataSteward', GROUP_MEMBER, False),
    # Legacy: a bare role name still goes to the role
    ('Data Steward', ROLE_MEMBER, True),
    ('Data Steward', NAMED_USER, False),
])
def test_explicit_principals_are_not_role_names(manager, check, recipient, user, expected):
    assert check(manager, recipient, user) is expected


def test_admins_keep_access_to_explicit_principals(manager):
    admin = _user('ada@example.com', groups=['admins'])
    assert _access(manager, 'group:Data Steward', admin) is True
    assert _visible(manager, 'group:Data Steward', admin) is False


def _matches(manager, recipient, user):
    return manager.recipient_matcher(user)(recipient, None)


@pytest.mark.parametrize('recipient, user, expected', [
    # require_all asks the matcher which targets the caller fills (#1119)
    ('group:Data Steward', GROUP_MEMBER, True),
    ('group:Data Steward', ROLE_MEMBER, False),
    ('user:DataSteward', NAMED_USER, True),
    ('user:ds@example.com', NAMED_USER, True),
    ('user:DataSteward', ROLE_MEMBER, False),
    # Group names ignore case, as emails and usernames do
    ('group:data steward', GROUP_MEMBER, True),
    ('GROUP-X', _user('gus@example.com', groups=['group-x']), True),
])
def test_the_require_all_matcher_reads_explicit_principals(manager, recipient, user, expected):
    assert _matches(manager, recipient, user) is expected
