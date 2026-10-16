"""The requester can't decide an owner approval of their own request.

Owner approvals (DomainOwner / ContractApprover) leave out the requester, and
fall back to the Data Stewards and admins when no other owner exists. The
requester may hold one of those roles, so handle-approval refuses their own
decision there.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from src.db_models.notifications import NotificationDb
from src.db_models.process_workflows import (
    ProcessWorkflowDb, WorkflowExecutionDb, WorkflowStepDb,
)
from src.models.users import UserInfo
from src.routes import workflows_routes


def _user(email):
    return UserInfo(email=email, username=email, user=email, ip='127.0.0.1', groups=['admins'])


def _paused_execution(db, approvers, requester='rita@example.com'):
    workflow = ProcessWorkflowDb(
        id=str(uuid.uuid4()), name=f'wf-{uuid.uuid4().hex[:6]}',
        trigger_config=json.dumps({'type': 'on_request_review'}),
    )
    db.add(workflow)
    db.flush()
    db.add(WorkflowStepDb(
        id=str(uuid.uuid4()), workflow_id=workflow.id, step_id='approve', step_type='approval',
        config=json.dumps({'approvers': approvers}), order=0,
    ))
    execution = WorkflowExecutionDb(
        id=str(uuid.uuid4()), workflow_id=workflow.id, status='paused',
        current_step_id='approve',
        trigger_context=json.dumps({'user_email': requester, 'entity_type': 'data_product'}),
    )
    db.add(execution)
    db.add(NotificationDb(
        id=str(uuid.uuid4()), type='action_required', title='Approval Required',
        recipient='Data Steward', action_type='workflow_approval',
        action_payload=json.dumps({'execution_id': execution.id, 'step_id': 'approve'}),
    ))
    db.flush()
    return execution


def _authorize(db, execution, email):
    notifications = MagicMock()
    notifications.can_user_access_notification.return_value = True
    return workflows_routes._assert_caller_authorized_for_execution(
        db=db, notifications_manager=notifications, execution_id=execution.id,
        user_info=_user(email),
    )


@pytest.mark.parametrize('approvers', ['DomainOwner', 'domain_owners', 'ContractApprover'])
def test_the_requester_cannot_decide_an_owner_approval(db_session, approvers):
    execution = _paused_execution(db_session, approvers)

    with pytest.raises(HTTPException) as e:
        _authorize(db_session, execution, 'Rita@example.com')

    assert e.value.status_code == 403
    assert e.value.detail['code'] == 'own_owner_approval'
    assert 'your own request' in e.value.detail['message']


def test_another_steward_or_admin_can_decide_it(db_session):
    execution = _paused_execution(db_session, 'DomainOwner')

    assert _authorize(db_session, execution, 'sam@example.com')


def test_other_approvals_keep_their_rules(db_session):
    # e.g. a Data Steward approval: no owner semantics, unchanged by this guard
    execution = _paused_execution(db_session, 'DataSteward')

    assert _authorize(db_session, execution, 'rita@example.com')
