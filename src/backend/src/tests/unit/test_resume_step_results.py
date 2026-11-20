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
from src.db_models.tags import TagDb
from src.models.process_workflows import (
    EntityType,
    ProcessWorkflowCreate,
    StepType,
    TriggerContext,
    TriggerType,
    WorkflowExecutionCreate,
    WorkflowStepCreate,
    WorkflowTrigger,
)
from src.repositories.process_workflows_repository import (
    process_workflow_repo,
    workflow_execution_repo,
)
from src.repositories.tags_repository import tag_namespace_repo

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


def _seed_tags(db, *names):
    """Create the tags an Assign Tag step names: a tag not in the catalog fails the step
    (``tag_not_found``), and the run would end before the approval."""
    namespace = tag_namespace_repo.get_or_create_default_namespace(db, user_email=None)
    for name in names:
        if not db.query(TagDb).filter_by(namespace_id=namespace.id, name=name).first():
            db.add(TagDb(name=name, status='active', namespace_id=namespace.id))
    db.commit()


class _Spy:
    """Records the step_results each step sees, keyed by the step's id."""

    def __init__(self, executor):
        self.seen = {}
        self.tags = {}
        original = executor._execute_step

        def spy(step, context):
            self.seen[step.step_id] = {k: dict(v) if isinstance(v, dict) else v
                                       for k, v in context.step_results.items()}
            tags = context.entity.get('tags')
            self.tags[step.step_id] = dict(tags) if isinstance(tags, dict) else tags
            self.context = context
            return original(step, context)

        executor._execute_step = spy


