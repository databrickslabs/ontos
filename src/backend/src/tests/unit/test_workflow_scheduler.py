"""The workflow scheduler and the ``scheduled`` trigger's validation (#941)."""
import os

os.environ['TESTING'] = 'true'

from concurrent.futures import Executor, Future
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
        {'updated_at': changed, 'created_at': changed, 'schedule_changed_at': changed},
        synchronize_session=False)
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


class _Inline(Executor):
    """Runs each submitted run at once, so a test sees its outcome after run_once."""

    def submit(self, fn, *args, **kwargs):
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as e:  # noqa: BLE001 - handed to the future
            future.set_exception(e)
        return future


def _scheduler(sessions, name='a', **kwargs):
    kwargs.setdefault('run_executor', _Inline())
    return WorkflowScheduler(sessions, instance_id=name, **kwargs)


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
    # Look again, then the 10:30 slot: re-read the definitions, claim, then run
    # (on the pool, with its own session).
    assert sessions.opened == 5


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
        {'schedule_changed_at': _at(minute=3)}, synchronize_session=False)
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


def test_a_stored_schedule_without_upcoming_runs_is_logged_once(db_session, sessions, caplog):
    # Saved through YAML or an older API client: the save check would refuse it.
    workflow = _create(db_session, schedule='0 0 0 * * ? 2020', name='Past year')
    scheduler = _scheduler(sessions)
    with caplog.at_level('WARNING', logger='src.controller.workflow_scheduler'):
        scheduler.run_once(_at(minute=0, second=1))
        scheduler.invalidate()
        scheduler.run_once(_at(minute=1))
    logged = [r for r in caplog.records if 'no upcoming run' in r.getMessage()]
    assert len(logged) == 1 and workflow.id in logged[0].getMessage()
    assert _executions(db_session, workflow.id) == []


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
    scheduler = _scheduler(sessions, 'idle', idle_recheck_seconds=900)
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
    scheduler = _scheduler(sessions, 'idle', idle_recheck_seconds=900)
    assert scheduler.run_once(_at(minute=0)) == pytest.approx(900.5)
    # The saving instance re-reads at once; the re-check counts from that look.
    _create(db_session, schedule='0 0 * * * ?', name='Hourly', changed=_at(minute=1))
    assert scheduler.run_once(_at(minute=1)) == pytest.approx(900.5)  # before 11:00
    _create(db_session, name='Every five', changed=_at(minute=2))
    assert scheduler.run_once(_at(minute=2)) == pytest.approx(3 * 60 + 0.5)  # 10:05


def test_the_idle_recheck_is_off_by_default(db_session, sessions):
    from src.common.config import Settings

    assert Settings.model_fields['WORKFLOW_SCHEDULER_IDLE_RECHECK_SECONDS'].default == 0
    scheduler = _scheduler(sessions, 'default')
    scheduler.run_once(_at(minute=0))
    with patch('src.controller.workflows_manager._schedules_changed'):
        _create(db_session, changed=_at(minute=1))
    for day in (5, 6, 7):
        scheduler.run_once(_at(day=day, hour=23))
    assert sessions.opened == 1 and scheduler._has_scheduled is False


def test_the_idle_recheck_can_be_turned_off(db_session, sessions):
    scheduler = _scheduler(sessions, 'off', idle_recheck_seconds=0)
    scheduler.run_once(_at(minute=0))
    with patch('src.controller.workflows_manager._schedules_changed'):
        _create(db_session, changed=_at(minute=1))
    scheduler.run_once(_at(day=6))
    assert sessions.opened == 1 and scheduler._has_scheduled is False


def test_an_unrelated_edit_after_a_slot_does_not_drop_it(db_session, sessions):
    from src.models.process_workflows import ProcessWorkflowUpdate

    workflow = _create(db_session, changed=_at(hour=9, minute=58))
    scheduler = _scheduler(sessions)
    scheduler.run_once(_at(minute=0, second=1))  # 10:00 runs
    # Renamed at 10:05:30, before the 10:05 slot fired (a late wake-up, a retry).
    WorkflowsManager(db_session).update_workflow(
        workflow.id, ProcessWorkflowUpdate(name='Renamed'))
    db_session.query(ProcessWorkflowDb).filter(ProcessWorkflowDb.id == workflow.id).update(
        {'updated_at': _at(minute=5, second=30)}, synchronize_session=False)
    db_session.commit()
    scheduler.run_once(_at(minute=5, second=40))
    assert len(_executions(db_session, workflow.id)) == 2


