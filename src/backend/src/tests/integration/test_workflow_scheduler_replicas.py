"""Several workflow schedulers on one database run each slot once (#941).

Each scheduler stands for an app instance: its own engine and connections on a
shared database, so the claim (``INSERT ... ON CONFLICT DO NOTHING``) is the only
thing that keeps two of them from running the same slot.

The ``sqlite`` variant uses a database file. The ``postgresql`` variant runs when
``SCHEDULER_TEST_PG_URL`` points at a Postgres database (it works in a throwaway
schema it drops afterwards) and is skipped otherwise::

    SCHEDULER_TEST_PG_URL=postgresql+psycopg2://user:pw@localhost:5432/db \\
        hatch -e dev run pytest src/tests/integration/test_workflow_scheduler_replicas.py
"""
import os
import threading
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.common.database import Base
from src.controller import workflow_scheduler
from src.controller.workflow_scheduler import SCHEDULER_USER, WorkflowScheduler, task_key
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

UTC = timezone.utc
_TABLES = ('process_workflows', 'workflow_steps', 'workflow_executions',
           'workflow_step_executions', 'scheduler_claims')
_PG_URL = os.environ.get('SCHEDULER_TEST_PG_URL')


def _at(minute, second=1):
    return datetime(2026, 1, 5, 10, minute, second, tzinfo=UTC)


class _Database:
    """A shared database; ``instance()`` is a new app instance's engine on it."""

    def __init__(self, url, connect_args=None):
        self._url = url
        self._connect_args = connect_args or {}
        self._engines = []

    def engine(self):
        engine = create_engine(self._url, connect_args=self._connect_args)
        self._engines.append(engine)
        return engine

    def sessions(self):
        return sessionmaker(bind=self.engine(), autoflush=False)

    def dispose(self):
        for engine in self._engines:
            engine.dispose()


@pytest.fixture(params=['sqlite', 'postgresql'])
def database(request, tmp_path):
    tables = [Base.metadata.tables[name] for name in _TABLES]
    if request.param == 'sqlite':
        shared = _Database(f"sqlite:///{tmp_path / 'scheduler.db'}",
                           {'check_same_thread': False, 'timeout': 30})
        Base.metadata.create_all(shared.engine(), tables=tables)
        yield shared
        shared.dispose()
        return
    if not _PG_URL:
        pytest.skip('SCHEDULER_TEST_PG_URL not set')
    schema = f'scheduler_it_{uuid.uuid4().hex[:8]}'
    admin = create_engine(_PG_URL)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    shared = _Database(_PG_URL, {'options': f'-csearch_path={schema}'})
    try:
        Base.metadata.create_all(shared.engine(), tables=tables)
        yield shared
    finally:
        shared.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


def _create_workflow(sessions, schedule='0 0/5 * * * ?', name='Every five minutes'):
    db = sessions()
    try:
        workflow = WorkflowsManager(db).create_workflow(ProcessWorkflowCreate(
            name=name,
            trigger=WorkflowTrigger(type=TriggerType.SCHEDULED, schedule=schedule),
            is_active=True,
            steps=[WorkflowStepCreate(step_id='done', name='Done', step_type=StepType.PASS,
                                      order=0)],
        ))
        changed = datetime(2026, 1, 5, 9, 58, tzinfo=UTC)
        db.query(ProcessWorkflowDb).filter(ProcessWorkflowDb.id == workflow.id).update(
            {'updated_at': changed, 'created_at': changed}, synchronize_session=False)
        db.commit()
        return workflow.id
    finally:
        db.close()


def _rows(sessions, workflow_id):
    db = sessions()
    try:
        executions = db.query(WorkflowExecutionDb).filter(
            WorkflowExecutionDb.workflow_id == workflow_id).all()
        claims = db.query(SchedulerClaimDb).filter(
            SchedulerClaimDb.task_key == task_key(workflow_id)
        ).order_by(SchedulerClaimDb.slot).all()
        return executions, claims
    finally:
        db.close()


