"""Scheduled bulk asset maturity evaluation (#1414 follow-up).

- Scheduler: a scheduled workflow with an ``evaluate_asset_maturity`` step runs the bulk
  evaluation once per slot, also with two app instances (schedulers) on one database.
  The run itself (``execute_run``) is replaced by a counting fake; the run registry,
  the step and the scheduler's claims are real.
- Permissions: saving, activating, running or retrying a workflow with the step needs
  Settings read/write, as ``POST /api/maturity-evaluations/assets``.
"""
import json
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.common.database import Base
from src.common.features import FeatureAccessLevel
from src.controller import maturity_bulk_evaluator as bulk
from src.controller.authorization_manager import AuthorizationManager
from src.controller.workflow_scheduler import WorkflowScheduler
from src.controller.workflows_manager import WorkflowsManager
from src.db_models.process_workflows import (
    ProcessWorkflowDb,
    WorkflowExecutionDb,
    WorkflowStepDb,
)
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
STEP = 'evaluate_asset_maturity'


@pytest.fixture(autouse=True)
def _no_run_in_memory():
    bulk._current = None
    yield
    bulk._current = None


# --- Scheduler ----------------------------------------------------------------------

@pytest.fixture
def runs(monkeypatch):
    """Counts the bulk runs; each one evaluates two assets and completes."""
    calls = []

    @contextmanager
    def no_store():
        yield MagicMock()

    def execute_run(run_id, scope, **kwargs):
        calls.append((run_id, scope))
        bulk._update(run_id, total=2, processed=2, evaluated=2, changed=1)
        return bulk._finish(run_id, 'completed', no_store)

    monkeypatch.setattr(bulk, 'execute_run', execute_run)
    return calls


@pytest.fixture
def sessions(tmp_path):
    engines = []

    def factory():
        engine = create_engine(f"sqlite:///{tmp_path / 'scheduler.db'}",
                               connect_args={'check_same_thread': False, 'timeout': 30})
        engines.append(engine)
        return sessionmaker(bind=engine, autoflush=False)

    first = factory()
    Base.metadata.create_all(first.kw['bind'],
                             tables=[Base.metadata.tables[name] for name in _TABLES])
    yield factory
    for engine in engines:
        engine.dispose()


def _at(minute, second=1):
    return datetime(2026, 1, 5, 10, minute, second, tzinfo=UTC)


def _scheduled_workflow(make_session):
    db = make_session()
    try:
        workflow = WorkflowsManager(db).create_workflow(ProcessWorkflowCreate(
            name='Evaluate assets every five minutes',
            trigger=WorkflowTrigger(type=TriggerType.SCHEDULED, schedule='0 0/5 * * * ?'),
            is_active=True,
            steps=[
                WorkflowStepCreate(step_id='evaluate', name='Evaluate',
                                   step_type=StepType.EVALUATE_ASSET_MATURITY,
                                   config={'catalog': 'main'}, on_pass='done', order=0),
                WorkflowStepCreate(step_id='done', name='Done', step_type=StepType.PASS,
                                   order=1),
            ],
        ))
        changed = datetime(2026, 1, 5, 9, 58, tzinfo=UTC)
        db.query(ProcessWorkflowDb).filter(ProcessWorkflowDb.id == workflow.id).update(
            {'updated_at': changed, 'created_at': changed, 'schedule_changed_at': changed},
            synchronize_session=False)
        db.commit()
        return workflow.id
    finally:
        db.close()