def test_a_restart_after_an_unrelated_edit_still_runs_the_due_slot(db_session, sessions):
    """Down 05:50-06:10, renamed at 06:01: the 06:00 slot still runs after the restart."""
    from src.models.process_workflows import ProcessWorkflowUpdate

    workflow = _create(db_session, schedule='0 0 6 * * ?', changed=_at(day=4, hour=12))
    WorkflowsManager(db_session).update_workflow(
        workflow.id, ProcessWorkflowUpdate(name='Renamed'))
    db_session.query(ProcessWorkflowDb).filter(ProcessWorkflowDb.id == workflow.id).update(
        {'updated_at': _at(hour=6, minute=1)}, synchronize_session=False)
    db_session.commit()
    _scheduler(sessions, 'restarted').run_once(_at(hour=6, minute=10))  # empty cache
    [claim] = _claims(db_session, workflow.id)
    assert claim.slot.replace(tzinfo=UTC) == _at(hour=6)


@pytest.mark.parametrize('update, moves', [
    ({'name': 'Renamed'}, False),
    ({'description': 'x'}, False),
    ({'trigger': {'schedule': '0 0/15 * * * ?'}}, True),
    ({'trigger': {'timezone': 'Europe/Berlin'}}, True),
    ({'trigger': {'type': TriggerType.MANUAL, 'schedule': None}}, True),
    ({'is_active': False}, True),
])
def test_only_a_schedule_change_moves_schedule_changed_at(db_session, update, moves):
    from src.models.process_workflows import ProcessWorkflowUpdate

    workflow = _create(db_session, tz='UTC')
    if 'trigger' in update:
        stored = WorkflowsManager(db_session).get_workflow(workflow.id).trigger
        update = {'trigger': stored.model_copy(update=update['trigger'])}
    WorkflowsManager(db_session).update_workflow(workflow.id, ProcessWorkflowUpdate(**update))
    row = db_session.get(ProcessWorkflowDb, workflow.id)
    db_session.refresh(row)
    assert (row.schedule_changed_at.replace(tzinfo=UTC) != CHANGED) is moves


def test_toggling_a_workflow_moves_schedule_changed_at(db_session):
    workflow = _create(db_session)
    WorkflowsManager(db_session).toggle_active(workflow.id, False)
    row = db_session.get(ProcessWorkflowDb, workflow.id)
    db_session.refresh(row)
    assert row.schedule_changed_at.replace(tzinfo=UTC) > CHANGED


@pytest.mark.parametrize('change', ['cron', 'toggle'])
def test_a_schedule_change_after_a_slot_still_moves_the_cutoff(db_session, sessions, change):
    workflow = _create(db_session, changed=_at(hour=9, minute=58))
    scheduler = _scheduler(sessions)
    scheduler.run_once(_at(minute=0, second=1))
    query = db_session.query(ProcessWorkflowDb).filter(ProcessWorkflowDb.id == workflow.id)
    if change == 'cron':
        query.update({'trigger_config': '{"type": "scheduled", "schedule": "0 0/15 * * * ?"}',
                      'schedule_changed_at': _at(minute=5, second=30)},
                     synchronize_session=False)
    else:
        query.update({'is_active': False}, synchronize_session=False)
        db_session.commit()
        scheduler.invalidate()
        scheduler.run_once(_at(minute=5, second=20))  # sees it off
        query.update({'is_active': True, 'schedule_changed_at': _at(minute=5, second=30)},
                     synchronize_session=False)
    db_session.commit()
    scheduler.invalidate()
    scheduler.run_once(_at(minute=5, second=40))
    assert len(_executions(db_session, workflow.id)) == 1  # 10:05 isn't run


