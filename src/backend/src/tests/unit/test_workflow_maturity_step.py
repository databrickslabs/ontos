"""The evaluate_asset_maturity workflow step (#1414 follow-up).

The step runs the bulk maturity evaluation (``maturity_bulk_evaluator``) in its own
thread. ``run_now`` is wrapped so the run uses the test session and a fake per-asset
evaluator; scope selection, the one-run-at-a-time registry and the summary are real.
"""
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from src.common.workflow_executor import EvaluateAssetMaturityStepHandler, StepContext
from src.controller import maturity_bulk_evaluator as bulk
from src.controller.workflows_manager import WorkflowsManager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.maturity import MaturityLevelDb
from src.models.process_workflows import (
    ProcessWorkflowCreate,
    StepType,
    TriggerType,
    WorkflowStepCreate,
    WorkflowTrigger,
)


@pytest.fixture(autouse=True)
def _no_run_in_memory():
    bulk._current = None
    yield
    bulk._current = None


class _Report:
    def __init__(self, order):
        self.achieved_level_order = order
        self.stored = True  # a stored evaluation, as the real evaluator reports


class _FakeEvaluator:
    def __init__(self):
        self.calls = []

    def evaluate(self, db, *, entity_type, entity_id, persist=True, evaluated_by=None):
        self.calls.append((entity_id, evaluated_by))
        return _Report(1)


@pytest.fixture
def evaluator(db_session, monkeypatch):
    """The step's runs use the test session and this evaluator."""
    fake = _FakeEvaluator()
    real_run_now = bulk.run_now

    @contextmanager
    def same_session():
        yield db_session

    def run_now(scope, *, started_by):
        return real_run_now(scope, started_by=started_by, session_factory=same_session,
                            evaluator_factory=lambda: fake)

    monkeypatch.setattr(bulk, 'run_now', run_now)
    return fake


def _asset(db, location, type_name='Table'):
    asset_type = db.query(AssetTypeDb).filter_by(name=type_name).first()
    if asset_type is None:
        asset_type = AssetTypeDb(id=uuid.uuid4(), name=type_name)
        db.add(asset_type)
        db.flush()
    row = AssetDb(id=uuid.uuid4(), name=location.split('.')[-1], asset_type_id=asset_type.id,
                  platform='databricks', location=location, status='active')
    db.add(row)
    db.flush()
    return str(row.id)


def _asset_level(db):
    db.add(MaturityLevelDb(level_order=1, name='Prerequisite', entity_type='Asset'))
    db.flush()


def _context(user_email=None):
    return StepContext(
        entity={'type': 'schedule', 'id': 'wf-1'}, entity_type='schedule', entity_id='wf-1',
        entity_name='Nightly', user_email=user_email, trigger_context=None,
        execution_id='exec-1', workflow_id='wf-1', workflow_name='Nightly', step_results={},
    )


def _run_step(db, config, user_email=None):
    return EvaluateAssetMaturityStepHandler(db, config).execute(_context(user_email))


def test_the_step_evaluates_its_scope_and_returns_the_run_summary(db_session, evaluator):
    _asset_level(db_session)
    in_scope = {_asset(db_session, 'bulkw.sales.orders'),
                _asset(db_session, 'bulkw.sales.items', type_name='View')}
    _asset(db_session, 'bulkw.finance.gl')

    result = _run_step(db_session, {'catalog': 'bulkw', 'schema_name': 'sales'})

    assert result.passed, result.error
    assert {asset_id for asset_id, _ in evaluator.calls} == in_scope
    data = result.data
    assert data['state'] == 'completed'
    assert data['scope']['catalog'] == 'bulkw' and data['scope']['schema'] == 'sales'
    assert (data['total'], data['processed'], data['evaluated']) == (2, 2, 2)
    assert data['changed'] == 2  # no snapshot before: each asset got its first level
    assert (data['skipped'], data['error_count']) == ({}, 0)
    assert data['run_id'] == bulk.get_latest_run()['id']
    assert result.message == 'Evaluated 2 of 2 assets: 2 changed level, 0 skipped, 0 errors'


def test_without_a_scope_every_table_and_view_asset_is_evaluated(db_session, evaluator):
    _asset_level(db_session)
    _asset(db_session, 'bulkx.a.t1')
    _asset(db_session, 'bulky.b.t2')

    result = _run_step(db_session, {})

    assert result.passed
    assert result.data['scope']['catalog'] is None
    assert result.data['total'] >= 2


def test_a_scheduled_run_is_started_by_the_scheduler_and_a_manual_one_by_its_user(
        db_session, evaluator):
    _asset_level(db_session)
    _asset(db_session, 'bulkz.s.t')

    _run_step(db_session, {'catalog': 'bulkz'})
    assert bulk.get_latest_run()['started_by'] == 'system:scheduler'
    assert evaluator.calls[-1][1] == 'system:scheduler'

    _run_step(db_session, {'catalog': 'bulkz'}, user_email='admin@example.com')
    assert bulk.get_latest_run()['started_by'] == 'admin@example.com'


