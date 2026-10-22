"""A review decided on the contract page also decides its waiting review workflows (#963).

Requesting a review starts the contract's on_request_review workflows, which
pause at an approval step. Approving or rejecting the contract on its page
changed the status but left those executions paused, with their approval
notifications open.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.db_models.notifications import NotificationDb
from src.db_models.process_workflows import (
    ProcessWorkflowDb, WorkflowExecutionDb, WorkflowStepDb,
)
from src.routes import data_contracts_routes
from src.routes.data_contracts_routes import _decide_waiting_review_workflows

CONTRACT = 'c-1'


def _execution(db, *, entity_id=CONTRACT, trigger='on_request_review', step_type='approval',
               status='paused'):
    workflow = ProcessWorkflowDb(
        id=str(uuid.uuid4()), name=f'wf-{uuid.uuid4().hex[:6]}',
        trigger_config=json.dumps({'type': trigger}),
    )
    db.add(workflow)
    db.flush()
    db.add(WorkflowStepDb(
        id=str(uuid.uuid4()), workflow_id=workflow.id, step_id='request-approval',
        step_type=step_type, config='{}', order=0,
    ))
    execution = WorkflowExecutionDb(
        id=str(uuid.uuid4()), workflow_id=workflow.id, status=status,
        current_step_id='request-approval',
        trigger_context=json.dumps({
            'entity_type': 'data_contract', 'entity_id': entity_id, 'trigger_type': trigger,
            'user_email': 'pat@example.com',
        }),
    )
    db.add(execution)
    db.add(NotificationDb(
        id=str(uuid.uuid4()), type='action_required', title='Approval Required',
        recipient='Data Steward', action_type='workflow_approval', read=False,
        action_payload=json.dumps({'execution_id': execution.id, 'step_id': 'request-approval'}),
    ))
    db.flush()
    return execution


def _approval_notification(db, execution):
    return next(
        n for n in db.query(NotificationDb).all()
        if json.loads(n.action_payload)['execution_id'] == execution.id
    )


@pytest.mark.parametrize('approved, decision', [(True, 'approved'), (False, 'rejected')])
def test_waiting_review_workflows_get_the_decision(db_session, approved, decision):
    execution = _execution(db_session)

    with patch('src.common.workflow_executor.WorkflowExecutor.resume_workflow') as resume:
        assert _decide_waiting_review_workflows(
            db_session, CONTRACT, approved, 'sue@example.com',
        ) == 1

    kwargs = resume.call_args.kwargs
    assert kwargs['execution_id'] == execution.id
    assert kwargs['step_result'] is approved
    assert kwargs['result_data']['decision'] == decision
    assert kwargs['result_data']['decided_on'] == 'contract_page'
    assert kwargs['user_email'] == 'sue@example.com'
    notification = _approval_notification(db_session, execution)
    assert notification.read is True
    assert json.loads(notification.action_payload)['decision'] == decision


def test_other_executions_are_left_alone(db_session):
    others = [
        _execution(db_session, entity_id='another-contract'),
        _execution(db_session, trigger='on_request_publish'),
        _execution(db_session, step_type='notification'),
        _execution(db_session, status='succeeded'),
    ]

    with patch('src.common.workflow_executor.WorkflowExecutor.resume_workflow') as resume:
        assert _decide_waiting_review_workflows(db_session, CONTRACT, True, 'sue@example.com') == 0

    resume.assert_not_called()
    assert all(_approval_notification(db_session, e).read is False for e in others)


def test_an_id_that_contains_the_contract_id_is_not_a_match(db_session):
    _execution(db_session, entity_id=CONTRACT + '0')

    with patch('src.common.workflow_executor.WorkflowExecutor.resume_workflow') as resume:
        assert _decide_waiting_review_workflows(db_session, CONTRACT, True, 'sue@example.com') == 0

    resume.assert_not_called()


def test_the_trigger_context_as_the_executor_stores_it_is_found(db_session):
    # The SQL filter matches quoted values in the stored text; the executor
    # writes it with ``model_dump_json`` (compact separators).
    from src.models.process_workflows import TriggerContext, TriggerType

    execution = _execution(db_session)
    execution.trigger_context = TriggerContext(
        entity_type='data_contract', entity_id=CONTRACT, entity_name='Orders',
        trigger_type=TriggerType.ON_REQUEST_REVIEW, user_email='pat@example.com',
        entity_data={'id': CONTRACT, 'status': 'proposed'},
    ).model_dump_json()
    db_session.flush()

    with patch('src.common.workflow_executor.WorkflowExecutor.resume_workflow') as resume:
        assert _decide_waiting_review_workflows(db_session, CONTRACT, True, 'sue@example.com') == 1

    assert resume.call_args.kwargs['execution_id'] == execution.id


def test_a_failing_resume_is_logged_and_the_others_still_run(db_session):
    _execution(db_session)
    second = _execution(db_session)
    calls = []

    def resume(**kwargs):
        calls.append(kwargs['execution_id'])
        if len(calls) == 1:
            raise RuntimeError('boom')

    with patch('src.common.workflow_executor.WorkflowExecutor.resume_workflow', side_effect=resume):
        assert _decide_waiting_review_workflows(db_session, CONTRACT, True, 'sue@example.com') == 1

    assert len(calls) == 2
    assert calls[1] == second.id


@pytest.mark.parametrize('route, approved, status', [
    ('approve_contract', True, 'approved'), ('reject_contract', False, 'draft'),
])
def test_the_contract_page_routes_pass_the_decision_on(route, approved, status):
    manager = MagicMock()
    manager.transition_status.return_value = SimpleNamespace(status=status)
    user = SimpleNamespace(email='sue@example.com', username='sue')
    db = MagicMock()

    with patch.object(data_contracts_routes.data_contract_repo, 'get',
                      return_value=SimpleNamespace(status='proposed')), \
            patch.object(data_contracts_routes, '_decide_waiting_review_workflows') as decide:
        result = asyncio.run(getattr(data_contracts_routes, route)(
            contract_id=CONTRACT, request=MagicMock(), db=db, audit_manager=MagicMock(),
            current_user=user, manager=manager, _=True,
        ))

    assert result == {'status': status}
    decide.assert_called_once_with(db, CONTRACT, approved, 'sue@example.com')