def test_a_failure_before_the_claim_retries_the_slot_soon(db_session, sessions):
    from sqlalchemy.exc import OperationalError

    from src.controller.workflow_scheduler import ERROR_RETRY_SECONDS

    workflow = _create(db_session, schedule='0 0 * * * ?', changed=_at(hour=9, minute=58))
    scheduler = _scheduler(sessions)
    down = OperationalError('SELECT', {}, Exception('connection refused'))
    with patch.object(scheduler_claims_repo, 'latest_slot', side_effect=down):
        assert scheduler.run_once(_at(minute=0, second=1)) == ERROR_RETRY_SECONDS
    assert _claims(db_session, workflow.id) == []
    # The next pass runs the same slot once; no retry is pending any more.
    assert scheduler.run_once(_at(minute=1, second=1)) == pytest.approx(59 * 60 - 0.5)
    assert len(_executions(db_session, workflow.id)) == 1
    assert len(_claims(db_session, workflow.id)) == 1


def test_the_loop_waits_the_retry_delay_after_a_failed_pass_and_goes_on(sessions):
    from src.controller.workflow_scheduler import ERROR_RETRY_SECONDS

    scheduler = _scheduler(sessions)
    waits = []
    passes = iter([RuntimeError('database down'), 42.0, None])

    def run_once():
        item = next(passes)
        if isinstance(item, Exception):
            raise item
        if item is None:
            scheduler._stop.set()
        return item

    class _Wake:
        def clear(self):
            pass

        def set(self):
            pass

        def wait(self, timeout=None):
            waits.append(timeout)

    scheduler.run_once = run_once
    scheduler._wake = _Wake()
    scheduler._loop()
    assert waits == [ERROR_RETRY_SECONDS, 42.0]


class _Deferred(Executor):
    """Keeps the submitted runs until ``finish()``: runs still in progress."""

    def __init__(self):
        self.pending = []

    def submit(self, fn, *args, **kwargs):
        future = Future()
        self.pending.append((future, fn, args, kwargs))
        return future

    def finish(self, index=None):
        """End every run in progress, or only the one at ``index``."""
        if index is None:
            pending, self.pending = self.pending, []
        else:
            pending = [self.pending.pop(index)]
        for future, fn, args, kwargs in pending:
            future.set_result(fn(*args, **kwargs))

    def workflow_id(self, index):
        return self.pending[index][2][0]


def test_a_run_in_progress_holds_up_neither_the_pass_nor_other_workflows(db_session, sessions):
    slow = _create(db_session, name='Slow', changed=_at(hour=9, minute=58))
    other = _create(db_session, name='Other', changed=_at(hour=9, minute=58))
    pool = _Deferred()
    scheduler = _scheduler(sessions, run_executor=pool)
    scheduler.run_once(_at(minute=0, second=1))
    # Both 10:00 slots are claimed and handed to the pool in the same pass.
    assert len(pool.pending) == 2
    assert len(_claims(db_session, slow.id)) == len(_claims(db_session, other.id)) == 1
    still_running = slow if pool.workflow_id(0) == slow.id else other
    done = other if still_running is slow else slow
    pool.finish(1)
    # The first run is still going at 10:05: only the other workflow's slot is claimed.
    scheduler.run_once(_at(minute=5, second=1))
    assert len(_claims(db_session, still_running.id)) == 1
    assert len(_claims(db_session, done.id)) == 2
    # Its run ends (waking the thread): the 10:05 slot it waited for runs then.
    pool.finish()
    assert scheduler._wake.is_set()
    scheduler.run_once(_at(minute=5, second=50))
    pool.finish()
    assert len(_claims(db_session, still_running.id)) == 2
    assert len(_executions(db_session, still_running.id)) == 2


def test_the_sleep_counts_from_the_time_after_the_claims(db_session, sessions):
    _create(db_session, changed=_at(hour=9, minute=58))
    clock = _Clock(_at(minute=0, second=1))
    scheduler = _scheduler(sessions, clock=clock)
    original = scheduler_claims_repo.claim

    def slow_claim(*args, **kwargs):
        clock.now = _at(minute=0, second=41)  # the claims took 40 seconds
        return original(*args, **kwargs)

    with patch.object(scheduler_claims_repo, 'claim', side_effect=slow_claim):
        delay = scheduler.run_once()
    assert delay == pytest.approx(4 * 60 + 19 + 0.5)  # until 10:05, from 10:00:41