def _run_together(schedulers, now):
    barrier = threading.Barrier(len(schedulers))
    errors = []

    def tick(scheduler):
        try:
            barrier.wait(timeout=10)
            scheduler.run_once(now)
            assert scheduler.wait_for_runs(timeout=30)
        except Exception as e:  # pragma: no cover - reported below
            errors.append(e)

    threads = [threading.Thread(target=tick, args=(s,)) for s in schedulers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not errors


def _executions(make_session, workflow_id):
    """(status, result data of the evaluate step) of each execution of the workflow."""
    db = make_session()
    try:
        rows = db.query(WorkflowExecutionDb).filter(
            WorkflowExecutionDb.workflow_id == workflow_id).all()
        return [
            (row.status, next(json.loads(s.result_data) for s in row.step_executions
                              if s.step_key == 'evaluate'))
            for row in rows
        ]
    finally:
        db.close()


def test_a_scheduled_workflow_runs_the_bulk_evaluation_once_per_slot(sessions, runs):
    observer = sessions()
    workflow_id = _scheduled_workflow(observer)
    schedulers = [WorkflowScheduler(sessions(), instance_id=f'replica-{n}') for n in range(2)]

    for second in (1, 20):  # two passes of both instances in the 10:00 slot
        _run_together(schedulers, _at(0, second))

    assert len(runs) == 1
    assert runs[0][1].catalog == 'main'
    [(status, data)] = _executions(observer, workflow_id)
    assert status == 'succeeded'
    assert (data['total'], data['evaluated'], data['changed']) == (2, 2, 1)
    assert data['run_id'] == runs[0][0]
    assert bulk.get_latest_run()['started_by'] == 'system:scheduler'

    _run_together(schedulers, _at(5))  # the next slot runs again
    assert len(runs) == 2
    assert len(_executions(observer, workflow_id)) == 2


def test_a_slot_while_a_run_is_going_records_a_failed_step_with_its_code(sessions, runs):
    observer = sessions()
    workflow_id = _scheduled_workflow(observer)
    running = bulk.start_run(bulk.normalize_scope(None, None, None))  # e.g. from the card

    _run_together([WorkflowScheduler(sessions(), instance_id='only')], _at(0))

    assert runs == []
    [(status, data)] = _executions(observer, workflow_id)
    assert status == 'failed'
    assert data['error_code'] == 'maturity_bulk_run_in_progress'
    assert bulk.get_latest_run()['id'] == running['id']


# --- Permissions -------------------------------------------------------------------

def _permissions(monkeypatch, **levels):
    monkeypatch.setattr(
        AuthorizationManager, 'get_user_effective_permissions',
        lambda self, *args, **kwargs: {k.replace('_', '-'): v for k, v in levels.items()},
    )


WORKFLOWS_ONLY = {'settings_workflows': FeatureAccessLevel.READ_WRITE,
                  'process_workflows': FeatureAccessLevel.ADMIN}


def _body(step_type=STEP, trigger_type='scheduled', is_active=False):
    trigger = {'type': trigger_type, 'entity_types': []}
    if trigger_type == 'scheduled':
        trigger['schedule'] = '0 0 2 * * ?'
    return {
        'name': f'maturity-{uuid.uuid4().hex[:8]}', 'trigger': trigger, 'is_active': is_active,
        'steps': [{'step_id': 'evaluate', 'name': 'Evaluate', 'step_type': step_type,
                   'config': {'catalog': 'main'}, 'order': 0}],
    }


def _stored(db_session, step_type=STEP, trigger_type='manual'):
    wf_id = str(uuid.uuid4())
    now = datetime.utcnow()
    db_session.add(ProcessWorkflowDb(
        id=wf_id, name=f'stored-{wf_id[:8]}', description='',
        trigger_config=json.dumps({'type': trigger_type, 'entity_types': []}),
        scope_config=json.dumps({'type': 'all'}), is_active=False, is_default=False,
        version=1, created_at=now, updated_at=now,
    ))
    db_session.add(WorkflowStepDb(
        id=str(uuid.uuid4()), workflow_id=wf_id, step_id='evaluate', name='Evaluate',
        step_type=step_type, config='{}', order=0, created_at=now, updated_at=now,
    ))
    db_session.commit()
    return wf_id


def _refused(response):
    assert response.status_code == 403, response.text
    assert response.json()['detail']['code'] == 'workflow_step_requires_settings_write'


class TestWorkflowsWithTheMaturityStepNeedSettingsWrite:

    def test_creating_one_needs_settings_write(self, client, monkeypatch, db_session):
        _permissions(monkeypatch, **WORKFLOWS_ONLY)
        body = _body()

        _refused(client.post('/api/workflows', json=body))
        assert db_session.query(ProcessWorkflowDb).filter_by(name=body['name']).count() == 0
        # The same user saves workflows without the step
        assert client.post('/api/workflows', json=_body(step_type='pass')).status_code == 200

        _permissions(monkeypatch, **WORKFLOWS_ONLY, settings=FeatureAccessLevel.READ_WRITE)
        assert client.post('/api/workflows', json=body).status_code == 200

    def test_editing_one_needs_settings_write_also_without_sending_the_steps(
            self, client, monkeypatch, db_session):
        wf_id = _stored(db_session)
        _permissions(monkeypatch, **WORKFLOWS_ONLY)

        _refused(client.put(f'/api/workflows/{wf_id}', json={'description': 'edited'}))
        # Removing the step is not refused
        removed = client.put(f'/api/workflows/{wf_id}', json={'steps': [
            {'step_id': 'ok', 'name': 'OK', 'step_type': 'pass', 'order': 0}]})
        assert removed.status_code == 200, removed.text

    def test_activating_running_and_retrying_one_need_settings_write(
            self, client, monkeypatch, db_session):
        wf_id = _stored(db_session)
        _permissions(monkeypatch, **WORKFLOWS_ONLY)
        # Turning it off is not refused
        off = client.post(f'/api/workflows/{wf_id}/toggle-active?is_active=false')
        assert off.status_code == 200, off.text

        _refused(client.post(f'/api/workflows/{wf_id}/toggle-active?is_active=true'))
        _refused(client.post(f'/api/workflows/{wf_id}/execute?entity_type=table&entity_id=x'))
        failed = WorkflowExecutionDb(id=str(uuid.uuid4()), workflow_id=wf_id, status='failed',
                                     triggered_by='admin@example.com')
        db_session.add(failed)
        db_session.commit()
        # Refused before the execution is reset (the route answers other errors with 500)
        _refused(client.post(f'/api/workflows/executions/{failed.id}/retry'))

    def test_an_event_trigger_is_refused_with_its_code(self, client):
        response = client.post('/api/workflows', json=_body(trigger_type='on_create'))

        assert response.status_code == 400, response.text
        codes = [i['code'] for i in response.json()['detail']['params']['issues']]
        assert 'evaluate_asset_maturity_trigger_unsupported' in codes

    def test_a_trigger_only_change_to_an_event_trigger_is_refused(self, client, db_session):
        wf_id = _stored(db_session)

        response = client.put(f'/api/workflows/{wf_id}', json={
            'trigger': {'type': 'on_create', 'entity_types': ['table']}})

        assert response.status_code == 400, response.text
        codes = [i['code'] for i in response.json()['detail']['params']['issues']]
        assert 'evaluate_asset_maturity_trigger_unsupported' in codes
