"""Strict notification access check (#1117, #1119).

The check that decides who may read an entity under review or decide its
approval. Kept out of test_notifications_manager.py, which is quarantined in
conftest.py.
"""
import uuid
from datetime import datetime
from unittest.mock import Mock

import pytest

from src.controller.notifications_manager import NotificationsManager
from src.models.notifications import Notification, NotificationType
from src.models.users import UserInfo


class TestStrictAccessCheck:
    """``strict``: a notification addressed to a role it can't resolve grants
    nothing (#1117). The default check, used for the bell, is unchanged."""

    ROLE = Mock(id='role-stewards', assigned_groups=['stewards'], assigned_users=[])
    ROLE.name = 'Data Steward'

    def _manager(self, roles=None):
        settings = Mock()
        if roles is None:
            settings.list_app_roles.side_effect = RuntimeError('roles unavailable')
        else:
            settings.list_app_roles.return_value = list(roles)
        return NotificationsManager(settings_manager=settings)

    def _notification(self, recipient=None, role_id=None):
        return Notification(
            id='n-1', recipient=recipient, recipient_role_id=role_id, title='Approval',
            type=NotificationType.ACTION_REQUIRED, created_at=datetime(2026, 1, 1),
        )

    def _user(self, groups=()):
        return UserInfo(
            username='u@example.com', email='u@example.com', user='u', ip='127.0.0.1',
            groups=list(groups),
        )

    @pytest.mark.parametrize('roles', [[], None], ids=['unknown-role', 'roles-unreadable'])
    def test_an_unresolvable_role_grants_nothing_when_strict(self, roles):
        manager = self._manager(roles)
        notification = self._notification(role_id='role-stewards')

        assert manager.can_user_access_notification(
            None, notification, self._user(), strict=True,
        ) is False
        # The bell keeps treating it as visible to everyone
        assert manager.can_user_access_notification(None, notification, self._user()) is True

    def test_a_role_member_still_passes_when_strict(self):
        manager = self._manager([self.ROLE])
        notification = self._notification(role_id='role-stewards')

        assert manager.can_user_access_notification(
            None, notification, self._user(['stewards']), strict=True,
        ) is True
        assert manager.can_user_access_notification(
            None, notification, self._user(['others']), strict=True,
        ) is False

    def test_a_role_stored_by_uuid_resolves_when_strict(self):
        """Roles come back with UUID ids; the notification stores the text form."""
        role = Mock(id=uuid.UUID('1605ecf8-b56f-40ac-80b1-d3a71a4e4ffb'),
                    assigned_groups=['stewards'], assigned_users=[])
        role.name = 'Data Steward'
        manager = self._manager([role])
        notification = self._notification(role_id=str(role.id))

        assert manager.can_user_access_notification(
            None, notification, self._user(['stewards']), strict=True,
        ) is True
        assert manager.can_user_access_notification(
            None, notification, self._user(['others']), strict=True,
        ) is False

    def test_a_broadcast_grants_nothing_when_strict(self):
        manager = self._manager([self.ROLE])

        assert manager.can_user_access_notification(
            None, self._notification(), self._user(), strict=True,
        ) is False

    def test_unreadable_roles_deny_even_a_named_recipient_when_strict(self):
        manager = self._manager(roles=None)
        notification = self._notification(recipient='u@example.com')

        assert manager.can_user_access_notification(
            None, notification, self._user(), strict=True,
        ) is False
        assert manager.can_user_access_notification(None, notification, self._user()) is True

    def test_a_business_role_notification_admits_only_its_owner_when_strict(self):
        """Business-role approvals name the owner and store the business role's
        id, which is not an app role."""
        admin = Mock(id='role-admin', assigned_groups=['admins'], assigned_users=[])
        admin.name = 'Admin'
        manager = self._manager([self.ROLE, admin])
        notification = self._notification(recipient='U@example.com', role_id='business-role-1')

        assert manager.can_user_access_notification(
            None, notification, self._user(), strict=True,
        ) is True
        other = UserInfo(
            username='o@example.com', email='o@example.com', user='o', ip='127.0.0.1',
            groups=['stewards', 'admins'],
        )
        assert manager.can_user_access_notification(
            None, notification, other, strict=True,
        ) is False

    def test_a_deleted_role_admits_nobody_when_strict(self):
        """An app-role notification names the role; once the role is deleted, a
        role created later with the same name doesn't inherit it."""
        manager = self._manager([self.ROLE])
        notification = self._notification(recipient='Data Steward', role_id='role-deleted')

        assert manager.can_user_access_notification(
            None, notification, self._user(['stewards']), strict=True,
        ) is False

    def test_a_role_stored_by_uuid_addresses_its_members_in_the_bell(self):
        """The default check resolves the text form of a UUID role id too, so
        the notification isn't a broadcast."""
        role = Mock(id=uuid.UUID('1605ecf8-b56f-40ac-80b1-d3a71a4e4ffb'),
                    assigned_groups=['stewards'], assigned_users=[])
        role.name = 'Data Steward'
        manager = self._manager([role])
        notification = self._notification(role_id=str(role.id))

        check = manager.can_user_access_notification
        assert check(None, notification, self._user(['stewards'])) is True
        assert check(None, notification, self._user(['others'])) is False