def test_a_crash_after_the_claim_leaves_the_slot_claimed_and_not_run_again(
        db_session, sessions):
    """At most once: the claim is committed before the run, which never ended."""
    workflow = _create(db_session, changed=_at(hour=9, minute=58))
    _scheduler(sessions, 'crashed', run_executor=_Deferred()).run_once(
        _at(minute=0, second=1))  # claimed; the process dies before the run
    _scheduler(sessions, 'restarted').run_once(_at(minute=0, second=40))
    [claim] = _claims(db_session, workflow.id)
    assert claim.claimed_by == 'crashed'
    assert claim.outcome == {'status': 'claimed', 'coalesced_slots': 1}
    assert _executions(db_session, workflow.id) == []
    _scheduler(sessions, 'restarted').run_once(_at(minute=5, second=1))
    assert len(_executions(db_session, workflow.id)) == 1  # the next slot runs


def test_stopping_waits_for_runs_in_progress_and_records_the_unstarted_ones(
        db_session, sessions):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    first = _create(db_session, name='First', changed=_at(hour=9, minute=58))
    second = _create(db_session, name='Second', changed=_at(hour=9, minute=58))
    release, running = threading.Event(), threading.Event()
    started = []

    def run(self, workflow_id, slot, coalesced, **_kwargs):
        started.append(workflow_id)
        running.set()
        release.wait(timeout=10)

    pool = ThreadPoolExecutor(max_workers=1)  # the second run queues behind the first
    scheduler = _scheduler(sessions, run_executor=pool)
    with patch.object(WorkflowScheduler, '_run', run):
        scheduler.run_once(_at(minute=0, second=1))
        assert running.wait(timeout=5)
        threading.Timer(0.3, release.set).start()
        scheduler.drain(timeout=5)
    assert len(started) == 1 and not scheduler._in_flight
    [queued] = {first.id, second.id} - set(started)
    [claim] = _claims(db_session, queued)
    assert claim.outcome == {'status': 'not_started', 'coalesced_slots': 1}


def test_the_drain_gives_up_after_its_timeout(sessions, caplog):
    scheduler = _scheduler(sessions)
    scheduler._in_flight['wf'] = Future()  # a run that doesn't end
    with caplog.at_level('WARNING', logger='src.controller.workflow_scheduler'):
        scheduler.drain(timeout=0.05)
    assert any('still in progress' in r.message for r in caplog.records)


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
        {'schedule_changed_at': _at(minute=10)}, synchronize_session=False)
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


@pytest.mark.parametrize('cron, tz, first, repeat', [
    # 01:30 New York and 02:30 Berlin happen twice on the fall-back night.
    ('0 30 1 * * ?', 'America/New_York', datetime(2026, 11, 1, 5, 30, tzinfo=UTC),
     datetime(2026, 11, 1, 6, 30, tzinfo=UTC)),
    ('0 30 2 * * ?', 'Europe/Berlin', datetime(2026, 10, 25, 0, 30, tzinfo=UTC),
     datetime(2026, 10, 25, 1, 30, tzinfo=UTC)),
])
def test_a_daily_run_fires_once_on_the_dst_fall_back_night(
        db_session, sessions, cron, tz, first, repeat):
    from datetime import timedelta

    workflow = _create(db_session, schedule=cron, tz=tz, changed=first - timedelta(days=1))
    scheduler = _scheduler(sessions)
    scheduler.run_once(first + timedelta(seconds=1))
    scheduler.run_once(repeat + timedelta(seconds=1))
    scheduler.run_once(repeat + timedelta(minutes=30))
    assert [c.slot.replace(tzinfo=UTC) for c in _claims(db_session, workflow.id)] == [first]
    assert len(_executions(db_session, workflow.id)) == 1


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
    scheduler = _scheduler(sessions, 'other', clock=clock)
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
    scheduler = _scheduler(sessions, 'other', clock=clock, change_check_seconds=60)
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
    scheduler = _scheduler(sessions, 'other', clock=clock)
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


