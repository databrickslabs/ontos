"""The workflow scheduler and the ``scheduled`` trigger's validation (#941)."""
import os

os.environ['TESTING'] = 'true'

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from src.common.workflow_executor import WorkflowExecutor
from src.controller.workflow_scheduler import (
    COALESCE_COUNT_LIMIT,
    SCHEDULER_USER,
    WorkflowScheduler,
    notify_schedules_changed,
    task_key,
)
from src.controller.workflows_manager import WorkflowsManager
from src.db_models.process_workflows import ProcessWorkflowDb, WorkflowExecutionDb
from src.db_models.scheduler_claims import SchedulerClaimDb
from src.models.process_workflows import (
    ProcessWorkflowCreate,
    StepType,
    TriggerType,
    WorkflowStepCreate,
    WorkflowTrigger,
)
from src.repositories.scheduler_claims_repository import scheduler_claims_repo

UTC = timezone.utc
CHANGED = datetime(2026, 1, 1, tzinfo=UTC)
EVERY_5 = '0 0/5 * * * ?'


def _at(day=5, hour=10, minute=0, second=0):
    return datetime(2026, 1, day, hour, minute, second, tzinfo=UTC)


def _create(db, schedule=EVERY_5, tz=None, *, active=True, trigger_type=TriggerType.SCHEDULED,
            name='Nightly', changed=CHANGED):
    workflow = WorkflowsManager(db).create_workflow(ProcessWorkflowCreate(
        name=name,
        trigger=WorkflowTrigger(type=trigger_type, schedule=schedule, timezone=tz),
        is_active=active,
        steps=[WorkflowStepCreate(step_id='done', name='Done', step_type=StepType.PASS, order=0)],
    ))
    db.query(ProcessWorkflowDb).filter(ProcessWorkflowDb.id == workflow.id).update(
        {'updated_at': changed, 'created_at': changed}, synchronize_session=False)
    db.commit()
    return workflow


class _Sessions:
    """Session factory on the test connection that counts how often it is used."""

    def __init__(self, db):
        self._factory = sessionmaker(bind=db.get_bind(), autoflush=False)
        self.opened = 0

    def __call__(self):
        self.opened += 1
        return self._factory()


@pytest.fixture
def sessions(db_session):
    return _Sessions(db_session)


def _scheduler(sessions, name='a'):
    return WorkflowScheduler(sessions, tick_seconds=60, instance_id=name)


def _executions(db, workflow_id):
    return db.query(WorkflowExecutionDb).filter(
        WorkflowExecutionDb.workflow_id == workflow_id).all()


def _claims(db, workflow_id):
    return db.query(SchedulerClaimDb).filter(
        SchedulerClaimDb.task_key == task_key(workflow_id)).all()


# --- no database while nothing is scheduled --------------------------------------

def test_no_database_access_while_no_workflow_is_scheduled(db_session, sessions):
    _create(db_session, trigger_type=TriggerType.MANUAL, schedule=None, name='Manual')
    _create(db_session, active=False, name='Off')
    scheduler = _scheduler(sessions)

    assert scheduler.run_once(_at()) == 60
    assert sessions.opened == 1  # the first tick looks once
    for minute in range(1, 30):
        scheduler.run_once(_at(minute=minute))
    assert sessions.opened == 1

    _create(db_session, name='Now scheduled')  # create_workflow notifies the scheduler
    scheduler.run_once(_at(minute=31))
    # Look again, then the 10:30 slot: re-read the definitions, claim and run.
    assert sessions.opened == 4


@pytest.mark.parametrize('change', ['update', 'toggle', 'delete'])
def test_every_workflow_change_makes_the_scheduler_look_again(db_session, sessions, change):
    from src.models.process_workflows import ProcessWorkflowUpdate

    workflow = _create(db_session, trigger_type=TriggerType.MANUAL, schedule=None)
    scheduler = _scheduler(sessions)
    scheduler.run_once(_at())
    assert sessions.opened == 1
    manager = WorkflowsManager(db_session)
    if change == 'update':
        manager.update_workflow(workflow.id, ProcessWorkflowUpdate(description='x'))
    elif change == 'toggle':
        manager.toggle_active(workflow.id, False)
    else:
        manager.delete_workflow(workflow.id)
    scheduler.run_once(_at(minute=1))
    assert sessions.opened == 2


