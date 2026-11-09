"""Approval steps render ${...} placeholders in their ``message``.

The default Publication / Certification Request Review approvals use
``message: "Please review the ... request for ${entity_type} '${entity_name}'."``.
Notification steps already substitute these; approval steps showed them
verbatim in the notification and the approval dialog.
"""
import json
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from src.common.workflow_executor import ApprovalStepHandler, StepContext
from src.db_models.notifications import NotificationDb


def _make_context() -> StepContext:
    return StepContext(
        entity={'name': 'Orders', 'status': 'active'},
        entity_type='data_product',
        entity_id='product-1',
        entity_name='Orders',
        user_email='requester@co.com',
        trigger_context=None,
        execution_id='exec-1',
        workflow_id='wf-1',
        workflow_name='Certification Request Review',
        step_results={},
    )


def _single_notification(db_session) -> NotificationDb:
    notifications = db_session.query(NotificationDb).all()
    assert len(notifications) == 1
    return notifications[0]


def test_approval_message_placeholders_are_rendered(db_session):
    handler = ApprovalStepHandler(db_session, {
        'approvers': 'steward@co.com',
        'message': "Please review the certification request for ${entity_type} '${entity_name}'.",
    })

    result = handler.execute(_make_context())

    assert result.blocking is True
    notification = _single_notification(db_session)
    expected = "Please review the certification request for data_product 'Orders'."
    assert f"Workflow message: {expected}" in notification.description
    assert '${' not in notification.description
    assert json.loads(notification.action_payload)['workflow_message'] == expected


def test_approval_without_message_has_no_workflow_message(db_session):
    ApprovalStepHandler(db_session, {'approvers': 'steward@co.com'}).execute(_make_context())

    notification = _single_notification(db_session)
    assert 'Workflow message' not in (notification.description or '')
    assert json.loads(notification.action_payload)['workflow_message'] is None