# --- follow-ups of #1310: shutdown, late runs, claims, threads, connections --------

def test_a_slot_claimed_while_the_scheduler_stops_is_not_started(db_session, sessions):
    # A pass still claiming (e.g. a slow Lakebase) when stop() drains: the claim is
    # recorded as not_started, and nothing is handed to the pool during the exit.
    workflow = _create(db_session, changed=_at(hour=9, minute=58))
    pool = _Deferred()
    scheduler = _scheduler(sessions, run_executor=pool)
    original = scheduler_claims_repo.claim

    def claim_while_stopping(*args, **kwargs):
        claimed = original(*args, **kwargs)
        scheduler.drain(timeout=0)
        return claimed

    with patch.object(scheduler_claims_repo, 'claim', side_effect=claim_while_stopping):
        scheduler.run_once(_at(minute=0, second=1))
    assert pool.pending == []
    [claim] = _claims(db_session, workflow.id)
    assert claim.outcome == {'status': 'not_started', 'coalesced_slots': 1}
    assert _executions(db_session, workflow.id) == []


def test_a_drained_scheduler_starts_again_with_a_new_pool(db_session, sessions, monkeypatch):
    from src.common import database

    monkeypatch.setattr(database, '_request_db_use_listeners', [])
    workflow = _create(db_session, changed=_at(hour=9, minute=58))
    scheduler = _scheduler(sessions, run_executor=None)
    scheduler.run_once(_at(minute=0, second=1))
    assert scheduler.wait_for_runs(timeout=10)
    scheduler.drain(timeout=1)
    assert scheduler._pool is None
    with patch.object(WorkflowScheduler, '_loop', lambda self: None):
        scheduler.start()
    scheduler.run_once(_at(minute=5, second=1))
    assert scheduler.wait_for_runs(timeout=10)
    assert [c.outcome['status'] for c in _claims(db_session, workflow.id)] == [
        'succeeded', 'succeeded']


def test_runs_go_to_daemon_threads(db_session, sessions):
    import threading

    _create(db_session, changed=_at(hour=9, minute=58))
    daemon = []

    def run(self, *args, **kwargs):
        daemon.append(threading.current_thread().daemon)

    scheduler = _scheduler(sessions, run_executor=None)
    with patch.object(WorkflowScheduler, '_run', run):
        scheduler.run_once(_at(minute=0, second=1))
        assert scheduler.wait_for_runs(timeout=10)
    scheduler.drain(timeout=1)
    assert daemon == [True]


@pytest.mark.parametrize('waited, status', [(60, 'succeeded'), (5 * 60, 'skipped')])
def test_a_run_waiting_for_a_worker_past_its_next_slot_is_not_started(
        db_session, sessions, waited, status):
    from src.controller import workflow_scheduler

    workflow = _create(db_session, changed=_at(hour=9, minute=58))
    pool = _Deferred()
    scheduler = _scheduler(sessions, run_executor=pool)
    real = workflow_scheduler.time.monotonic
    started = real()
    with patch.object(workflow_scheduler.time, 'monotonic', side_effect=lambda: started):
        scheduler.run_once(_at(minute=0, second=1))  # 4:59 before the 10:05 slot
    with patch.object(workflow_scheduler.time, 'monotonic',
                      side_effect=lambda: started + waited):
        pool.finish()  # a worker gets free ``waited`` seconds later
    [claim] = _claims(db_session, workflow.id)
    assert claim.outcome['status'] == status
    if status == 'skipped':
        assert claim.outcome == {'status': 'skipped', 'reason': 'late', 'coalesced_slots': 1}
        assert _executions(db_session, workflow.id) == []
    else:
        assert len(_executions(db_session, workflow.id)) == 1


def test_the_start_budget_is_capped_at_24_hours():
    from src.controller.workflow_scheduler import _Schedule

    weekly = _Schedule(workflow_id='w', cron='0 0 10 ? * MON', tz=None, changed_at=CHANGED)
    slot = _at(day=5, hour=10)  # a Monday
    assert WorkflowScheduler._start_budget(weekly, slot, slot) == 24 * 3600
    every_5 = _Schedule(workflow_id='w', cron=EVERY_5, tz=None, changed_at=CHANGED)
    assert WorkflowScheduler._start_budget(every_5, slot, slot + _seconds(60)) == 4 * 60


