"""fail_flow_on_failure is honoured only on best-effort steps (#859 review B9, N7).

A failed approval, gate or script always fails the run, whatever its config says.
A failed notification or webhook with the flag off continues the run: it follows
its on_fail when set, else its on_pass, and the step is recorded as non-fatal. The
flag is read as a boolean, so the string "false" counts.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid

import pytest

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


def _step(step_id, step_type, config=None, on_pass=None, on_fail=None):
    return WorkflowStepCreate(
        step_id=step_id, step_type=step_type, config=config or {},
        on_pass=on_pass, on_fail=on_fail,
    )


def _create(db, steps):
    # Saved without validation, as an older designer or the YAML loader stored it
    return process_workflow_repo.create(db, ProcessWorkflowCreate(
        name=f'wf-{uuid.uuid4().hex[:6]}',
        trigger=WorkflowTrigger(type=TriggerType.MANUAL, entity_types=[EntityType.TABLE]),
        steps=steps,
    ))


def _run(db, workflow_id):
    workflow = WorkflowsManager(db).get_workflow(workflow_id)
    return WorkflowExecutor(db).execute_workflow(
        workflow=workflow,
        entity={'id': 't-1', 'name': 'orders'},
        entity_type='table',
        entity_id='t-1',
        entity_name='orders',
        user_email='pat@example.com',
        trigger_context=TriggerContext(
            entity_type='table', entity_id='t-1', entity_name='orders',
            trigger_type=TriggerType.MANUAL, user_email='pat@example.com',
        ),
    )


def _ran(execution):
    return [(s.step_key, s.status.value if hasattr(s.status, 'value') else s.status)
            for s in execution.step_executions]


def _step_row(execution, step_key):
    return next(s for s in execution.step_executions if s.step_key == step_key)


# A notification with no recipients fails (no send is attempted), and so does an
# approval with no approvers, without pausing the run.
FAILING_NOTIFY = {'recipients': '', 'template': 'request_submitted'}
FAILING_APPROVAL = {'approvers': ''}


def test_a_failed_approval_with_the_flag_off_still_fails_the_run(db_session):
    db_workflow = _create(db_session, [
        _step('approve', StepType.APPROVAL, {**FAILING_APPROVAL, 'fail_flow_on_failure': False}, on_pass='done'),
        _step('done', StepType.PASS),
    ])

    execution = _run(db_session, db_workflow.id)

    assert _ran(execution) == [('approve', 'failed')]
    assert execution.status.value == 'failed'
    assert 'non_fatal' not in (_step_row(execution, 'approve').result_data or {})


def test_a_failed_notification_with_the_flag_off_continues_as_non_fatal(db_session):
    db_workflow = _create(db_session, [
        _step('notify', StepType.NOTIFICATION, {**FAILING_NOTIFY, 'fail_flow_on_failure': False}, on_pass='done'),
        _step('done', StepType.PASS),
    ])

    execution = _run(db_session, db_workflow.id)

    assert _ran(execution) == [('notify', 'failed'), ('done', 'succeeded')]
    assert execution.status.value == 'succeeded'
    assert (_step_row(execution, 'notify').result_data or {}).get('non_fatal') is True


def test_a_failed_notification_without_the_flag_fails_the_run(db_session):
    db_workflow = _create(db_session, [
        _step('notify', StepType.NOTIFICATION, FAILING_NOTIFY, on_pass='done'),
        _step('done', StepType.PASS),
    ])

    execution = _run(db_session, db_workflow.id)

    assert _ran(execution) == [('notify', 'failed')]
    assert execution.status.value == 'failed'


def test_a_non_fatal_failure_follows_on_fail_when_defined(db_session):
    db_workflow = _create(db_session, [
        _step('notify', StepType.NOTIFICATION, {**FAILING_NOTIFY, 'fail_flow_on_failure': False},
              on_pass='done', on_fail='rescue'),
        _step('done', StepType.PASS),
        _step('rescue', StepType.FAIL, {'message': 'Notification could not be sent'}),
    ])

    execution = _run(db_session, db_workflow.id)

    assert _ran(execution) == [('notify', 'failed'), ('rescue', 'failed')]
    assert execution.status.value == 'failed'
    assert execution.error_message == 'Notification could not be sent'


def test_the_string_false_is_read_as_false(db_session):
    db_workflow = _create(db_session, [
        _step('notify', StepType.NOTIFICATION, {**FAILING_NOTIFY, 'fail_flow_on_failure': 'false'}, on_pass='done'),
        _step('done', StepType.PASS),
    ])

    execution = _run(db_session, db_workflow.id)

    assert _ran(execution) == [('notify', 'failed'), ('done', 'succeeded')]
    assert execution.status.value == 'succeeded'


def test_the_string_false_on_an_approval_still_fails_the_run(db_session):
    db_workflow = _create(db_session, [
        _step('approve', StepType.APPROVAL, {**FAILING_APPROVAL, 'fail_flow_on_failure': 'false'}, on_pass='done'),
        _step('done', StepType.PASS),
    ])

    execution = _run(db_session, db_workflow.id)

    assert execution.status.value == 'failed'
    assert _ran(execution) == [('approve', 'failed')]


def test_resumed_run_continues_past_a_non_fatal_notification(db_session):
    db_workflow = _create(db_session, [
        _step('approve', StepType.APPROVAL, {'approvers': 'reviewer@example.com'}, on_pass='notify'),
        _step('notify', StepType.NOTIFICATION, {**FAILING_NOTIFY, 'fail_flow_on_failure': False}, on_pass='done'),
        _step('done', StepType.PASS),
    ])
    paused = _run(db_session, db_workflow.id)
    assert paused.status.value == 'paused'

    resumed = WorkflowExecutor(db_session).resume_workflow(
        execution_id=paused.id, step_result=True,
        result_data={'decision': 'approved'}, user_email='reviewer@example.com',
    )

    assert _ran(resumed)[-2:] == [('notify', 'failed'), ('done', 'succeeded')]
    assert resumed.status.value == 'succeeded'
    assert (_step_row(resumed, 'notify').result_data or {}).get('non_fatal') is True


def test_resumed_run_follows_on_fail_of_a_non_fatal_notification(db_session):
    db_workflow = _create(db_session, [
        _step('approve', StepType.APPROVAL, {'approvers': 'reviewer@example.com'}, on_pass='notify'),
        _step('notify', StepType.NOTIFICATION, {**FAILING_NOTIFY, 'fail_flow_on_failure': False},
              on_pass='done', on_fail='stop'),
        _step('done', StepType.PASS),
        _step('stop', StepType.FAIL, {'message': 'Stopped after notice'}),
    ])
    paused = _run(db_session, db_workflow.id)

    resumed = WorkflowExecutor(db_session).resume_workflow(
        execution_id=paused.id, step_result=True,
        result_data={'decision': 'approved'}, user_email='reviewer@example.com',
    )

    assert _ran(resumed)[-2:] == [('notify', 'failed'), ('stop', 'failed')]
    assert resumed.status.value == 'failed'


def test_save_rejects_the_flag_on_a_step_that_must_fail_the_run(db_session):
    manager = WorkflowsManager(db_session)
    result = manager.validate_workflow(ProcessWorkflowCreate(
        name='wf-flag',
        trigger=WorkflowTrigger(type=TriggerType.MANUAL, entity_types=[EntityType.TABLE]),
        steps=[
            _step('approve', StepType.APPROVAL, {'approvers': 'a@example.com', 'fail_flow_on_failure': False}, on_pass='done'),
            _step('done', StepType.PASS),
        ],
    ))

    codes = [issue.code for issue in result.issues]
    assert 'fail_flow_on_failure_not_allowed' in codes
    assert result.valid is False
    issue = next(i for i in result.issues if i.code == 'fail_flow_on_failure_not_allowed')
    assert issue.params['step'] == 'approve'
    assert issue.params['step_type'] == 'approval'


@pytest.mark.parametrize('step_type,config', [
    (StepType.NOTIFICATION, {'recipients': 'a@example.com', 'template': 'request_submitted', 'fail_flow_on_failure': 'false'}),
    (StepType.WEBHOOK, {'fail_flow_on_failure': False}),
])
def test_save_accepts_the_flag_on_best_effort_steps(db_session, step_type, config):
    result = WorkflowsManager(db_session).validate_workflow(ProcessWorkflowCreate(
        name='wf-ok',
        trigger=WorkflowTrigger(type=TriggerType.MANUAL, entity_types=[EntityType.TABLE]),
        steps=[_step('notify', step_type, config)],
    ))

    assert 'fail_flow_on_failure_not_allowed' not in [i.code for i in result.issues]


def test_flag_is_rejected_on_every_non_best_effort_type(db_session):
    result = WorkflowsManager(db_session).validate_workflow(ProcessWorkflowCreate(
        name='wf-gate',
        trigger=WorkflowTrigger(type=TriggerType.MANUAL, entity_types=[EntityType.TABLE]),
        steps=[_step('check', StepType.VALIDATION, {'rule': 'x > 0', 'fail_flow_on_failure': False})],
    ))

    assert [i.code for i in result.issues if i.code == 'fail_flow_on_failure_not_allowed'] == [
        'fail_flow_on_failure_not_allowed',
    ]


def test_coerce_flag_reads_words_and_keeps_the_default_for_unreadable_values():
    from src.models.process_workflows import coerce_flag

    assert coerce_flag('false', True) is False
    assert coerce_flag(' FALSE ', True) is False
    assert coerce_flag('no', True) is False
    assert coerce_flag('true', False) is True
    assert coerce_flag(0, True) is False
    assert coerce_flag('maybe', True) is True
    assert coerce_flag(None, False) is False
