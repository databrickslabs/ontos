"""Pass/Fail steps end a run (#1417); a false Conditional picks its branch (#1418).

Up to v1.0.2 the designer saved a link from a Pass or Fail step to the step added
after it, which the canvas never drew. The executor followed it, so a run went on
from its Pass step into a Fail step. A Conditional that evaluated to false was
recorded as a failed step, though it only picked its false branch.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid

from src.common.workflow_executor import WorkflowExecutor
from src.controller.workflows_manager import WorkflowsManager
from src.db_models.process_workflows import WorkflowStepDb
from src.models.process_workflows import (
    EntityType,
    ProcessWorkflowCreate,
    ProcessWorkflowUpdate,
    StepType,
    TriggerContext,
    TriggerType,
    WorkflowStepCreate,
    WorkflowTrigger,
    WorkflowType,
)
from src.repositories.process_workflows_repository import process_workflow_repo


def _step(step_id, step_type, config=None, on_pass=None, on_fail=None):
    return WorkflowStepCreate(
        step_id=step_id, step_type=step_type, config=config or {},
        on_pass=on_pass, on_fail=on_fail,
    )


def _create(db, steps):
    return process_workflow_repo.create(db, ProcessWorkflowCreate(
        name=f'wf-{uuid.uuid4().hex[:6]}',
        trigger=WorkflowTrigger(type=TriggerType.MANUAL, entity_types=[EntityType.TABLE]),
        steps=steps,
    ))


def _store_link(db, workflow_id, step_id, on_pass=None, on_fail=None):
    """Write a link as an older designer stored it, bypassing the save path."""
    row = db.query(WorkflowStepDb).filter_by(workflow_id=workflow_id, step_id=step_id).one()
    row.on_pass = on_pass
    row.on_fail = on_fail
    db.commit()


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


def _conditional(condition, on_pass='done', on_fail='stop'):
    return _step('check', StepType.CONDITIONAL, {'condition': condition}, on_pass, on_fail)


# --- #1417: Pass and Fail steps end the run ---------------------------------


def test_a_pass_step_ends_the_run_despite_a_stored_next_step(db_session):
    db_workflow = _create(db_session, [
        _step('done', StepType.PASS),
        _step('stop', StepType.FAIL, {'message': 'Should not run'}),
    ])
    _store_link(db_session, db_workflow.id, 'done', on_pass='stop')

    execution = _run(db_session, db_workflow.id)

    assert _ran(execution) == [('done', 'succeeded')]
    assert execution.status.value == 'succeeded'
    assert execution.failure_count == 0


def test_a_fail_step_ends_the_run_despite_a_stored_next_step(db_session):
    db_workflow = _create(db_session, [
        _step('stop', StepType.FAIL, {'message': 'Rule failed'}),
        _step('done', StepType.PASS),
    ])
    _store_link(db_session, db_workflow.id, 'stop', on_pass='done', on_fail='done')

    execution = _run(db_session, db_workflow.id)

    assert _ran(execution) == [('stop', 'failed')]
    assert execution.status.value == 'failed'
    assert execution.error_message == 'Rule failed'


def test_a_pass_step_after_an_approval_ends_the_resumed_run(db_session):
    db_workflow = _create(db_session, [
        _step('approve', StepType.APPROVAL, {'approvers': 'reviewer@example.com'}, on_pass='done'),
        _step('done', StepType.PASS),
        _step('stop', StepType.FAIL),
    ])
    _store_link(db_session, db_workflow.id, 'done', on_pass='stop')
    paused = _run(db_session, db_workflow.id)
    assert paused.status.value == 'paused'

    resumed = WorkflowExecutor(db_session).resume_workflow(
        execution_id=paused.id, step_result=True,
        result_data={'decision': 'approved'}, user_email='reviewer@example.com',
    )

    keys = [key for key, _ in _ran(resumed)]
    assert keys[-1] == 'done' and 'stop' not in keys
    assert resumed.status.value == 'succeeded'


def test_approval_workflows_keep_links_out_of_pass_steps(db_session):
    """The wizard runtime passes through a Pass step that has a next step."""
    db_workflow = process_workflow_repo.create(db_session, ProcessWorkflowCreate(
        name=f'wf-{uuid.uuid4().hex[:6]}', workflow_type=WorkflowType.APPROVAL,
        trigger=WorkflowTrigger(type=TriggerType.MANUAL, entity_types=[EntityType.TABLE]),
        steps=[_step('mid', StepType.PASS, on_pass='end'), _step('end', StepType.PASS)],
    ))
    row = db_session.query(WorkflowStepDb).filter_by(workflow_id=db_workflow.id, step_id='mid').one()
    assert row.on_pass == 'end'

    result = WorkflowsManager(db_session).validate_workflow(ProcessWorkflowCreate(
        name='wf', workflow_type=WorkflowType.APPROVAL,
        trigger=WorkflowTrigger(type=TriggerType.MANUAL, entity_types=[EntityType.TABLE]),
        steps=[_step('mid', StepType.PASS, on_pass='end'), _step('end', StepType.PASS)],
    ))
    assert [w.code for w in result.warning_issues] == []


def test_a_terminal_step_with_two_links_reports_both(db_session):
    result = WorkflowsManager(db_session).validate_workflow(ProcessWorkflowCreate(
        name='wf',
        trigger=WorkflowTrigger(type=TriggerType.MANUAL, entity_types=[EntityType.TABLE]),
        steps=[_step('stop', StepType.FAIL, on_pass='a', on_fail='b'), _step('a', StepType.PASS), _step('b', StepType.PASS)],
    ))
    targets = [w.params['target'] for w in result.warning_issues if w.code == 'terminal_step_has_next']
    assert targets == ['a', 'b']


def test_saving_drops_links_out_of_terminal_steps(db_session):
    db_workflow = _create(db_session, [
        _step('done', StepType.PASS, on_pass='stop'),
        _step('stop', StepType.FAIL, on_fail='done'),
    ])
    rows = {r.step_id: r for r in db_session.query(WorkflowStepDb).filter_by(workflow_id=db_workflow.id)}
    assert (rows['done'].on_pass, rows['stop'].on_fail) == (None, None)

    _store_link(db_session, db_workflow.id, 'done', on_pass='stop')
    workflow = WorkflowsManager(db_session).get_workflow(db_workflow.id)
    process_workflow_repo.update(db_session, db_workflow.id, ProcessWorkflowUpdate(steps=[
        WorkflowStepCreate(**{k: getattr(s, k) for k in ('step_id', 'name', 'step_type', 'config', 'on_pass', 'on_fail', 'order')})
        for s in workflow.steps
    ]))
    db_session.expire_all()
    row = db_session.query(WorkflowStepDb).filter_by(workflow_id=db_workflow.id, step_id='done').one()
    assert row.on_pass is None


def test_validation_warns_about_links_out_of_terminal_steps(db_session):
    result = WorkflowsManager(db_session).validate_workflow(ProcessWorkflowCreate(
        name='wf',
        trigger=WorkflowTrigger(type=TriggerType.MANUAL, entity_types=[EntityType.TABLE]),
        steps=[_step('done', StepType.PASS, on_pass='stop'), _step('stop', StepType.FAIL)],
    ))

    assert result.valid
    by_code = {w.code: w for w in result.warning_issues}
    assert by_code['terminal_step_has_next'].params == {'step': 'done', 'target': 'stop'}
    # The Fail step is reachable only through the ignored link
    assert by_code['unreachable_steps'].params == {'steps': ['stop']}


# --- #1418: a Conditional picks a branch, it doesn't fail --------------------


def test_a_false_condition_succeeds_and_takes_the_false_branch(db_session):
    db_workflow = _create(db_session, [
        _conditional('1 != 1'),
        _step('done', StepType.PASS),
        _step('stop', StepType.FAIL, {'message': 'Condition not met'}),
    ])

    execution = _run(db_session, db_workflow.id)

    assert _ran(execution) == [('check', 'succeeded'), ('stop', 'failed')]
    check = execution.step_executions[0]
    assert check.passed is True
    assert check.result_data['result'] is False
    assert check.result_data['branch'] == 'false'
    # The run fails at its Fail step, and only that step counts as a failure
    assert execution.status.value == 'failed'
    assert (execution.success_count, execution.failure_count) == (1, 1)


def test_a_true_condition_takes_the_true_branch(db_session):
    db_workflow = _create(db_session, [
        _conditional('1 = 1'),
        _step('done', StepType.PASS),
        _step('stop', StepType.FAIL),
    ])

    execution = _run(db_session, db_workflow.id)

    assert _ran(execution) == [('check', 'succeeded'), ('done', 'succeeded')]
    assert execution.step_executions[0].result_data['branch'] == 'true'
    assert execution.status.value == 'succeeded'


def test_a_false_condition_with_a_pass_on_its_false_branch_succeeds(db_session):
    db_workflow = _create(db_session, [
        _conditional('1 != 1', on_pass='stop', on_fail='done'),
        _step('done', StepType.PASS),
        _step('stop', StepType.FAIL),
    ])

    execution = _run(db_session, db_workflow.id)

    assert _ran(execution) == [('check', 'succeeded'), ('done', 'succeeded')]
    assert execution.status.value == 'succeeded'
    assert execution.failure_count == 0


def test_a_false_condition_with_nothing_on_its_branch_ends_the_run_succeeded(db_session):
    db_workflow = _create(db_session, [_conditional('1 != 1', on_pass=None, on_fail=None)])

    execution = _run(db_session, db_workflow.id)

    assert _ran(execution) == [('check', 'succeeded')]
    assert execution.status.value == 'succeeded'
    assert execution.error_message is None


def test_a_condition_that_cannot_be_evaluated_fails_the_step(db_session):
    db_workflow = _create(db_session, [
        _conditional('1 = = 1', on_fail='done'),
        _step('done', StepType.PASS),
        _step('stop', StepType.FAIL),
    ])

    execution = _run(db_session, db_workflow.id)

    check = execution.step_executions[0]
    assert check.status.value == 'failed'
    assert check.passed is False
    assert 'branch' not in (check.result_data or {})
    # An error is not a false condition: the run ends at the conditional, failed
    assert [key for key, _ in _ran(execution)] == ['check']
    assert execution.status.value == 'failed'
    assert execution.error_message


def test_validation_warns_about_a_conditional_without_a_false_branch(db_session):
    result = WorkflowsManager(db_session).validate_workflow(ProcessWorkflowCreate(
        name='wf',
        trigger=WorkflowTrigger(type=TriggerType.MANUAL, entity_types=[EntityType.TABLE]),
        steps=[_conditional('1 = 1', on_pass='done', on_fail=None), _step('done', StepType.PASS)],
    ))

    missing = [w.params for w in result.warning_issues if w.code == 'conditional_branch_missing']
    assert missing == [{'step': 'check', 'branch': 'false'}]


def test_later_steps_see_the_branch_of_a_conditional(db_session):
    db_workflow = _create(db_session, [_conditional('1 != 1', on_pass=None, on_fail=None)])
    workflow = WorkflowsManager(db_session).get_workflow(db_workflow.id)
    executor = WorkflowExecutor(db_session)
    seen = {}
    original = executor._execute_step

    def spy(step, context):
        result = original(step, context)
        seen['context'] = context
        return result

    executor._execute_step = spy
    executor.execute_workflow(
        workflow=workflow, entity={'id': 't-1'}, entity_type='table', entity_id='t-1',
        entity_name='orders', user_email='pat@example.com',
    )

    assert seen['context'].step_results['check']['branch'] == 'false'


def test_a_failed_validation_rule_still_counts_as_a_failure(db_session):
    db_workflow = _create(db_session, [
        _step('rule', StepType.VALIDATION, {'rule': 'MATCH (obj:Object) ASSERT 1 != 1'},
              on_pass='done', on_fail='notify'),
        _step('notify', StepType.PASS),
        _step('done', StepType.PASS),
    ])

    execution = _run(db_session, db_workflow.id)

    assert _ran(execution) == [('rule', 'failed'), ('notify', 'succeeded')]
    assert execution.failure_count == 1
    assert execution.status.value == 'succeeded'


# --- startup scan, stored values, approval workflows -------------------------


def test_startup_scan_logs_stored_terminal_links_and_open_gate_branches(db_session, caplog):
    linked = _create(db_session, [_step('done', StepType.PASS), _step('stop', StepType.FAIL)])
    _store_link(db_session, linked.id, 'done', on_pass='stop')
    gate = process_workflow_repo.create(db_session, ProcessWorkflowCreate(
        name='gate', trigger=WorkflowTrigger(type=TriggerType.BEFORE_UPDATE, entity_types=[EntityType.DATA_CONTRACT]),
        steps=[_conditional('1 = 1', on_pass='done', on_fail=None), _step('done', StepType.PASS)],
    ))
    _create(db_session, [_conditional('1 = 1', on_pass='done', on_fail=None), _step('done', StepType.PASS)])

    with caplog.at_level('WARNING'):
        warned = WorkflowsManager(db_session).log_branching_warnings()

    assert warned == 2
    assert linked.id in caplog.text and "['done']" in caplog.text
    assert gate.id in caplog.text and "check:false" in caplog.text


def test_a_condition_that_returns_a_value_is_stored_as_text(db_session):
    from datetime import datetime
    from unittest.mock import patch

    db_workflow = _create(db_session, [_conditional('obj.name', on_pass='done', on_fail='stop'),
                                       _step('done', StepType.PASS), _step('stop', StepType.FAIL)])
    with patch('src.common.compliance_dsl.Evaluator.evaluate', return_value=datetime(2026, 1, 2)):
        execution = _run(db_session, db_workflow.id)

    check = execution.step_executions[0]
    assert check.result_data['result'] == '2026-01-02 00:00:00'
    assert check.result_data['branch'] == 'true'
    assert execution.status.value == 'succeeded'


# --- validate keeps the coded warnings next to policy and trigger errors -----


def _validate(db, workflow):
    import asyncio
    from unittest.mock import MagicMock

    from src.routes.workflows_routes import validate_workflow

    return asyncio.run(validate_workflow(
        request=MagicMock(), workflow=workflow, workflow_id=None,
        manager=WorkflowsManager(db),
    ))


def _terminal_link_workflow(trigger, is_active):
    return ProcessWorkflowCreate(
        name='wf', trigger=trigger, is_active=is_active,
        steps=[
            _step('check', StepType.POLICY_CHECK, {'policy_id': 'missing'}, on_pass='done'),
            _step('done', StepType.PASS, on_pass='stop'),
            _step('stop', StepType.FAIL),
        ],
    )


def test_validate_keeps_coded_warnings_next_to_policy_errors(db_session):
    trigger = WorkflowTrigger(type=TriggerType.MANUAL, entity_types=[EntityType.TABLE])

    result = _validate(db_session, _terminal_link_workflow(trigger, True))

    assert [i.code for i in result.issues] == ['policy_check_policy_missing']
    codes = {w.code for w in result.warning_issues}
    assert 'terminal_step_has_next' in codes
    assert 'workflow_validation_warning' not in codes


def test_validate_keeps_coded_warnings_next_to_trigger_errors(db_session):
    trigger = WorkflowTrigger(
        type=TriggerType.MANUAL, entity_types=[EntityType.TABLE],
        unknown_entity_types=['bogus'],
    )

    result = _validate(db_session, _terminal_link_workflow(trigger, False))

    assert 'trigger_entity_type_unknown' in [i.code for i in result.issues]
    codes = {w.code for w in result.warning_issues}
    assert 'terminal_step_has_next' in codes
    assert 'workflow_validation_warning' not in codes