def _seconds(n):
    from datetime import timedelta

    return timedelta(seconds=n)


def _old_claim(db, workflow_id, slot):
    db.add(SchedulerClaimDb(task_key=task_key(workflow_id), slot=slot, claimed_by='old',
                            outcome={'status': 'succeeded', 'coalesced_slots': 1}))
    db.commit()


def test_old_claims_are_pruned_once_a_day_keeping_each_latest(db_session, sessions):
    from datetime import timedelta

    workflow = _create(db_session, changed=_at(hour=9, minute=58))
    other = _create(db_session, name='Other', active=False, changed=_at(hour=9, minute=58))
    now = _at(minute=0, second=1)
    _old_claim(db_session, workflow.id, now - timedelta(days=40))
    _old_claim(db_session, workflow.id, now - timedelta(days=31))
    _old_claim(db_session, workflow.id, now - timedelta(days=29))
    _old_claim(db_session, other.id, now - timedelta(days=60))  # its latest: kept
    scheduler = _scheduler(sessions)
    scheduler.run_once(now)
    db_session.expire_all()
    assert sorted(c.slot.replace(tzinfo=UTC) for c in _claims(db_session, workflow.id)) == [
        now - timedelta(days=29), _at(minute=0)]
    assert len(_claims(db_session, other.id)) == 1
    # Within a day no other prune runs, even with old claims.
    _old_claim(db_session, workflow.id, now - timedelta(days=50))
    scheduler.run_once(_at(minute=5, second=1))
    db_session.expire_all()
    assert len(_claims(db_session, workflow.id)) == 4


def test_a_failing_prune_does_not_stop_the_run(db_session, sessions):
    workflow = _create(db_session, changed=_at(hour=9, minute=58))
    with patch.object(scheduler_claims_repo, 'prune', side_effect=RuntimeError('locked')):
        _scheduler(sessions).run_once(_at(minute=0, second=1))
    [claim] = _claims(db_session, workflow.id)
    assert claim.outcome['status'] == 'succeeded'


def test_the_app_scheduler_uses_a_dedicated_engine_and_disposes_it(monkeypatch):
    from src.common import database

    monkeypatch.setattr(database, '_request_db_use_listeners', [])
    engine = type('Engine', (), {'disposed': False,
                                 'dispose': lambda self: setattr(self, 'disposed', True)})()
    factory = object()
    calls = []

    def create(pool_size, name):
        calls.append((pool_size, name))
        return factory, engine

    monkeypatch.setattr(database, 'create_dedicated_session_factory', create)
    scheduler = WorkflowScheduler(max_workers=3, run_executor=_Inline())
    with patch.object(WorkflowScheduler, '_loop', lambda self: self._stop.wait(5)):
        scheduler.start()
        assert calls == [(4, 'workflow_scheduler')]  # 3 runs + the scheduler thread
        assert scheduler._session_factory is factory
        scheduler.stop()
    assert engine.disposed and scheduler._session_factory is None


@pytest.mark.parametrize('failure', [
    RuntimeError('could not connect to host=db.example password=hunter2'),
    None,
])
def test_the_scheduler_warns_when_it_falls_back_to_the_app_pool(monkeypatch, caplog, failure):
    from src.common import database

    def create(pool_size, name):
        if failure is not None:
            raise failure
        return None

    monkeypatch.setattr(database, 'create_dedicated_session_factory', create)
    scheduler = WorkflowScheduler(max_workers=3, run_executor=_Inline())
    with caplog.at_level('WARNING', logger='src.controller.workflow_scheduler'):
        scheduler._use_dedicated_engine()
    warned = [r for r in caplog.records
              if r.levelname == 'WARNING' and 'connection pool' in r.getMessage()]
    assert len(warned) == 1
    assert 'hunter2' not in warned[0].getMessage()
    assert scheduler._session_factory is None and scheduler._own_engine is None


