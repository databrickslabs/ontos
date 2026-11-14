"""Steps after an approval see the results of the steps before it (#1437).

A resumed run built ``step_results`` with only the approval's result, so a later
step's ``${step_results.<earlier>.<field>}`` resolved to nothing, and a
conditional's ``branch`` from before the pause was lost.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid

from src.common.workflow_executor import WorkflowExecutor, substitute_template
from src.controller.workflows_manager import WorkflowsManager
from src.db_models.process_workflows import WorkflowStepExecutionDb
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

RULE = 'MATCH (obj:Object) ASSERT 1 = 1'
FAILING_RULE = 'MATCH (obj:Object) ASSERT 1 = 2'


def _step(step_id, step_type, config=None, on_pass=None, on_fail=None):
    return WorkflowStepCreate(
        step_id=step_id, step_type=step_type, config=config or {},
        on_pass=on_pass, on_fail=on_fail,
    )


def _approval(step_id, on_pass):
    return _step(step_id, StepType.APPROVAL, {'approvers': 'reviewer@example.com'}, on_pass=on_pass)


def _create(db, steps):
    return process_workflow_repo.create(db, ProcessWorkflowCreate(
        name=f'wf-{uuid.uuid4().hex[:6]}',
        trigger=WorkflowTrigger(type=TriggerType.MANUAL, entity_types=[EntityType.TABLE]),
        steps=steps,
    ))


class _Spy:
    """Records the step_results each step sees, keyed by the step's id."""

    def __init__(self, executor):
        self.seen = {}
        original = executor._execute_step

        def spy(step, context):
            self.seen[step.step_id] = {k: dict(v) if isinstance(v, dict) else v
                                       for k, v in context.step_results.items()}
            self.context = context
            return original(step, context)

        executor._execute_step = spy


def _run(db, workflow_id, executor):
    workflow = WorkflowsManager(db).get_workflow(workflow_id)
    return executor.execute_workflow(
        workflow=workflow,
        entity={'id': 't-1', 'name': 'orders'},
        entity_type='table', entity_id='t-1', entity_name='orders',
        user_email='pat@example.com',
        trigger_context=TriggerContext(
            entity_type='table', entity_id='t-1', entity_name='orders',
            trigger_type=TriggerType.MANUAL, user_email='pat@example.com',
        ),
    )


def _resume(executor, execution_id, reason=None):
    return executor.resume_workflow(
        execution_id=execution_id, step_result=True,
        result_data={'reason': reason} if reason else {},
        user_email='reviewer@example.com',
    )


def test_steps_after_an_approval_see_the_results_before_it(db_session):
    db_workflow = _create(db_session, [
        _step('validate', StepType.VALIDATION, {'rule': RULE}, on_pass='approve'),
        _approval('approve', on_pass='done'),
        _step('done', StepType.PASS),
    ])
    before = WorkflowExecutor(db_session)
    spy_before = _Spy(before)
    paused = _run(db_session, db_workflow.id, before)
    assert paused.status.value == 'paused'
    validate_entry = spy_before.seen['approve']['validate']

    after = WorkflowExecutor(db_session)
    spy_after = _Spy(after)
    resumed = _resume(after, paused.id, reason='Looks good')

    assert resumed.status.value == 'succeeded'
    seen = spy_after.seen['done']
    # Same entry as the step saw before the pause: passed, message, data
    assert seen['validate'] == validate_entry
    assert seen['approve']['decision'] == 'approved'
    assert seen['approve']['reason'] == 'Looks good'


def test_a_template_after_the_approval_reads_the_earlier_message(db_session):
    db_workflow = _create(db_session, [
        _step('validate', StepType.VALIDATION, {'rule': FAILING_RULE}, on_fail='approve'),
        _approval('approve', on_pass='done'),
        _step('done', StepType.PASS),
    ])
    before = WorkflowExecutor(db_session)
    spy_before = _Spy(before)
    paused = _run(db_session, db_workflow.id, before)
    message = spy_before.seen['approve']['validate']['message']
    assert message and message.startswith('Assertion failed')

    after = WorkflowExecutor(db_session)
    spy_after = _Spy(after)
    _resume(after, paused.id)

    assert substitute_template('${step_results.validate.message}', spy_after.context) == message


def test_a_conditional_keeps_its_branch_across_the_pause(db_session):
    db_workflow = _create(db_session, [
        _step('check', StepType.CONDITIONAL, {'condition': '1 != 1'}, on_pass='approve', on_fail='approve'),
        _approval('approve', on_pass='done'),
        _step('done', StepType.PASS),
    ])
    paused = _run(db_session, db_workflow.id, WorkflowExecutor(db_session))

    after = WorkflowExecutor(db_session)
    spy = _Spy(after)
    _resume(after, paused.id)

    assert spy.seen['done']['check']['branch'] == 'false'
    assert spy.seen['done']['check']['passed'] is True


def test_two_approvals_in_one_run_keep_every_earlier_result(db_session):
    db_workflow = _create(db_session, [
        _step('validate', StepType.VALIDATION, {'rule': RULE}, on_pass='first'),
        _approval('first', on_pass='check'),
        _step('check', StepType.CONDITIONAL, {'condition': '1 = 1'}, on_pass='second', on_fail='second'),
        _approval('second', on_pass='done'),
        _step('done', StepType.PASS),
    ])
    paused = _run(db_session, db_workflow.id, WorkflowExecutor(db_session))
    paused_again = _resume(WorkflowExecutor(db_session), paused.id, reason='First ok')
    assert paused_again.status.value == 'paused'

    last = WorkflowExecutor(db_session)
    spy = _Spy(last)
    resumed = _resume(last, paused.id, reason='Second ok')

    assert resumed.status.value == 'succeeded'
    seen = spy.seen['done']
    assert set(seen) == {'validate', 'first', 'check', 'second'}
    assert seen['first'] == {'passed': True, 'decision': 'approved', 'reason': 'First ok'}
    assert seen['second']['reason'] == 'Second ok'
    assert seen['check']['branch'] == 'true'
    assert seen['validate']['passed'] is True


def test_results_recorded_before_messages_were_stored_still_restore(db_session):
    """Runs paused before the upgrade have no stored message: the rest is restored."""
    db_workflow = _create(db_session, [
        _step('validate', StepType.VALIDATION, {'rule': FAILING_RULE}, on_fail='approve'),
        _approval('approve', on_pass='done'),
        _step('done', StepType.PASS),
    ])
    paused = _run(db_session, db_workflow.id, WorkflowExecutor(db_session))
    row = db_session.query(WorkflowStepExecutionDb).filter_by(
        execution_id=paused.id, step_key='validate',
    ).one()
    row.message = None
    db_session.commit()

    after = WorkflowExecutor(db_session)
    spy = _Spy(after)
    _resume(after, paused.id)

    assert spy.seen['done']['validate']['passed'] is False
    assert spy.seen['done']['validate']['message'] is None


def test_the_execution_details_return_each_step_message(db_session):
    import asyncio

    from src.routes.workflows_routes import get_execution

    db_workflow = _create(db_session, [
        _step('validate', StepType.VALIDATION, {'rule': FAILING_RULE}, on_fail='done'),
        _step('done', StepType.PASS),
    ])
    execution = _run(db_session, db_workflow.id, WorkflowExecutor(db_session))

    details = asyncio.run(get_execution(execution.id, db_session, None))

    by_key = {s['step_key']: s for s in details['step_executions']}
    assert by_key['validate']['message'].startswith('Assertion failed')
    assert by_key['done']['message'] == 'Workflow completed successfully'
