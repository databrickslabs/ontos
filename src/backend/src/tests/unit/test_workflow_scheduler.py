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
        # Savepoints, so a scheduler session's rollback keeps the test's other rows.
        self._factory = sessionmaker(bind=db.get_bind(), autoflush=False,
                                     join_transaction_mode='create_savepoint')
        self.opened = 0

    def __call__(self):
        self.opened += 1
        return self._factory()


@pytest.fixture
def sessions(db_session):
    return _Sessions(db_session)


def _scheduler(sessions, name='a'):
    return WorkflowScheduler(sessions, instance_id=name)


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

    assert scheduler.run_once(_at()) is None  # nothing to wait for: sleep until woken
    assert sessions.opened == 1  # the first pass looks once
    for minute in range(1, 15):
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


def test_the_sleep_lasts_until_the_next_slot_however_far(db_session, sessions):
    # No fixed tick: an hourly schedule sleeps the hour, a daily one the day.
    _create(db_session, schedule='0 0 * * * ?', name='Hourly')
    scheduler = _scheduler(sessions)
    assert scheduler.run_once(_at(minute=0, second=1)) == pytest.approx(3599.5)
    _create(db_session, schedule='0 0 3 * * ?', name='Daily', changed=_at(minute=1))
    assert scheduler.run_once(_at(minute=1)) == pytest.approx(59 * 60 + 0.5)


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
    _create(db_session, schedule='0 0 9 * * ?', tz='Nowhere/City', name='Bad timezone')
    scheduler = _scheduler(sessions)
    scheduler.run_once(_at(minute=0, second=1))
    assert db_session.query(WorkflowExecutionDb).count() == 0
    assert scheduler._has_scheduled is False


def test_a_slot_too_soon_after_the_last_run_is_skipped_not_the_workflow(
        db_session, sessions, caplog):
    # Saved without the validator; the 5-minute rule only skips slots at runtime.
    workflow = _create(db_session, schedule='0 * * * * ?', changed=_at(hour=9, minute=59))
    scheduler = _scheduler(sessions)
    with caplog.at_level('WARNING', logger='src.controller.workflow_scheduler'):
        for minute in range(0, 11):
            scheduler.run_once(_at(minute=minute, second=1))
    slots = sorted(c.slot.replace(tzinfo=UTC) for c in _claims(db_session, workflow.id))
    assert slots == [_at(minute=0, second=0), _at(minute=5, second=0), _at(minute=10, second=0)]
    assert len(_executions(db_session, workflow.id)) == 3
    assert scheduler._has_scheduled is True
    skipped = [r for r in caplog.records if 'less than 5 minutes after the last run' in r.message]
    assert len(skipped) == 1


def test_a_change_during_a_refresh_is_not_lost(db_session, sessions):
    _create(db_session, trigger_type=TriggerType.MANUAL, schedule=None, name='Manual')
    scheduler = _scheduler(sessions)
    original = WorkflowScheduler._schedule_of

    def change_meanwhile(row):
        # Another request commits a scheduled workflow after the query read its rows.
        scheduler.invalidate()
        return original(row)

    with patch.object(WorkflowScheduler, '_schedule_of', staticmethod(change_meanwhile)):
        scheduler.run_once(_at())
    assert scheduler._has_scheduled is None
    opened = sessions.opened
    scheduler.run_once(_at(minute=1))
    assert sessions.opened == opened + 1
    assert scheduler._has_scheduled is False


def test_an_idle_scheduler_rechecks_slowly_for_other_instances_schedules(
        db_session, sessions):
    scheduler = WorkflowScheduler(sessions, idle_recheck_seconds=900, instance_id='idle')
    scheduler.run_once(_at(minute=0))
    assert sessions.opened == 1 and scheduler._has_scheduled is False
    # Created through another instance: no notification reaches this one.
    with patch('src.controller.workflows_manager._schedules_changed'):
        workflow = _create(db_session, changed=_at(minute=1))
    for minute in (1, 5, 14):
        scheduler.run_once(_at(minute=minute))
    assert sessions.opened == 1
    scheduler.run_once(_at(minute=15, second=1))  # 15 minutes after the last look
    assert scheduler._has_scheduled is True
    assert len(_executions(db_session, workflow.id)) == 1