def _fake_settings(env='LOCAL', schema=None):
    from types import SimpleNamespace

    return SimpleNamespace(DB_ECHO=False, DB_POOL_TIMEOUT=7, DB_POOL_RECYCLE=3600, ENV=env,
                           DB_USE_PASSWORD_AUTH=False, PGSCHEMA=schema)


@pytest.mark.parametrize('env, token_hook', [('LOCAL', False), ('PROD', True)])
def test_the_dedicated_engine_has_its_own_small_pool_and_the_same_hooks(
        monkeypatch, tmp_path, env, token_hook):
    from sqlalchemy import create_engine, text

    from src.common import database

    app_engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setattr(database, '_engine', app_engine)
    monkeypatch.setattr(database, '_SessionLocal', sessionmaker(bind=app_engine))
    monkeypatch.setattr(database, 'get_settings', lambda: _fake_settings(env))
    hooked = []
    listens_for = database.event.listens_for

    def spy(target, name, *args, **kwargs):
        hooked.append((target, name))
        return listens_for(target, name, *args, **kwargs)

    monkeypatch.setattr(database.event, 'listens_for', spy)
    factory, dedicated = database.create_dedicated_session_factory(5, 'test')
    try:
        assert dedicated is not app_engine and dedicated.url == app_engine.url
        assert dedicated.pool.size() == 5 and dedicated.pool._max_overflow == 0
        assert dedicated.pool.timeout() == 7
        # The Lakebase OAuth token goes into its new connections too.
        assert ((dedicated, 'do_connect') in hooked) is token_hook
        with factory() as db:
            assert db.execute(text('select 1')).scalar() == 1
    finally:
        dedicated.dispose()
        app_engine.dispose()


def test_no_dedicated_engine_when_the_session_factory_was_replaced(monkeypatch):
    from sqlalchemy import create_engine

    from src.common import database

    app_engine = create_engine('sqlite://')
    monkeypatch.setattr(database, '_engine', app_engine)
    monkeypatch.setattr(database, '_SessionLocal', sessionmaker(bind=create_engine('sqlite://')))
    assert database.create_dedicated_session_factory(5, 'test') is None
    monkeypatch.setattr(database, '_engine', None)
    assert database.create_dedicated_session_factory(5, 'test') is None


@pytest.mark.parametrize('previous_minutes', [2, None])  # a short gap, and a normal claim
def test_fire_returns_its_connection_on_every_path(tmp_path, previous_minutes):
    """The dedicated pool is small and has no overflow: a leaked session blocks the next."""
    from datetime import timedelta

    from sqlalchemy import create_engine
    from sqlalchemy.pool import QueuePool

    from src.common.database import Base
    from src.controller.workflow_scheduler import _Schedule

    engine = create_engine(f"sqlite:///{tmp_path / 'pool.db'}", poolclass=QueuePool,
                           pool_size=2, max_overflow=0, pool_timeout=1)
    Base.metadata.create_all(engine, tables=[Base.metadata.tables['scheduler_claims']])
    scheduler = WorkflowScheduler(sessionmaker(bind=engine), instance_id='a',
                                  run_executor=_Deferred())
    schedule = _Schedule(workflow_id='w', cron=EVERY_5, tz=None, changed_at=CHANGED)
    try:
        for n in range(3):
            slot = _at(minute=5 * (n + 1))
            if previous_minutes is not None:
                with sessionmaker(bind=engine)() as db:
                    db.add(SchedulerClaimDb(task_key=task_key('w'),
                                            slot=slot - timedelta(minutes=previous_minutes),
                                            claimed_by='old'))
                    db.commit()
            assert scheduler._fire(schedule, slot, slot) is True
            assert engine.pool.checkedout() == 0
    finally:
        engine.dispose()