def test_between_slots_the_scheduler_reads_nothing(db_session, sessions):
    _create(db_session)
    scheduler = _scheduler(sessions)
    scheduler.run_once(_at(minute=0, second=10))  # load + fire 10:00
    opened = sessions.opened
    for second in (20, 40):
        scheduler.run_once(_at(minute=0, second=second))
    scheduler.run_once(_at(minute=4, second=59))
    assert sessions.opened == opened


def test_the_sleep_ends_at_the_next_slot(db_session, sessions):
    _create(db_session)
    scheduler = _scheduler(sessions)
    assert scheduler.run_once(_at(minute=4, second=40)) == pytest.approx(20.5)


# --- a run -------------------------------------------------------------------------

def test_a_due_slot_runs_the_workflow_as_the_scheduler(db_session, sessions):
    workflow = _create(db_session, changed=_at(hour=9, minute=58))
    _scheduler(sessions).run_once(_at(minute=0, second=3))

    [execution] = _executions(db_session, workflow.id)
    assert execution.triggered_by == SCHEDULER_USER
    assert execution.status == 'succeeded'
    [claim] = _claims(db_session, workflow.id)
    assert claim.execution_id == execution.id
    assert claim.claimed_by == 'a'
    assert claim.outcome == {
        'status': 'succeeded', 'coalesced_slots': 1, 'execution_id': execution.id,
    }


def test_the_run_has_the_schedule_entity_and_no_requester(db_session, sessions):
    workflow = _create(db_session)
    captured = {}
    original = WorkflowExecutor.execute_workflow

    def spy(self, **kwargs):
        captured.update(kwargs)
        return original(self, **kwargs)

    with patch.object(WorkflowExecutor, 'execute_workflow', spy):
        _scheduler(sessions).run_once(_at(minute=0, second=3))

    slot = '2026-01-05T10:00:00+00:00'
    assert captured['entity'] == {
        'type': 'schedule', 'id': workflow.id, 'name': 'Nightly', 'scheduled_for': slot,
    }
    assert captured['entity_type'] == 'schedule' and captured['entity_id'] == workflow.id
    assert captured['user_email'] is None
    assert captured['triggered_by'] == SCHEDULER_USER
    context = captured['trigger_context']
    assert context.trigger_type == TriggerType.SCHEDULED and context.user_email is None


def test_a_slot_runs_once_per_scheduler_and_the_next_slot_runs_again(db_session, sessions):
    workflow = _create(db_session)
    scheduler = _scheduler(sessions)
    for second in (1, 30, 59):
        scheduler.run_once(_at(minute=0, second=second))
    scheduler.run_once(_at(minute=5, second=1))
    assert len(_executions(db_session, workflow.id)) == 2


def test_a_second_scheduler_finds_the_slot_claimed(db_session, sessions):
    workflow = _create(db_session)
    _scheduler(sessions, 'a').run_once(_at(minute=0, second=1))
    _scheduler(sessions, 'b').run_once(_at(minute=0, second=2))
    assert len(_executions(db_session, workflow.id)) == 1
    assert [c.claimed_by for c in _claims(db_session, workflow.id)] == ['a']


def test_a_slot_before_the_workflow_changed_is_not_run(db_session, sessions):
    workflow = _create(db_session)
    db_session.query(ProcessWorkflowDb).filter(ProcessWorkflowDb.id == workflow.id).update(
        {'updated_at': _at(minute=3)}, synchronize_session=False)
    db_session.commit()
    scheduler = _scheduler(sessions)
    scheduler.run_once(_at(minute=4))
    assert _executions(db_session, workflow.id) == []
    scheduler.run_once(_at(minute=5, second=1))
    assert len(_executions(db_session, workflow.id)) == 1


