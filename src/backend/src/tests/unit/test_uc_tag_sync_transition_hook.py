"""A lifecycle transition into or out of deprecated / retired requests a uc_tag_sync run.

The real managers and a real JobsManager run against the test database; only the
Databricks workspace client is a mock. The JobsManager is registered in the app state
registry the way startup does.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
import logging
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.service.jobs import RunLifeCycleState

from src.common import app_state
from src.common.workflow_executor import WorkflowExecutor
from src.controller.data_contracts_manager import DataContractsManager
from src.controller.data_products_manager import DataProductsManager
from src.controller.jobs_manager import JobsManager
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb
from src.db_models.workflow_installations import WorkflowInstallationDb
from src.models.process_workflows import TriggerContext, TriggerType
from src.repositories.workflow_configurations_repository import workflow_configuration_repo

JOB_ID = 4242
RUN_ID = 777


@pytest.fixture
def ws():
    client = MagicMock()
    client.jobs.list_runs.return_value = []
    client.jobs.run_now.return_value = SimpleNamespace(run_id=RUN_ID)
    return client


@pytest.fixture
def jobs_manager(db_session, ws, monkeypatch):
    manager = JobsManager(db=db_session, ws_client=ws)
    monkeypatch.setattr(manager, 'run_job', MagicMock(wraps=manager.run_job))
    monkeypatch.setitem(app_state._managers_registry, 'jobs_manager', manager)
    return manager


@pytest.fixture
def installed(db_session):
    installation = WorkflowInstallationDb(
        workflow_id='uc_tag_sync', name='Unity Catalog Tag Sync', job_id=JOB_ID,
        status='installed',
    )
    db_session.add(installation)
    db_session.flush()
    return installation


def _product(db, status):
    product = DataProductDb(
        id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct', status=status,
        name=f'p-{uuid.uuid4().hex[:8]}', version='1.0.0',
    )
    db.add(product)
    db.flush()
    return product


def _contract(db, status):
    contract = DataContractDb(
        id=str(uuid.uuid4()), name=f'c-{uuid.uuid4().hex[:8]}', version='1.0.0',
        status=status,
    )
    db.add(contract)
    db.flush()
    return contract


def _stored_status(db, model, entity_id):
    db.expire_all()
    return db.get(model, entity_id).status


def _assert_one_run_requested(jobs_manager, ws):
    jobs_manager.run_job.assert_called_once_with(
        job_id=JOB_ID, job_name='uc_tag_sync', workflow_id='uc_tag_sync'
    )
    ws.jobs.run_now.assert_called_once()
    assert ws.jobs.run_now.call_args.kwargs['job_id'] == JOB_ID


@pytest.mark.parametrize('from_status, to_status', [
    ('active', 'deprecated'), ('deprecated', 'retired'), ('deprecated', 'active'),
])
def test_a_product_transition_requests_one_run(db_session, jobs_manager, installed, ws,
                                               from_status, to_status):
    product = _product(db_session, from_status)

    DataProductsManager(db=db_session).transition_status(product.id, to_status, 'u@x.com')

    _assert_one_run_requested(jobs_manager, ws)
    assert _stored_status(db_session, DataProductDb, product.id) == to_status


def test_the_run_gets_the_saved_tag_sync_configuration(db_session, jobs_manager, installed,
                                                       ws):
    configs = [{'entity_type': entity_type, 'mapping': 'lifecycle_status', 'enabled': True,
                'tag_key_format': 'lifecycle', 'tag_value_format': value_format}
               for entity_type, value_format in (('data_contract', '{CONTRACT.STATUS}'),
                                                 ('data_product', '{PRODUCT.STATUS}'))]
    workflow_configuration_repo.upsert(db_session, workflow_id='uc_tag_sync',
                                       configuration={'tag_sync_configs': configs})
    product = _product(db_session, 'active')

    DataProductsManager(db=db_session).transition_status(product.id, 'deprecated')

    params = ws.jobs.run_now.call_args.kwargs['job_parameters']
    assert json.loads(params['tag_sync_configs']) == configs


def test_a_configuration_saved_without_the_mapping_runs_with_it(db_session, jobs_manager,
                                                                installed, ws):
    """An upgraded install whose saved list predates the lifecycle entries."""
    name_entry = {'entity_type': 'data_product', 'enabled': True,
                  'tag_key_format': 'ontos_product_name', 'tag_value_format': '{PRODUCT.NAME}'}
    workflow_configuration_repo.upsert(db_session, workflow_id='uc_tag_sync',
                                       configuration={'tag_sync_configs': [name_entry]})
    product = _product(db_session, 'active')

    DataProductsManager(db=db_session).transition_status(product.id, 'deprecated')

    params = ws.jobs.run_now.call_args.kwargs['job_parameters']
    configs = json.loads(params['tag_sync_configs'])
    assert configs[0] == name_entry
    assert [(c['entity_type'], c['enabled'], c['tag_value_format']) for c in configs[1:]] == [
        ('data_contract', False, '{CONTRACT.STATUS}'),
        ('data_product', True, '{PRODUCT.STATUS}'),
    ]


def test_other_transitions_wait_for_the_scheduled_run(db_session, jobs_manager, installed,
                                                      ws):
    product = _product(db_session, 'draft')

    DataProductsManager(db=db_session).transition_status(product.id, 'proposed')

    jobs_manager.run_job.assert_not_called()
    ws.jobs.list_runs.assert_not_called()


@pytest.mark.parametrize('status', ['failed', None])
def test_no_run_without_an_installed_job(db_session, jobs_manager, ws, status):
    if status:
        db_session.add(WorkflowInstallationDb(workflow_id='uc_tag_sync', name='x',
                                              job_id=JOB_ID, status=status))
        db_session.flush()
    product = _product(db_session, 'active')

    DataProductsManager(db=db_session).transition_status(product.id, 'deprecated')

    jobs_manager.run_job.assert_not_called()
    ws.jobs.run_now.assert_not_called()
    assert _stored_status(db_session, DataProductDb, product.id) == 'deprecated'


@pytest.mark.parametrize('state', [
    RunLifeCycleState.QUEUED, RunLifeCycleState.PENDING, RunLifeCycleState.BLOCKED,
    RunLifeCycleState.WAITING_FOR_RETRY,
])
def test_a_run_waiting_to_start_is_enough(db_session, jobs_manager, installed, ws, state):
    ws.jobs.list_runs.return_value = [
        SimpleNamespace(run_id=1, state=SimpleNamespace(life_cycle_state=state))]
    product = _product(db_session, 'active')

    DataProductsManager(db=db_session).transition_status(product.id, 'deprecated')

    ws.jobs.list_runs.assert_called_once_with(job_id=JOB_ID, active_only=True)
    jobs_manager.run_job.assert_not_called()


def test_a_running_run_may_have_read_the_old_status(db_session, jobs_manager, installed, ws):
    ws.jobs.list_runs.return_value = [SimpleNamespace(
        run_id=1, state=SimpleNamespace(life_cycle_state=RunLifeCycleState.RUNNING))]
    product = _product(db_session, 'active')

    DataProductsManager(db=db_session).transition_status(product.id, 'deprecated')

    _assert_one_run_requested(jobs_manager, ws)


@pytest.mark.parametrize('failing', ['run_now', 'list_runs'])
def test_a_failed_request_never_fails_the_transition(db_session, jobs_manager, installed, ws,
                                                     caplog, failing):
    getattr(ws.jobs, failing).side_effect = RuntimeError('workspace unreachable')
    product = _product(db_session, 'active')

    with caplog.at_level(logging.WARNING):
        result = DataProductsManager(db=db_session).transition_status(product.id, 'deprecated')

    assert result.status == 'deprecated'
    assert _stored_status(db_session, DataProductDb, product.id) == 'deprecated'
    assert 'Could not request a uc_tag_sync run' in caplog.text


def test_no_jobs_manager_no_run(db_session, installed, ws):
    product = _product(db_session, 'active')

    DataProductsManager(db=db_session).transition_status(product.id, 'deprecated')

    ws.jobs.run_now.assert_not_called()
    assert _stored_status(db_session, DataProductDb, product.id) == 'deprecated'


def test_startup_registers_the_jobs_manager_for_the_hook(monkeypatch):
    # Without the registration the hook finds no JobsManager and silently does nothing.
    # Startup runs with mocked managers up to the jobs manager, then stops.
    from src.utils import startup_tasks

    monkeypatch.setattr(app_state, '_managers_registry', {})
    jobs = object()
    for name, mock in {
        'get_workspace_client': MagicMock(),
        'get_session_factory': MagicMock(),
        'get_registry': MagicMock(),
        'SettingsManager': MagicMock(return_value=MagicMock(_jobs=jobs)),
        'AuditManager': MagicMock(),
        'UsersManager': MagicMock(),
        'AuthorizationManager': MagicMock(),
        'NotificationsManager': MagicMock(),
        'DataAssetReviewManager': MagicMock(side_effect=RuntimeError('stop here')),
    }.items():
        monkeypatch.setattr(startup_tasks, name, mock)
    monkeypatch.setattr('src.controller.connections_manager.ConnectionsManager', MagicMock())
    monkeypatch.setattr('src.controller.workspace_manager.WorkspaceManager', MagicMock())
    app = SimpleNamespace(state=SimpleNamespace(health={'warnings': []}))

    startup_tasks.initialize_managers(app)

    assert app.state.jobs_manager is jobs
    assert app_state.get_app_state_manager('jobs_manager') is jobs


def test_a_contract_transition_requests_one_run(db_session, jobs_manager, installed, ws):
    contract = _contract(db_session, 'active')

    DataContractsManager(data_dir=Path('/tmp')).transition_status(
        db_session, contract.id, 'deprecated', 'u@x.com')

    _assert_one_run_requested(jobs_manager, ws)


def test_a_failed_request_keeps_the_contract_transition(db_session, jobs_manager, installed,
                                                        ws):
    ws.jobs.run_now.side_effect = RuntimeError('workspace unreachable')
    contract = _contract(db_session, 'active')

    updated = DataContractsManager(data_dir=Path('/tmp')).transition_status(
        db_session, contract.id, 'deprecated', 'u@x.com')

    assert updated.status == 'deprecated'
    assert _stored_status(db_session, DataContractDb, contract.id) == 'deprecated'


def test_an_approved_contract_status_change_request_requests_one_run(db_session,
                                                                      jobs_manager,
                                                                      installed, ws):
    contract = _contract(db_session, 'active')

    DataContractsManager(data_dir=Path('/tmp')).handle_status_change_response(
        db_session, MagicMock(), contract.id, approver_email='a@x.com', decision='approve',
        target_status='deprecated', requester_email='r@x.com',
    )

    _assert_one_run_requested(jobs_manager, ws)
    assert _stored_status(db_session, DataContractDb, contract.id) == 'deprecated'


def test_an_approved_product_status_change_request_requests_one_run(db_session,
                                                                     jobs_manager,
                                                                     installed, ws):
    # The default Status Change Request workflow applies the status once approved.
    product = _product(db_session, 'active')
    context = TriggerContext(
        entity_type='data_product', entity_id=product.id, entity_name=product.name,
        trigger_type=TriggerType.ON_REQUEST_STATUS_CHANGE, user_email='r@x.com',
        from_status='active', to_status='deprecated',
        entity_data={'target_status': 'deprecated', 'justification': 'v2'},
    )
    workflow = SimpleNamespace(
        name='Status Change Request',
        trigger=SimpleNamespace(type=TriggerType.ON_REQUEST_STATUS_CHANGE),
    )

    WorkflowExecutor(db_session)._handle_workflow_completion(
        trigger_context=context, workflow=workflow, succeeded=True,
        responded_by='a@x.com', approved=True,
    )

    _assert_one_run_requested(jobs_manager, ws)
    assert _stored_status(db_session, DataProductDb, product.id) == 'deprecated'


def test_an_approved_product_status_change_response_requests_one_run(db_session,
                                                                      jobs_manager,
                                                                      installed, ws):
    product = _product(db_session, 'active')

    DataProductsManager(db=db_session).handle_status_change_response(
        db_session, MagicMock(), product.id, approver_email='a@x.com', decision='approve',
        target_status='deprecated',
    )

    _assert_one_run_requested(jobs_manager, ws)
    assert _stored_status(db_session, DataProductDb, product.id) == 'deprecated'


@pytest.mark.parametrize('entity_type', ['data_contract', 'data_product'])
def test_an_approved_request_asks_with_the_stored_and_the_requested_status(
        db_session, jobs_manager, installed, ws, monkeypatch, entity_type):
    # One request per approval, through transition_status, once the new status is written.
    from src.common import uc_tag_sync_trigger
    from src.controller import data_contracts_manager, data_products_manager

    stored = {}
    real = uc_tag_sync_trigger.request_uc_tag_sync_after_transition

    def spy(kind, entity_id, from_status, to_status):
        model = DataContractDb if kind == 'data_contract' else DataProductDb
        stored[entity_id] = _stored_status(db_session, model, entity_id)
        return real(kind, entity_id, from_status, to_status)

    request = MagicMock(side_effect=spy)
    monkeypatch.setattr(data_contracts_manager, 'request_uc_tag_sync_after_transition', request)
    monkeypatch.setattr(data_products_manager, 'request_uc_tag_sync_after_transition', request)

    if entity_type == 'data_contract':
        entity = _contract(db_session, 'active')
        DataContractsManager(data_dir=Path('/tmp')).handle_status_change_response(
            db_session, MagicMock(), entity.id, approver_email='a@x.com', decision='approve',
            target_status='Deprecated', requester_email='r@x.com',
        )
    else:
        entity = _product(db_session, 'active')
        DataProductsManager(db=db_session).handle_status_change_response(
            db_session, MagicMock(), entity.id, approver_email='a@x.com', decision='approve',
            target_status='Deprecated',
        )

    request.assert_called_once_with(entity_type, entity.id, 'active', 'deprecated')
    assert stored[entity.id] == 'deprecated'
    _assert_one_run_requested(jobs_manager, ws)