def _run_together(schedulers, now):
    """``run_once(now)`` on every scheduler at the same moment, each in its own thread."""
    barrier = threading.Barrier(len(schedulers))
    errors = []

    def tick(scheduler):
        try:
            barrier.wait(timeout=10)
            scheduler.run_once(now)
        except Exception as e:  # pragma: no cover - reported below
            errors.append(e)

    threads = [threading.Thread(target=tick, args=(s,)) for s in schedulers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not errors


def test_two_schedulers_fire_a_slot_exactly_once(database):
    observer = database.sessions()
    workflow_id = _create_workflow(observer)
    schedulers = [WorkflowScheduler(database.sessions(), instance_id=f'replica-{n}')
                  for n in range(2)]

    for second in (1, 20):
        _run_together(schedulers, _at(0, second))
    executions, claims = _rows(observer, workflow_id)
    assert len(executions) == 1 and len(claims) == 1
    assert executions[0].triggered_by == SCHEDULER_USER
    assert claims[0].execution_id == executions[0].id
    assert claims[0].claimed_by in ('replica-0', 'replica-1')
    assert claims[0].outcome['coalesced_slots'] == 1

    _run_together(schedulers, _at(5))
    executions, claims = _rows(observer, workflow_id)
    assert len(executions) == 2 and len(claims) == 2


def test_a_restart_after_a_gap_fires_once_with_the_coalesced_count(database):
    observer = database.sessions()
    workflow_id = _create_workflow(observer)
    WorkflowScheduler(database.sessions(), instance_id='before').run_once(_at(0))

    # Down from 10:01 to 10:31; two instances come back at the same time.
    restarted = [WorkflowScheduler(database.sessions(), instance_id=f'after-{n}')
                 for n in range(2)]
    _run_together(restarted, _at(31))
    executions, claims = _rows(observer, workflow_id)
    assert len(executions) == 2
    assert [c.slot.astimezone(UTC) if c.slot.tzinfo else c.slot.replace(tzinfo=UTC)
            for c in claims] == [_at(0, 0), _at(30, 0)]
    assert claims[1].outcome['coalesced_slots'] == 6  # 10:05, 10:10, ... 10:30


@pytest.mark.parametrize('change', ['deactivate', 'delete'])
def test_an_inactive_or_deleted_workflow_stops_firing_on_every_instance(database, change):
    observer = database.sessions()
    workflow_id = _create_workflow(observer)
    local, other = (WorkflowScheduler(database.sessions(), instance_id=name)
                    for name in ('local', 'other'))
    _run_together([local, other], _at(0))
    # ``other`` is another process: a change made here doesn't notify it, so it only
    # notices when its next slot is due and it re-reads the definitions.
    workflow_scheduler._schedulers.discard(other)

    db = observer()
    try:
        manager = WorkflowsManager(db)
        if change == 'deactivate':
            manager.toggle_active(workflow_id, False)
        else:
            manager.delete_workflow(workflow_id)
    finally:
        db.close()
    _run_together([local, other], _at(5))
    _run_together([local, other], _at(10))

    executions, claims = _rows(observer, workflow_id)
    assert len(claims) == 1
    assert len(executions) == (1 if change == 'deactivate' else 0)
    assert local._has_scheduled is False and other._has_scheduled is False


def test_creating_a_workflow_with_an_invalid_schedule_answers_its_code(client):
    response = client.post('/api/workflows', json={
        'name': 'Too often',
        'trigger': {'type': 'scheduled', 'schedule': '0 0,2 * * * ?'},
        'steps': [{'step_id': 'done', 'name': 'Done', 'step_type': 'pass', 'order': 0}],
    })
    assert response.status_code == 400
    issues = response.json()['detail']['params']['issues']
    assert [issue['code'] for issue in issues] == ['cron_interval_too_short']
    assert issues[0]['params']['minutes'] == 5
