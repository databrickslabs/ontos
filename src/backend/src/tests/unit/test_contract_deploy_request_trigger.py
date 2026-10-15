"""Contract deploy requests have their own trigger and don't touch the status.

Deploy requests used to fire ``on_request_publish``, so every publication
workflow also ran for them, and a completed ``on_request_publish`` workflow
set the contract to ``deployed`` (approved) or ``draft`` (rejected).
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import yaml

from src.common.workflow_executor import WorkflowExecutor
from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.change_log import ChangeLogDb
from src.db_models.data_contracts import DataContractDb
from src.models.process_workflows import TriggerContext, TriggerType

_DEFAULT_WORKFLOWS = Path(__file__).resolve().parents[2] / 'data' / 'default_workflows.yaml'


def _contract(db, status='approved'):
    contract = DataContractDb(
        id=str(uuid.uuid4()), name='c', version='1.0.0', status=status,
        version_family_id=str(uuid.uuid4()),
    )
    db.add(contract)
    db.flush()
    return contract


def _complete(db, contract, trigger_type, succeeded, approved=None):
    workflow = SimpleNamespace(name='Gate', trigger=SimpleNamespace(type=trigger_type))
    context = TriggerContext(
        entity_type='data_contract', entity_id=contract.id, entity_name=contract.name,
        trigger_type=trigger_type, user_email='requester@example.com',
    )
    WorkflowExecutor(db)._handle_workflow_completion(
        trigger_context=context, workflow=workflow, succeeded=succeeded,
        responded_by='approver@example.com', approved=approved,
    )


def test_request_deploy_fires_on_request_deploy():
    registry = MagicMock()
    registry.on_request_deploy.return_value = [MagicMock()]
    contract = SimpleNamespace(id='contract-1', name='Orders')

    with patch('src.controller.data_contracts_manager.data_contract_repo') as repo, \
            patch('src.controller.change_log_manager.change_log_manager'), \
            patch('src.common.workflow_triggers.get_trigger_registry', return_value=registry):
        repo.get.return_value = contract
        result = DataContractsManager.request_deploy(
            MagicMock(), db=MagicMock(), notifications_manager=MagicMock(),
            deployment_manager=MagicMock(), current_user_obj=None,
            contract_id='contract-1', requester_email='requester@example.com',
        )

    registry.on_request_deploy.assert_called_once()
    registry.on_request_publish.assert_not_called()
    assert registry.on_request_deploy.call_args.kwargs['entity_id'] == 'contract-1'
    assert 'Workflow triggered' in result['message']


@pytest.mark.parametrize('approved, decision', [(True, 'approve'), (False, 'deny')])
def test_deploy_decision_is_logged_and_status_kept(db_session, approved, decision):
    contract = _contract(db_session)

    _complete(db_session, contract, TriggerType.ON_REQUEST_DEPLOY, approved, approved=approved)

    db_session.refresh(contract)
    assert contract.status == 'approved'
    entry = db_session.query(ChangeLogDb).filter(ChangeLogDb.entity_id == contract.id).one()
    assert entry.action == f'deploy_{decision}'
    assert entry.username == 'approver@example.com'
    details = json.loads(entry.details_json)
    assert details['requester_email'] == 'requester@example.com'
    assert details['workflow'] == 'Gate'


@pytest.mark.parametrize('succeeded', [True, False])
def test_a_deploy_workflow_without_approval_logs_no_decision(db_session, succeeded):
    contract = _contract(db_session)

    _complete(db_session, contract, TriggerType.ON_REQUEST_DEPLOY, succeeded)

    db_session.refresh(contract)
    assert contract.status == 'approved'
    assert db_session.query(ChangeLogDb).filter(ChangeLogDb.entity_id == contract.id).count() == 0


@pytest.mark.parametrize('succeeded', [True, False])
def test_publication_request_completion_keeps_contract_status(db_session, succeeded):
    contract = _contract(db_session)

    _complete(db_session, contract, TriggerType.ON_REQUEST_PUBLISH, succeeded)

    db_session.refresh(contract)
    assert contract.status == 'approved'
    assert db_session.query(ChangeLogDb).filter(ChangeLogDb.entity_id == contract.id).count() == 0


def _default_workflows():
    return yaml.safe_load(_DEFAULT_WORKFLOWS.read_text())['workflows']


def _handling(trigger_type, entity_type):
    return sorted(
        wf['name'] for wf in _default_workflows()
        if wf['trigger']['type'] == trigger_type
        and entity_type in wf['trigger'].get('entity_types', [])
    )


def test_default_workflows_split_deploy_and_publish_requests():
    assert _handling('on_request_deploy', 'data_contract') == ['Data Contract Deploy Request']
    assert 'Data Contract Deploy Request' not in _handling('on_request_publish', 'data_contract')


def test_the_logged_decision_is_the_approvers_not_the_run_outcome(db_session):
    # Approved, but a later step (e.g. the notification) failed the run.
    contract = _contract(db_session)
    workflow = SimpleNamespace(
        name='Gate', trigger=SimpleNamespace(type=TriggerType.ON_REQUEST_DEPLOY)
    )
    context = TriggerContext(
        entity_type='data_contract', entity_id=contract.id, entity_name=contract.name,
        trigger_type=TriggerType.ON_REQUEST_DEPLOY, user_email='requester@example.com',
    )

    WorkflowExecutor(db_session)._handle_workflow_completion(
        trigger_context=context, workflow=workflow, succeeded=False,
        responded_by='approver@example.com', approved=True,
    )

    entry = db_session.query(ChangeLogDb).filter(ChangeLogDb.entity_id == contract.id).one()
    assert entry.action == 'deploy_approve'