def test_an_invalid_stored_schedule_never_runs(db_session, sessions):
    _create(db_session, schedule='0 9 * * *', name='Unix cron')  # 5 fields
    _create(db_session, schedule='0 * * * * ?', name='Every minute')
    scheduler = _scheduler(sessions)
    scheduler.run_once(_at(minute=0, second=1))
    assert db_session.query(WorkflowExecutionDb).count() == 0
    assert scheduler._has_scheduled is False


# --- missed runs -------------------------------------------------------------------

def test_missed_runs_coalesce_into_the_latest_slot(db_session, sessions):
    workflow = _create(db_session)
    scheduler_claims_repo.claim(db_session, task_key=task_key(workflow.id), slot=_at(minute=0),
                                claimed_by='old')
    _scheduler(sessions).run_once(_at(minute=31))  # 10:05 ... 10:30 were missed

    claims = {c.slot.replace(tzinfo=UTC): c for c in _claims(db_session, workflow.id)}
    assert sorted(claims) == [_at(minute=0), _at(minute=30)]
    assert claims[_at(minute=30)].outcome['coalesced_slots'] == 6
    assert len(_executions(db_session, workflow.id)) == 1


def test_coalesced_slots_count_from_the_last_change_without_an_earlier_claim(
        db_session, sessions):
    workflow = _create(db_session)
    db_session.query(ProcessWorkflowDb).filter(ProcessWorkflowDb.id == workflow.id).update(
        {'updated_at': _at(minute=10)}, synchronize_session=False)
    db_session.commit()
    _scheduler(sessions).run_once(_at(minute=21))  # 10:10, 10:15, 10:20
    [claim] = _claims(db_session, workflow.id)
    assert claim.outcome['coalesced_slots'] == 3


def test_the_coalesced_count_is_capped(db_session, sessions):
    workflow = _create(db_session)  # changed 2026-01-01, so ~1150 slots by 01-05 10:00
    with patch('src.controller.workflow_scheduler.COALESCE_COUNT_LIMIT', 100):
        _scheduler(sessions).run_once(_at(minute=0, second=1))
    [claim] = _claims(db_session, workflow.id)
    assert claim.outcome['coalesced_slots'] == 100
    assert COALESCE_COUNT_LIMIT == 10_000


def test_a_missed_slot_older_than_24_hours_is_not_run(db_session, sessions):
    weekly = _create(db_session, schedule='0 0 0 ? * MON', name='Weekly')  # 2026-01-05 is a Monday
    _scheduler(sessions, 'late').run_once(_at(day=6, hour=1))  # 25 hours late
    assert _executions(db_session, weekly.id) == []
    _scheduler(sessions, 'in-time').run_once(_at(day=5, hour=23))  # 23 hours late
    assert len(_executions(db_session, weekly.id)) == 1


def test_the_schedule_timezone_decides_the_slot(db_session, sessions):
    workflow = _create(db_session, schedule='0 0 9 * * ?', tz='America/Sao_Paulo',
                       changed=_at(hour=0))
    scheduler = _scheduler(sessions)
    scheduler.run_once(_at(hour=9, minute=1))  # 09:01Z = 06:01 in Sao Paulo
    assert _executions(db_session, workflow.id) == []
    scheduler.run_once(_at(hour=12, minute=1))  # 09:01 in Sao Paulo
    [claim] = _claims(db_session, workflow.id)
    assert claim.slot.replace(tzinfo=UTC) == _at(hour=12)


# --- stop firing -------------------------------------------------------------------

def test_an_inactive_or_deleted_workflow_stops_firing(db_session, sessions):
    off = _create(db_session, name='Off')
    gone = _create(db_session, name='Gone')
    scheduler = _scheduler(sessions)
    scheduler.run_once(_at(minute=0, second=1))
    manager = WorkflowsManager(db_session)
    manager.toggle_active(off.id, False)
    manager.delete_workflow(gone.id)
    scheduler.run_once(_at(minute=5, second=1))
    assert len(_executions(db_session, off.id)) == 1
    assert _executions(db_session, gone.id) == []
    assert scheduler._has_scheduled is False