def _run(db, workflow_id, executor, entity=None):
    workflow = WorkflowsManager(db).get_workflow(workflow_id)
    entity = entity or {'id': 't-1', 'name': 'orders'}
    return executor.execute_workflow(
        workflow=workflow,
        entity=entity,
        entity_type='table', entity_id='t-1', entity_name='orders',
        user_email='pat@example.com',
        trigger_context=TriggerContext(
            entity_type='table', entity_id='t-1', entity_name='orders',
            trigger_type=TriggerType.MANUAL, user_email='pat@example.com',
            entity_data=entity,
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


def test_runs_written_within_one_second_restore_the_later_one(db_session):
    """Two runs of a step written in the same second (SQLite keeps whole
    seconds) still sort by when they ran, so the later run is the one restored."""
    db_workflow = _create(db_session, [_step('check', StepType.VALIDATION, {'rule': RULE})])
    workflow = WorkflowsManager(db_session).get_workflow(db_workflow.id)
    steps_by_id = {s.step_id: s for s in workflow.steps}
    execution = workflow_execution_repo.create(
        db_session, WorkflowExecutionCreate(workflow_id=db_workflow.id),
    )
    first = workflow_execution_repo.add_step_execution(
        db_session, execution_id=execution.id, step_id=steps_by_id['check'].id,
        status='failed', passed=False, message='first run',
    )
    second = workflow_execution_repo.add_step_execution(
        db_session, execution_id=execution.id, step_id=steps_by_id['check'].id,
        status='failed', passed=False, message='second run',
    )
    assert first.started_at < second.started_at

    restored = WorkflowExecutor(db_session)._restored_step_results(execution.id, steps_by_id)

    assert restored['check']['message'] == 'second run'


def test_runs_with_equal_timestamps_keep_their_insertion_order(db_session, monkeypatch):
    """A coarse clock gives two runs the same instant. Ids are random, so the
    row written last must still sort last (the repository bumps it by 1 us)."""
    import src.repositories.process_workflows_repository as repo_module

    frozen = repo_module.utc_now()
    monkeypatch.setattr(repo_module, 'utc_now', lambda: frozen)
    db_workflow = _create(db_session, [_step('check', StepType.VALIDATION, {'rule': RULE})])
    workflow = WorkflowsManager(db_session).get_workflow(db_workflow.id)
    steps_by_id = {s.step_id: s for s in workflow.steps}
    execution = workflow_execution_repo.create(
        db_session, WorkflowExecutionCreate(workflow_id=db_workflow.id),
    )
    stamps = [
        workflow_execution_repo.add_step_execution(
            db_session, execution_id=execution.id, step_id=steps_by_id['check'].id,
            status='failed', passed=False, message=f'run {n}',
        ).started_at
        for n in range(6)
    ]

    assert stamps == sorted(set(stamps))  # strictly increasing: nothing left to a tie
    restored = WorkflowExecutor(db_session)._restored_step_results(execution.id, steps_by_id)
    assert restored['check']['message'] == 'run 5'


def test_a_decided_pause_record_is_not_the_open_one(db_session, monkeypatch):
    """Rounds are told apart by the ``status: decided`` marker, not by timestamps:
    the decided round's pause record and its decision are skipped, even when the
    new round's record carries the same instant."""
    import src.repositories.process_workflows_repository as repo_module

    frozen = repo_module.utc_now()
    monkeypatch.setattr(repo_module, 'utc_now', lambda: frozen)
    db_workflow = _create(db_session, [
        _approval('approve', on_pass='done'), _step('done', StepType.PASS),
    ])
    workflow = WorkflowsManager(db_session).get_workflow(db_workflow.id)
    approve = next(s for s in workflow.steps if s.step_id == 'approve')
    execution = workflow_execution_repo.create(
        db_session, WorkflowExecutionCreate(workflow_id=db_workflow.id),
    )

    def add(data):
        return workflow_execution_repo.add_step_execution(
            db_session, execution_id=execution.id, step_id=approve.id,
            status='succeeded', passed=True, result_data=data,
        )

    add({'status': 'decided', 'approvers': 'round 1'})
    add({'approval_result': 'approved'})
    open_round = add({'status': 'pending', 'approvers': 'round 2'})

    found = WorkflowExecutor(db_session)._approval_pause_record(execution.id, approve)

    assert found is not None and found.id == open_round.id
    db_session.delete(open_round)
    db_session.commit()
    assert WorkflowExecutor(db_session)._approval_pause_record(execution.id, approve) is None


def test_tags_set_in_the_run_context_survive_the_approval(db_session):
    """Tags the steps before the approval set in the run context are what a step
    after it sees, as it would without the pause."""
    _seed_tags(db_session, 'tier', 'reviewed')
    db_workflow = _create(db_session, [
        _step('tier', StepType.ASSIGN_TAG, {'key': 'tier', 'value': 'gold'}, on_pass='flag'),
        _step('flag', StepType.ASSIGN_TAG, {'key': 'reviewed'}, on_pass='drop'),
        _step('drop', StepType.REMOVE_TAG, {'key': 'stale'}, on_pass='approve'),
        _approval('approve', on_pass='done'),
        _step('done', StepType.PASS),
    ])
    before = WorkflowExecutor(db_session)
    spy_before = _Spy(before)
    entity = {'id': 't-1', 'name': 'orders', 'tags': {'stale': 'yes', 'owner': 'pat'}}
    paused = _run(db_session, db_workflow.id, before, entity=entity)
    assert paused.status.value == 'paused'
    tags_at_pause = spy_before.tags['approve']
    assert tags_at_pause == {'owner': 'pat', 'tier': 'gold', 'reviewed': True}

    after = WorkflowExecutor(db_session)
    spy_after = _Spy(after)
    resumed = _resume(after, paused.id)

    assert resumed.status.value == 'succeeded'
    assert spy_after.tags['done'] == tags_at_pause


def test_tags_changed_between_two_approvals_survive_both(db_session):
    _seed_tags(db_session, 'tier')
    db_workflow = _create(db_session, [
        _approval('first', on_pass='tier'),
        _step('tier', StepType.ASSIGN_TAG, {'key': 'tier', 'value': 'gold'}, on_pass='second'),
        _approval('second', on_pass='done'),
        _step('done', StepType.PASS),
    ])
    paused = _run(db_session, db_workflow.id, WorkflowExecutor(db_session))
    paused_again = _resume(WorkflowExecutor(db_session), paused.id)
    assert paused_again.status.value == 'paused'

    last = WorkflowExecutor(db_session)
    spy = _Spy(last)
    _resume(last, paused.id)

    assert spy.tags['done'] == {'tier': 'gold'}


def _paused_with_tags(db_session):
    _seed_tags(db_session, 'tier')
    db_workflow = _create(db_session, [
        _step('tier', StepType.ASSIGN_TAG, {'key': 'tier', 'value': 'gold'}, on_pass='approve'),
        _approval('approve', on_pass='done'),
        _step('done', StepType.PASS),
    ])
    paused = _run(db_session, db_workflow.id, WorkflowExecutor(db_session),
                  entity={'id': 't-1', 'name': 'orders', 'tags': {'owner': 'pat'}})
    assert paused.status.value == 'paused'
    return paused


def test_the_api_does_not_return_the_reserved_context_tags_key(db_session):
    import asyncio
    import json

    from src.routes.workflows_routes import get_execution

    paused = _paused_with_tags(db_session)

    # The pause record still stores the tags for the resume
    record = db_session.query(WorkflowStepExecutionDb).filter_by(
        execution_id=paused.id, step_key='approve',
    ).one()
    assert json.loads(record.result_data)['_context_tags'] == {'owner': 'pat', 'tier': 'gold'}

    details = asyncio.run(get_execution(paused.id, db_session, None))
    approve = next(s for s in details['step_executions'] if s['step_key'] == 'approve')
    assert '_context_tags' not in (approve['result_data'] or {})

    # The execution model (self-service, notices) does not carry it either
    assert all('_context_tags' not in (s.result_data or {}) for s in paused.step_executions)

    # The resume still gets the tags back
    after = WorkflowExecutor(db_session)
    spy = _Spy(after)
    _resume(after, paused.id)
    assert spy.tags['done'] == {'owner': 'pat', 'tier': 'gold'}


def test_public_result_data_only_drops_reserved_keys():
    from src.common.workflow_executor import public_result_data

    assert public_result_data(None) is None
    assert public_result_data('') is None
    assert public_result_data('{"_context_tags": {"a": 1}, "reason": "ok", "_other": 2}') == {
        'reason': 'ok', '_other': 2,
    }