def test_the_opt_in_recheck_is_a_deadline_of_the_sleep(db_session, sessions):
    scheduler = WorkflowScheduler(sessions, idle_recheck_seconds=900, instance_id='idle')
    assert scheduler.run_once(_at(minute=0)) == pytest.approx(900.5)
    # The saving instance re-reads at once; the re-check counts from that look.
    _create(db_session, schedule='0 0 * * * ?', name='Hourly', changed=_at(minute=1))
    assert scheduler.run_once(_at(minute=1)) == pytest.approx(900.5)  # before 11:00
    _create(db_session, name='Every five', changed=_at(minute=2))
    assert scheduler.run_once(_at(minute=2)) == pytest.approx(3 * 60 + 0.5)  # 10:05


def test_the_idle_recheck_is_off_by_default(db_session, sessions):
    from src.common.config import Settings

    assert Settings.model_fields['WORKFLOW_SCHEDULER_IDLE_RECHECK_SECONDS'].default == 0
    scheduler = WorkflowScheduler(sessions, instance_id='default')
    scheduler.run_once(_at(minute=0))
    with patch('src.controller.workflows_manager._schedules_changed'):
        _create(db_session, changed=_at(minute=1))
    for day in (5, 6, 7):
        scheduler.run_once(_at(day=day, hour=23))
    assert sessions.opened == 1 and scheduler._has_scheduled is False


def test_the_idle_recheck_can_be_turned_off(db_session, sessions):
    scheduler = WorkflowScheduler(sessions, idle_recheck_seconds=0, instance_id='off')
    scheduler.run_once(_at(minute=0))
    with patch('src.controller.workflows_manager._schedules_changed'):
        _create(db_session, changed=_at(minute=1))
    scheduler.run_once(_at(day=6))
    assert sessions.opened == 1 and scheduler._has_scheduled is False


def test_a_failing_run_records_an_error_outcome(db_session, sessions):
    workflow = _create(db_session, changed=_at(hour=9, minute=58))
    scheduler = _scheduler(sessions)
    with patch.object(WorkflowExecutor, 'execute_workflow', side_effect=RuntimeError('boom')):
        scheduler.run_once(_at(minute=0, second=1))
        scheduler.run_once(_at(minute=0, second=30))
    [claim] = _claims(db_session, workflow.id)
    assert claim.outcome == {'status': 'error', 'coalesced_slots': 1}
    assert claim.execution_id is None
    assert _executions(db_session, workflow.id) == []


def test_the_postgres_claim_is_insert_on_conflict_do_nothing():
    from sqlalchemy.dialects import postgresql

    statement = scheduler_claims_repo.claim_statement(
        'postgresql', task_key='workflow:x', slot=_at(), claimed_by='a',
    )
    sql = ' '.join(str(statement.compile(dialect=postgresql.dialect())).split())
    assert sql.startswith('INSERT INTO scheduler_claims')
    assert sql.endswith('ON CONFLICT (task_key, slot) DO NOTHING')


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


def test_the_thread_starts_and_stops(sessions, monkeypatch):
    from src.common import database
    from src.controller.workflow_scheduler import note_database_activity

    monkeypatch.setattr(database, '_request_db_use_listeners', [])
    scheduler = _scheduler(sessions)
    scheduler.start()
    assert scheduler._thread.is_alive()
    assert database._request_db_use_listeners == [note_database_activity]
    scheduler.stop()
    assert not scheduler._thread.is_alive()


# --- changes made through another instance -----------------------------------------

class _Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


def _created_elsewhere(db, **kwargs):
    """A workflow saved through another instance: no notification reaches this one."""
    with patch('src.controller.workflows_manager._schedules_changed'):
        return _create(db, **kwargs)