def test_notify_reaches_every_live_scheduler(sessions):
    first, second = _scheduler(sessions, 'a'), _scheduler(sessions, 'b')
    first._has_scheduled = second._has_scheduled = False
    notify_schedules_changed()
    assert first._has_scheduled is None and second._has_scheduled is None
    assert first._wake.is_set() and second._wake.is_set()


def test_the_thread_starts_and_stops(sessions):
    scheduler = _scheduler(sessions)
    scheduler.start()
    assert scheduler._thread.is_alive()
    scheduler.stop()
    assert not scheduler._thread.is_alive()


# --- triggered_by is not the requester -------------------------------------------

def test_execute_workflow_records_triggered_by_apart_from_the_user(db_session):
    workflow = _create(db_session, trigger_type=TriggerType.MANUAL, schedule=None)
    executor = WorkflowExecutor(db_session)
    seen = []
    original = executor._execute_step

    def spy(step, context):
        seen.append(context.user_email)
        return original(step, context)

    executor._execute_step = spy
    scheduled = executor.execute_workflow(
        workflow=workflow, entity={}, entity_type='schedule', entity_id=workflow.id,
        user_email=None, triggered_by=SCHEDULER_USER,
    )
    manual = executor.execute_workflow(
        workflow=workflow, entity={}, entity_type='schedule', entity_id=workflow.id,
        user_email='ann@example.com',
    )
    assert (scheduled.triggered_by, manual.triggered_by) == (SCHEDULER_USER, 'ann@example.com')
    assert seen == [None, 'ann@example.com']


# --- validation and the timezone field ---------------------------------------------

def _validate(db, schedule, tz=None, trigger_type=TriggerType.SCHEDULED):
    return WorkflowsManager(db).validate_workflow(ProcessWorkflowCreate(
        name='Check',
        trigger=WorkflowTrigger(type=trigger_type, schedule=schedule, timezone=tz),
        steps=[WorkflowStepCreate(step_id='done', name='Done', step_type=StepType.PASS, order=0)],
    ))


@pytest.mark.parametrize(('schedule', 'tz', 'code'), [
    (None, None, 'schedule_required'),
    ('  ', None, 'schedule_required'),
    ('0 9 * * *', None, 'cron_field_count'),
    ('15 0 9 * * ?', None, 'cron_seconds_not_zero'),
    ('0 0 9 L * ?', None, 'cron_unsupported_character'),
    ('0 0 9 1 * MON', None, 'cron_day_fields_conflict'),
    ('0 0 99 * * ?', None, 'cron_invalid'),
    ('0 0,2 * * * ?', None, 'cron_interval_too_short'),
    ('0 0 9 * * ?', 'Nowhere/City', 'timezone_invalid'),
])
def test_scheduled_trigger_validation_codes(db_session, schedule, tz, code):
    result = _validate(db_session, schedule, tz)
    assert not result.valid
    assert [issue.code for issue in result.issues] == [code]


def test_a_valid_schedule_and_other_trigger_types_pass(db_session):
    assert _validate(db_session, '0 30 2 * * ?', 'Europe/Berlin').valid
    assert _validate(db_session, None, trigger_type=TriggerType.MANUAL).valid
    assert _validate(db_session, 'not cron', trigger_type=TriggerType.ON_CREATE).valid


def test_timezone_is_kept_on_read_and_duplicate(db_session):
    workflow = _create(db_session, schedule='0 30 2 * * ?', tz='Europe/Berlin')
    manager = WorkflowsManager(db_session)
    assert manager.get_workflow(workflow.id).trigger.timezone == 'Europe/Berlin'
    copy = manager.duplicate_workflow(workflow.id, 'Copy')
    assert (copy.trigger.schedule, copy.trigger.timezone) == ('0 30 2 * * ?', 'Europe/Berlin')
