"""A decided approval closes the step's notifications the approvers already opened.

Opening a notification in the bell marks it read. When another member of the
target group or role then decides, that notification must still be marked
handled, or the home page keeps offering a decision that is no longer pending.
"""
import json
import uuid

from src.db_models.notifications import NotificationDb
from src.routes.workflows_routes import (
    _mark_decided_approver_notifications,
    _mark_step_notifications_handled,
)


def _approval(db, execution_id, *, read, recipient=None, role_id=None, extra=None):
    payload = {'execution_id': execution_id, 'step_id': 'approve', **(extra or {})}
    notification = NotificationDb(
        id=str(uuid.uuid4()), type='action_required', title='Approval requested',
        recipient=recipient, recipient_role_id=role_id, read=read,
        action_type='workflow_approval', action_payload=json.dumps(payload),
    )
    db.add(notification)
    db.flush()
    return notification


def _payload(db, notification):
    db.flush()
    db.refresh(notification)
    return json.loads(notification.action_payload)


def test_a_read_but_pending_notification_is_handled_when_another_member_decides(db_session):
    execution_id = f'exec-{uuid.uuid4().hex[:8]}'
    opened = _approval(db_session, execution_id, read=True, role_id='role-stewards')

    _mark_step_notifications_handled(
        db_session, execution_id, 'approve', True, 'other@example.com',
    )

    payload = _payload(db_session, opened)
    assert payload['handled'] is True
    assert payload['decision'] == 'approved'
    assert payload['handled_by'] == 'other@example.com'
    assert opened.read is True


def test_an_already_handled_notification_keeps_its_decision(db_session):
    execution_id = f'exec-{uuid.uuid4().hex[:8]}'
    earlier = {
        'handled': True, 'decision': 'approved', 'handled_by': 'ana@example.com',
        'handled_at': '2026-11-06T10:00:00',
    }
    decided = _approval(
        db_session, execution_id, read=True, recipient='ana@example.com', extra=earlier,
    )

    # e.g. an admin cancels the step after Ana's decision
    _mark_step_notifications_handled(
        db_session, execution_id, 'approve', False, 'admin@example.com', decision='cancelled',
    )

    payload = _payload(db_session, decided)
    assert {k: payload[k] for k in earlier} == earlier


def test_require_all_handles_the_read_notification_of_the_target_that_decided(db_session):
    execution_id = f'exec-{uuid.uuid4().hex[:8]}'
    group = _approval(db_session, execution_id, read=True, recipient='data-stewards')
    other = _approval(db_session, execution_id, read=True, recipient='ben@example.com')

    _mark_decided_approver_notifications(db_session, execution_id, 'approve', [{
        'target': 'data-stewards', 'role_id': None, 'decided_by': 'cleo@example.com',
        'decision': 'approved', 'at': '2026-11-06T11:00:00',
    }])

    assert _payload(db_session, group)['handled_by'] == 'cleo@example.com'
    # Ben's target is still pending: his opened notification stays open
    assert 'handled' not in _payload(db_session, other)
