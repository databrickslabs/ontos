"""Groups picked as workflow recipients / approvers reach their members (#1064)."""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from src.common.workflow_executor import _resolve_role_to_users
from src.controller.notifications_manager import NotificationsManager
from src.db_models.notifications import NotificationDb
from src.models.notifications import Notification
from src.models.users import UserInfo
from src.routes import workflows_routes

STEWARD_ROLE = SimpleNamespace(id=str(uuid.uuid4()), name='Data Steward',
                               assigned_groups=['stewards'])


def _user(email, groups):
    return UserInfo(email=email, username=email, user=email, ip='127.0.0.1', groups=groups)


def _manager(roles=()):
    settings = MagicMock()
    settings.list_app_roles.return_value = list(roles)
    return NotificationsManager(settings_manager=settings)


def _approval_notification(db, recipient, role_id=None, execution_id='exec-1', step_id='approve'):
    row = NotificationDb(
        id=str(uuid.uuid4()), type='action_required', title='Approval required',
        recipient=recipient, recipient_role_id=role_id, action_type='workflow_approval',
        action_payload=json.dumps({'execution_id': execution_id, 'step_id': step_id}),
    )
    db.add(row)
    db.flush()
    return row


def test_a_group_approver_resolves_to_the_group_name():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    db.query.return_value.all.return_value = []
    context = SimpleNamespace(user_email='r@example.com', entity={}, entity_type='data_contract',
                              entity_id='c-1', entity_name='C')

    # What the Workflow Designer stores for a role plus a group picked as a principal
    assert _resolve_role_to_users(db, 'requester,data-producers', context) == [
        ('r@example.com', None), ('data-producers', None),
    ]


def test_group_members_see_a_notification_addressed_to_their_group(db_session):
    _approval_notification(db_session, 'data-producers')
    manager = _manager()

    member = manager.get_notifications(db_session, _user('ann@example.com', ['data-producers']))
    other = manager.get_notifications(db_session, _user('bob@example.com', ['analysts']))

    assert [n.recipient for n in member] == ['data-producers']
    assert other == []


def test_the_access_check_accepts_group_members_only(db_session):
    row = _approval_notification(db_session, 'data-producers')
    notification = Notification.model_validate(row)
    manager = _manager()

    assert manager.can_user_access_notification(
        db_session, notification, _user('ann@example.com', ['data-producers'])) is True
    assert manager.can_user_access_notification(
        db_session, notification, _user('bob@example.com', ['analysts'])) is False


def test_a_role_notification_is_not_opened_by_a_group_named_like_the_role(db_session):
    row = _approval_notification(db_session, 'Data Steward', role_id=STEWARD_ROLE.id)
    manager = _manager([STEWARD_ROLE])
    # In a group called like the role, but not in the role's assigned group
    user = _user('eve@example.com', ['Data Steward'])

    assert manager.get_notifications(db_session, user) == []
    assert manager.can_user_access_notification(
        db_session, Notification.model_validate(row), user) is False


@pytest.mark.parametrize('groups, allowed', [(['data-producers'], True), (['analysts'], False)])
def test_group_members_may_approve_the_pending_step(db_session, groups, allowed):
    _approval_notification(db_session, 'data-producers')
    user = _user('ann@example.com', groups)

    with patch.object(workflows_routes, '_pending_step_id', return_value='approve'):
        if allowed:
            assert workflows_routes._assert_caller_authorized_for_execution(
                db=db_session, notifications_manager=_manager(), execution_id='exec-1',
                user_info=user,
            )
        else:
            with pytest.raises(HTTPException) as err:
                workflows_routes._assert_caller_authorized_for_execution(
                    db=db_session, notifications_manager=_manager(), execution_id='exec-1',
                    user_info=user,
                )
            assert err.value.status_code == 403


def test_a_group_approver_of_an_earlier_step_may_not_approve(db_session):
    _approval_notification(db_session, 'data-producers', step_id='first-approval')

    with patch.object(workflows_routes, '_pending_step_id', return_value='second-approval'):
        with pytest.raises(HTTPException):
            workflows_routes._assert_caller_authorized_for_execution(
                db=db_session, notifications_manager=_manager(), execution_id='exec-1',
                user_info=_user('ann@example.com', ['data-producers']),
            )