def test_database_activity_makes_another_instance_pick_up_a_new_schedule(
        db_session, sessions):
    from src.controller.workflow_scheduler import note_database_activity

    clock = _Clock(_at(minute=0))
    scheduler = WorkflowScheduler(sessions, clock=clock, instance_id='other')
    scheduler.run_once(clock.now)
    assert sessions.opened == 1 and scheduler._has_scheduled is False
    clock.now = _at(minute=2)
    workflow = _created_elsewhere(db_session, changed=_at(minute=1))
    scheduler.run_once(clock.now)
    assert sessions.opened == 1  # no request yet: nothing read

    note_database_activity()  # a request of this instance uses the database
    assert scheduler._wake.is_set()
    assert scheduler.run_once(clock.now) == pytest.approx(3 * 60 + 0.5)  # until 10:05
    assert scheduler._has_scheduled is True
    assert sessions.opened == 3  # the small check, then the re-read
    scheduler.run_once(_at(minute=5, second=1))
    assert len(_executions(db_session, workflow.id)) == 1


def test_the_change_check_is_rate_limited_and_cheap_without_changes(db_session, sessions):
    clock = _Clock(_at(minute=0))
    scheduler = WorkflowScheduler(sessions, clock=clock, change_check_seconds=60,
                                  instance_id='other')
    scheduler.run_once(clock.now)
    for second in (10, 30, 59):  # within a minute of the last look: ignored
        clock.now = _at(minute=0, second=second)
        scheduler.note_database_activity()
        scheduler.run_once(clock.now)
    assert sessions.opened == 1
    clock.now = _at(minute=1)
    scheduler.note_database_activity()
    scheduler.run_once(clock.now)
    assert sessions.opened == 2  # one check; nothing changed, so no re-read


@pytest.mark.parametrize('change', ['update', 'delete'])
def test_the_change_check_sees_edits_and_deletes_made_elsewhere(
        db_session, sessions, change):
    workflow = _create(db_session)
    clock = _Clock(_at(minute=1))
    scheduler = WorkflowScheduler(sessions, clock=clock, instance_id='other')
    scheduler.run_once(clock.now)
    assert scheduler._has_scheduled is True
    query = db_session.query(ProcessWorkflowDb).filter(ProcessWorkflowDb.id == workflow.id)
    if change == 'update':
        query.update({'trigger_config': '{"type": "manual"}', 'updated_at': _at(minute=2)},
                     synchronize_session=False)
    else:
        query.delete(synchronize_session=False)
    db_session.commit()
    clock.now = _at(minute=3)
    scheduler.note_database_activity()
    assert scheduler.run_once(clock.now) is None
    assert scheduler._has_scheduled is False


def test_a_request_session_reports_its_first_database_use(db_session, monkeypatch):
    from sqlalchemy import text

    from src.common import database

    calls = []
    monkeypatch.setattr(database, '_request_db_use_listeners', [])
    monkeypatch.setattr(database, '_SessionLocal',
                        sessionmaker(bind=db_session.get_bind(), autoflush=False,
                                     join_transaction_mode='create_savepoint'))
    database.add_request_db_use_listener(lambda: calls.append(1))

    unused = database.get_db()
    next(unused)
    unused.close()
    assert calls == []

    used = database.get_db()
    db = next(used)
    db.execute(text('SELECT 1'))
    db.commit()
    db.execute(text('SELECT 1'))
    used.close()
    assert calls == [1]  # once per request session


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
    ('0 0 99 * * ?', None, 'cron_invalid_field'),
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


@pytest.mark.parametrize('state', ['deleted', 'inactive'])
def test_a_workflow_gone_after_the_claim_is_skipped(db_session, sessions, state):
    # Deleted or turned off between the re-read and the run (e.g. through another
    # instance): the claim is kept as skipped and nothing runs.
    workflow = _create(db_session, changed=_at(hour=9, minute=58))
    original = WorkflowsManager.get_workflow

    def reread(self, workflow_id):
        if state == 'deleted':
            return None
        return original(self, workflow_id).model_copy(update={'is_active': False})

    with patch.object(WorkflowsManager, 'get_workflow', reread):
        _scheduler(sessions).run_once(_at(minute=0, second=1))
    [claim] = _claims(db_session, workflow.id)
    assert claim.outcome == {'status': 'skipped', 'coalesced_slots': 1}
    assert claim.execution_id is None
    assert _executions(db_session, workflow.id) == []