def test_start_after_a_stop_whose_thread_outlived_the_join(sessions, monkeypatch):
    import threading

    from src.common import database

    monkeypatch.setattr(database, '_request_db_use_listeners', [])
    release, in_pass = threading.Event(), threading.Event()
    passes = []

    def slow_pass(self, now=None):
        passes.append(threading.current_thread())
        if len(passes) == 1:  # the first pass is slow (a Lakebase cold start)
            in_pass.set()
            release.wait(timeout=10)
        return None

    scheduler = _scheduler(sessions)
    scheduler._stop_join_seconds = 0.05
    with patch.object(WorkflowScheduler, 'run_once', slow_pass):
        scheduler.start()
        old = scheduler._thread
        assert in_pass.wait(timeout=5)
        scheduler.stop()
        assert old.is_alive()  # still in its pass after the join
        scheduler.start()
        new = scheduler._thread
        assert new is not old and new.is_alive() and scheduler._closing is False
        release.set()
        old.join(timeout=5)
        assert not old.is_alive()  # the old thread ended after its pass
        assert new.is_alive()
        scheduler._stop_join_seconds = 5
        scheduler.stop()
    assert not new.is_alive()


def test_the_drain_cancels_a_run_queued_on_the_daemon_pool(db_session, sessions):
    import threading

    first = _create(db_session, name='First', changed=_at(hour=9, minute=58))
    second = _create(db_session, name='Second', changed=_at(hour=9, minute=58))
    release, running = threading.Event(), threading.Event()
    started = []

    def run(self, workflow_id, slot, coalesced, **_kwargs):
        started.append(workflow_id)
        running.set()
        release.wait(timeout=10)

    # The app's pool (run_executor=None) with one worker: the second run queues.
    scheduler = _scheduler(sessions, run_executor=None, max_workers=1)
    with patch.object(WorkflowScheduler, '_run', run):
        scheduler.run_once(_at(minute=0, second=1))
        assert running.wait(timeout=5)
        pool = scheduler._pool
        threading.Timer(0.3, release.set).start()
        scheduler.drain(timeout=5)
        release.set()
        pool.shutdown(wait=True)  # the worker has gone through the queue
        _until(lambda: not scheduler._in_flight)
    assert len(started) == 1 and not scheduler._in_flight
    [queued] = {first.id, second.id} - set(started)
    [claim] = _claims(db_session, queued)
    assert claim.outcome == {'status': 'not_started', 'coalesced_slots': 1}


def _until(condition, timeout=2.0):
    import time

    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)


def test_a_run_raising_on_the_daemon_pool_ends_and_frees_its_workflow(db_session, sessions):
    _create(db_session, changed=_at(hour=9, minute=58))

    def run(self, *args, **kwargs):
        raise RuntimeError('boom')

    scheduler = _scheduler(sessions, run_executor=None, max_workers=1)
    with patch.object(WorkflowScheduler, '_run', run):
        scheduler.run_once(_at(minute=0, second=1))
        assert scheduler.wait_for_runs(timeout=5)
        _until(lambda: not scheduler._in_flight)  # the done callback runs right after
    assert not scheduler._runs and not scheduler._in_flight
    # The worker survived the exception: the next slot runs on it.
    ran = []
    with patch.object(WorkflowScheduler, '_run', lambda self, *a, **k: ran.append(a[0])):
        scheduler.run_once(_at(minute=5, second=1))
        assert scheduler.wait_for_runs(timeout=5)
    assert len(ran) == 1
    scheduler.drain(timeout=1)


def test_a_run_s_start_budget_does_not_include_the_claims_before_it(tmp_path):
    """The budget counts from the pass's now: slow claims earlier in the pass use it up."""
    import time

    from sqlalchemy import create_engine

    from src.common.database import Base
    from src.controller.workflow_scheduler import _Schedule

    engine = create_engine(f"sqlite:///{tmp_path / 'budget.db'}")
    Base.metadata.create_all(engine, tables=[Base.metadata.tables['scheduler_claims']])
    deferred = _Deferred()
    scheduler = WorkflowScheduler(sessionmaker(bind=engine), instance_id='a',
                                  run_executor=deferred)
    schedule = _Schedule(workflow_id='w', cron=EVERY_5, tz=None, changed_at=CHANGED)
    slot = _at(minute=5)
    try:
        scheduler._pass_started = time.monotonic() - 100  # the pass began 100 s ago
        assert scheduler._fire(schedule, slot, slot) is True
    finally:
        engine.dispose()
    start_by = deferred.pending[0][3]['start_by']
    # 5 minutes to the next slot, 100 s of them already gone
    assert 190 < start_by - time.monotonic() < 200
