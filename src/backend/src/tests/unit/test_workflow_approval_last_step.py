"""A workflow whose last step is an approval finishes when it is decided.

On resume, the approval's branch (``on_pass`` / ``on_fail``) picks the next
step. When the approval has no next step for the decision, the loop that runs
the remaining steps never starts, and the execution stayed ``running`` (with a
``finished_at``), so it counted as neither succeeded nor failed and its
completion handlers saw ``succeeded=False`` even for an approval.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from unittest.mock import patch

from src.common.workflow_executor import WorkflowExecutor
from src.controller.workflows_manager import WorkflowsManager
from src.models.process_workflows import (
    EntityType,
    ProcessWorkflowCreate,
    StepType,
    TriggerContext,
    TriggerType,
    WorkflowStepCreate,
    WorkflowTrigger,
)
from src.repositories.process_workflows_repository import process_workflow_repo


def _workflow(db, steps):
    db_workflow = process_workflow_repo.create(db, ProcessWorkflowCreate(
        name=f'wf-{uuid.uuid4().hex[:6]}',
        trigger=WorkflowTrigger(type=TriggerType.MANUAL, entity_types=[EntityType.DATA_PRODUCT]),
        steps=steps,
    ))
    return WorkflowsManager(db).get_workflow(db_workflow.id)


def _approval(on_pass=None, on_fail=None, order=0):
    return WorkflowStepCreate(
        step_id='approve', step_type=StepType.APPROVAL,
        config={'approvers': 'reviewer@example.com'},
        on_pass=on_pass, on_fail=on_fail, order=order,
    )


def _paused(db, workflow):
    execution = WorkflowExecutor(db).execute_workflow(
        workflow=workflow,
        entity={'id': 'p-1', 'name': 'sales_prod'},
        entity_type='data_product',
        entity_id='p-1',
        entity_name='sales_prod',
        user_email='pat@example.com',
        trigger_context=TriggerContext(
            entity_type='data_product', entity_id='p-1', entity_name='sales_prod',
            trigger_type=TriggerType.MANUAL, user_email='pat@example.com',
        ),
    )
    assert execution.status.value == 'paused'
    return execution


def _decide(db, execution, approved, reason=None):
    result_data = {'decision': 'approved' if approved else 'rejected'}
    if reason:
        result_data['reason'] = reason
    return WorkflowExecutor(db).resume_workflow(
        execution_id=execution.id,
        step_result=approved,
        result_data=result_data,
        user_email='reviewer@example.com',
    )


def test_an_approved_last_approval_succeeds(db_session):
    workflow = _workflow(db_session, [_approval()])
    execution = _paused(db_session, workflow)

    resumed = _decide(db_session, execution, approved=True)

    assert resumed.status.value == 'succeeded'
    assert resumed.finished_at is not None
    assert resumed.error_message is None


def test_a_rejected_last_approval_fails_with_the_reason(db_session):
    workflow = _workflow(db_session, [_approval()])
    execution = _paused(db_session, workflow)

    resumed = _decide(db_session, execution, approved=False, reason='Not ready')

    assert resumed.status.value == 'failed'
    assert resumed.error_message == 'Not ready'


def test_a_rejection_without_an_on_fail_step_fails(db_session):
    """The approval has a next step only when approved."""
    workflow = _workflow(db_session, [
        _approval(on_pass='ok'),
        WorkflowStepCreate(step_id='ok', step_type=StepType.PASS, order=1),
    ])
    execution = _paused(db_session, workflow)

    resumed = _decide(db_session, execution, approved=False)

    assert resumed.status.value == 'failed'
    assert resumed.error_message == 'Request denied'


def test_a_rejection_without_a_reason_says_request_denied(db_session):
    """The approve routes always send ``reason``, as None when none was written."""
    from src.db_models.process_workflows import WorkflowStepExecutionDb

    workflow = _workflow(db_session, [_approval()])
    execution = _paused(db_session, workflow)

    resumed = WorkflowExecutor(db_session).resume_workflow(
        execution_id=execution.id,
        step_result=False,
        result_data={'decision': 'rejected', 'reason': None},
        user_email='reviewer@example.com',
    )

    assert resumed.status.value == 'failed'
    assert resumed.error_message == 'Request denied'
    step_errors = [
        row.error_message
        for row in db_session.query(WorkflowStepExecutionDb)
        .filter(WorkflowStepExecutionDb.execution_id == execution.id).all()
        if row.passed is False
    ]
    assert step_errors == ['Request denied']


def _approval_run(db, execution):
    import json

    from src.db_models.process_workflows import WorkflowStepExecutionDb

    row = (
        db.query(WorkflowStepExecutionDb)
        .filter(WorkflowStepExecutionDb.execution_id == execution.id)
        .filter(WorkflowStepExecutionDb.step_key == 'approve')
        .filter(WorkflowStepExecutionDb.passed.is_(False))
        .one()
    )
    return json.loads(row.result_data)


def test_a_rejection_without_a_reason_carries_a_code_for_the_ui(db_session):
    workflow = _workflow(db_session, [_approval()])
    execution = _paused(db_session, workflow)

    WorkflowExecutor(db_session).resume_workflow(
        execution_id=execution.id,
        step_result=False,
        result_data={'decision': 'rejected', 'reason': None},
        user_email='reviewer@example.com',
    )

    data = _approval_run(db_session, execution)
    assert (data['error_code'], data['error_params']) == ('approval_rejected', {})


def test_a_rejection_with_a_reason_shows_the_reason_without_a_code(db_session):
    workflow = _workflow(db_session, [_approval()])
    execution = _paused(db_session, workflow)

    _decide(db_session, execution, approved=False, reason='Not ready')

    assert 'error_code' not in _approval_run(db_session, execution)


def test_the_execution_routes_send_the_code_of_the_rejection(db_session):
    """The list and the detail carry the failed step's code for the execution's error."""
    import asyncio
    from unittest.mock import MagicMock

    from src.routes import workflows_routes

    workflow = _workflow(db_session, [_approval()])
    execution = _paused(db_session, workflow)
    WorkflowExecutor(db_session).resume_workflow(
        execution_id=execution.id,
        step_result=False,
        result_data={'decision': 'rejected', 'reason': None},
        user_email='reviewer@example.com',
    )
    db_session.expire_all()

    listed = asyncio.run(workflows_routes.list_executions(
        request=MagicMock(), db=db_session, workflow_id=workflow.id,
        status=None, limit=50, offset=0, _=True,
    )).executions
    assert [(e.error_message, e.error_code) for e in listed] == [
        ('Request denied', 'approval_rejected'),
    ]
    detail = asyncio.run(workflows_routes.get_execution(
        execution_id=execution.id, db=db_session, _=True,
    ))
    assert (detail['error_code'], detail['error_params']) == ('approval_rejected', {})


def test_an_execution_error_with_a_reason_has_no_code(db_session):
    import asyncio
    from unittest.mock import MagicMock

    from src.routes import workflows_routes

    workflow = _workflow(db_session, [_approval()])
    execution = _paused(db_session, workflow)
    _decide(db_session, execution, approved=False, reason='Not ready')
    db_session.expire_all()

    listed = asyncio.run(workflows_routes.list_executions(
        request=MagicMock(), db=db_session, workflow_id=workflow.id,
        status=None, limit=50, offset=0, _=True,
    )).executions
    assert [(e.error_message, e.error_code) for e in listed] == [('Not ready', None)]


def test_an_approval_followed_by_a_step_still_runs_it(db_session):
    workflow = _workflow(db_session, [
        _approval(on_pass='ok'),
        WorkflowStepCreate(step_id='ok', step_type=StepType.PASS, order=1),
    ])
    execution = _paused(db_session, workflow)

    resumed = _decide(db_session, execution, approved=True)

    assert resumed.status.value == 'succeeded'
    assert resumed.success_count == 2


def test_completion_handlers_see_the_outcome(db_session):
    workflow = _workflow(db_session, [_approval()])
    execution = _paused(db_session, workflow)

    with patch.object(WorkflowExecutor, '_handle_workflow_completion') as completion:
        _decide(db_session, execution, approved=True)

    assert completion.call_args.kwargs['succeeded'] is True
    assert completion.call_args.kwargs['approved'] is True