def test_a_run_in_progress_fails_the_step_with_its_code_and_leaves_that_run(
        db_session, evaluator):
    running = bulk.start_run(bulk.normalize_scope('other', None, None))

    result = _run_step(db_session, {'catalog': 'bulkw'})

    assert not result.passed
    assert result.data == {'error_code': 'maturity_bulk_run_in_progress', 'error_params': {}}
    assert evaluator.calls == []
    latest = bulk.get_latest_run()
    assert (latest['id'], latest['state']) == (running['id'], 'running')


def test_a_schema_without_a_catalog_fails_the_step_with_the_scope_code(db_session, evaluator):
    result = _run_step(db_session, {'schema_name': 'sales'})

    assert not result.passed
    assert result.data['error_code'] == 'maturity_bulk_scope_invalid'
    assert bulk._current is None  # no run was registered


def test_a_failed_run_fails_the_step_with_its_code_and_counts(
        db_session, evaluator, monkeypatch):
    def broken(db, scope):
        raise RuntimeError('database gone')

    monkeypatch.setattr(bulk, 'select_asset_ids', broken)

    result = _run_step(db_session, {'catalog': 'bulkw'})

    assert not result.passed
    assert result.data['error_code'] == 'maturity_bulk_run_failed'
    assert result.data['state'] == 'failed'
    assert result.data['error_count'] == 1
    assert 'database gone' not in (result.error or '') + (result.message or '')


# --- Saving a workflow with the step ------------------------------------------------

def _workflow(trigger_type, config=None):
    trigger = WorkflowTrigger(
        type=trigger_type,
        schedule='0 0 2 * * ?' if trigger_type == TriggerType.SCHEDULED else None,
    )
    return ProcessWorkflowCreate(
        name='Evaluate assets', trigger=trigger, is_active=False,
        steps=[WorkflowStepCreate(step_id='evaluate', name='Evaluate',
                                  step_type=StepType.EVALUATE_ASSET_MATURITY,
                                  config=config or {}, order=0)],
    )


def _codes(result):
    return [issue.code for issue in result.issues]


@pytest.mark.parametrize('trigger_type', [TriggerType.SCHEDULED, TriggerType.MANUAL])
def test_the_step_saves_on_scheduled_and_manual_workflows(db_session, trigger_type):
    result = WorkflowsManager(db_session).validate_workflow(
        _workflow(trigger_type, {'catalog': 'main', 'schema_name': 'sales'}))

    assert result.valid, result.errors


@pytest.mark.parametrize('trigger_type', [TriggerType.ON_CREATE, TriggerType.ON_UPDATE])
def test_the_step_is_refused_on_an_event_trigger(db_session, trigger_type):
    result = WorkflowsManager(db_session).validate_workflow(_workflow(trigger_type))

    assert not result.valid
    assert 'evaluate_asset_maturity_trigger_unsupported' in _codes(result)
    issue = next(i for i in result.issues
                 if i.code == 'evaluate_asset_maturity_trigger_unsupported')
    assert issue.params == {'step': 'evaluate', 'triggerType': trigger_type.value}


def test_a_schema_without_a_catalog_is_refused_on_save(db_session):
    result = WorkflowsManager(db_session).validate_workflow(
        _workflow(TriggerType.SCHEDULED, {'schema_name': 'sales'}))

    assert not result.valid
    assert _codes(result) == ['maturity_bulk_scope_invalid']


def test_the_step_type_is_listed_with_its_scope_fields(db_session):
    schemas = {s.type: s for s in WorkflowsManager(db_session).get_step_type_schemas()}

    schema = schemas[StepType.EVALUATE_ASSET_MATURITY]
    assert set(schema.config_schema['properties']) == {'catalog', 'schema_name'}


def test_the_shipped_nightly_workflow_is_inactive_and_valid(db_session):
    path = Path(__file__).resolve().parents[2] / 'data' / 'default_workflows.yaml'
    shipped = {w['id']: w for w in yaml.safe_load(path.read_text())['workflows']}
    nightly = shipped['nightly-asset-maturity-evaluation']

    assert nightly['is_active'] is False
    assert nightly['trigger']['type'] == 'scheduled'
    assert nightly['steps'][0]['type'] == 'evaluate_asset_maturity'
    workflow = ProcessWorkflowCreate(
        name=nightly['name'],
        trigger=WorkflowTrigger(type=TriggerType.SCHEDULED,
                                schedule=nightly['trigger']['schedule'],
                                timezone=nightly['trigger']['timezone']),
        is_active=False,
        steps=[WorkflowStepCreate(step_id=s['id'], name=s['name'], step_type=StepType(s['type']),
                                  config=s.get('config') or {}, on_pass=s.get('on_pass'),
                                  order=i)
               for i, s in enumerate(nightly['steps'])],
    )
    assert WorkflowsManager(db_session).validate_workflow(workflow).valid


def test_the_step_ends_its_session_transaction_before_the_long_run(monkeypatch):
    """A scheduled run's session holds a transaction (the execution row's refresh opened
    it); it must not stay idle in it for the whole run (Lakebase ends such sessions)."""
    events = []
    db = MagicMock()
    db.commit.side_effect = lambda: events.append('commit')

    def run_now(scope, *, started_by):
        events.append('run')
        return {'id': 'r1', 'state': 'completed', 'evaluated': 0, 'total': 0}

    monkeypatch.setattr(bulk, 'run_now', run_now)

    result = _run_step(db, {})

    assert result.passed, result.error
    assert events == ['commit', 'run']
