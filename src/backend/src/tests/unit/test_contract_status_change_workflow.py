"""A data contract's status change request goes through the Status Change Request workflow (#1120).

- ``DataContractsManager.request_status_change`` fires ``on_request_status_change``
  with a product's payload, instead of its own English notifications;
- the completion of the request workflow applies an approved contract request
  through ``DataContractsManager.transition_status``, only while the contract
  still has the status the request was made from;
- the default "Status Change Request" workflow covers contracts, and an
  existing install gets ``data_contract`` added to its stored default once,
  keeping the admin's edits.
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
from src.controller.workflows_manager import WorkflowsManager
from src.db_models.app_settings import AppSettingDb
from src.db_models.data_contracts import DataContractDb
from src.db_models.notifications import NotificationDb
from src.db_models.process_workflows import ProcessWorkflowDb
from src.models.process_workflows import EntityType, TriggerContext, TriggerType

DEFAULT_WORKFLOWS = Path(__file__).resolve().parents[2] / 'data' / 'default_workflows.yaml'
UPGRADE_KEY = 'default_workflow_added_status_change_request_data_contract'


def _contract(db, status='active'):
    contract = DataContractDb(
        id=str(uuid.uuid4()), name=f'c-{uuid.uuid4().hex[:8]}', version='1.0.0', status=status,
    )
    db.add(contract)
    db.flush()
    return contract


# --- The request -------------------------------------------------------------

def test_a_request_fires_the_trigger_with_the_products_payload(db_session):
    contract = _contract(db_session)
    notifications = MagicMock()
    registry = MagicMock()
    registry.on_request_status_change.return_value = []

    with patch('src.common.workflow_triggers.get_trigger_registry', return_value=registry):
        result = DataContractsManager(data_dir=Path('.')).request_status_change(
            db=db_session, notifications_manager=notifications, contract_id=contract.id,
            target_status='Deprecated', justification='Replaced by v2',
            requester_email='requester@example.com', current_user='requester',
        )

    kwargs = registry.on_request_status_change.call_args.kwargs
    assert kwargs['entity_type'] == EntityType.DATA_CONTRACT
    assert kwargs['entity_id'] == contract.id
    assert (kwargs['from_status'], kwargs['to_status']) == ('active', 'deprecated')
    assert kwargs['user_email'] == 'requester@example.com'
    assert kwargs['entity_data'] == {
        'contract_id': contract.id, 'contract_name': contract.name,
        'from_status': 'active', 'target_status': 'deprecated',
        'justification': 'Replaced by v2', 'request_id': result['request_id'],
    }
    # The workflow notifies; the manager creates no notification of its own
    notifications.create_notification.assert_not_called()
    assert db_session.query(NotificationDb).count() == 0


def test_the_request_is_logged_with_the_id_the_workflow_gets(db_session):
    from src.controller.change_log_manager import change_log_manager

    contract = _contract(db_session)
    registry = MagicMock()
    registry.on_request_status_change.return_value = []

    with patch('src.common.workflow_triggers.get_trigger_registry', return_value=registry):
        result = DataContractsManager(data_dir=Path('.')).request_status_change(
            db=db_session, notifications_manager=MagicMock(), contract_id=contract.id,
            target_status='deprecated', justification='Replaced by v2',
            requester_email='requester@example.com',
        )

    entries = change_log_manager.get_changes_for_entity(
        db_session, 'data_contract', contract.id, action='status_change_requested',
    )
    assert [e.details['request_id'] for e in entries] == [result['request_id']]
    assert entries[0].details['workflow_triggered'] is False


# --- The completion ----------------------------------------------------------

def _complete(db, contract, approved, target='deprecated', from_status=None):
    context = TriggerContext(
        entity_type='data_contract', entity_id=contract.id, entity_name=contract.name,
        trigger_type=TriggerType.ON_REQUEST_STATUS_CHANGE, user_email='requester@example.com',
        from_status=from_status or contract.status, to_status=target,
        entity_data={'target_status': target, 'justification': 'Moving to v2'},
    )
    workflow = SimpleNamespace(
        name='Status Change Request',
        trigger=SimpleNamespace(type=TriggerType.ON_REQUEST_STATUS_CHANGE),
    )
    WorkflowExecutor(db)._handle_workflow_completion(
        trigger_context=context, workflow=workflow, succeeded=approved,
        responded_by='approver@example.com', approved=approved,
    )


def _warnings(db, contract):
    return db.query(NotificationDb).filter(NotificationDb.subtitle == contract.name).all()


@pytest.mark.parametrize('approved, expected', [(True, 'deprecated'), (False, 'active')])
def test_the_requested_status_is_applied_only_when_approved(db_session, approved, expected):
    contract = _contract(db_session)

    _complete(db_session, contract, approved)

    db_session.refresh(contract)
    assert contract.status == expected


def test_it_goes_through_the_contracts_transition_status(db_session):
    contract = _contract(db_session)
    manager = MagicMock()

    with patch('src.controller.data_contracts_manager.get_live_contracts_manager',
               return_value=manager):
        _complete(db_session, contract, True)

    manager.transition_status.assert_called_once_with(
        db=db_session, contract_id=contract.id, new_status='deprecated',
        current_user='approver@example.com',
    )


def test_a_request_made_from_another_status_is_not_applied(db_session):
    # Requested approved -> deprecated; meanwhile the contract went active
    contract = _contract(db_session, status='active')

    _complete(db_session, contract, True, from_status='approved')

    db_session.refresh(contract)
    assert contract.status == 'active'
    notes = _warnings(db_session, contract)
    assert {n.recipient for n in notes} == {'requester@example.com', 'approver@example.com'}
    assert all(json.loads(n.data)['i18n'] == {
        'title': 'notifications:statusChangeNotApplied.title',
        'description': 'notifications:statusChangeNotApplied.statusChanged',
        'params': {'fromStatus': 'approved', 'toStatus': 'deprecated', 'currentStatus': 'active'},
        # The contract status labels translate the statuses
        'statusNamespace': 'data-contracts',
    } for n in notes)


def test_a_refused_transition_tells_the_requester_with_its_code(db_session):
    contract = _contract(db_session, status='retired')

    _complete(db_session, contract, True, target='active')

    db_session.refresh(contract)
    assert contract.status == 'retired'
    notes = _warnings(db_session, contract)
    assert [n.recipient for n in notes] == ['requester@example.com']
    i18n = json.loads(notes[0].data)['i18n']
    assert i18n['description'] == 'notifications:statusChangeNotApplied.refused'
    assert i18n['statusNamespace'] == 'data-contracts'


def test_a_certified_contract_needs_the_approval_step(db_session):
    # A run that ended without an approver's decision doesn't deprecate it
    contract = _contract(db_session)
    contract.certification_level = 1
    db_session.flush()
    context = TriggerContext(
        entity_type='data_contract', entity_id=contract.id, entity_name=contract.name,
        trigger_type=TriggerType.ON_REQUEST_STATUS_CHANGE, user_email='requester@example.com',
        from_status='active', to_status='deprecated', entity_data={},
    )
    workflow = SimpleNamespace(
        name='Status Change Request',
        trigger=SimpleNamespace(type=TriggerType.ON_REQUEST_STATUS_CHANGE),
    )

    WorkflowExecutor(db_session)._handle_workflow_completion(
        trigger_context=context, workflow=workflow, succeeded=True,
        responded_by='approver@example.com', approved=None,
    )

    db_session.refresh(contract)
    assert contract.status == 'active'
    error = json.loads(_warnings(db_session, contract)[0].data)['i18n']['error']
    assert error['code'] == 'certified_deprecation_approval_refused'
    assert error['params']['reason'] == 'no_approver'


# --- The default workflow and existing installs ------------------------------

def test_the_default_workflow_covers_contracts():
    workflows = yaml.safe_load(DEFAULT_WORKFLOWS.read_text())['workflows']
    default = next(wf for wf in workflows if wf['id'] == 'status-change-request')

    assert default['trigger']['entity_types'] == ['data_product', 'data_contract']


def _stored_default(db, entity_types=('data_product',), is_default=True, approvers='Admin'):
    """The Status Change Request workflow as an older install stored it."""
    WorkflowsManager(db).load_from_yaml(str(DEFAULT_WORKFLOWS))
    workflow = db.query(ProcessWorkflowDb).filter_by(name='Status Change Request').one()
    trigger = json.loads(workflow.trigger_config)
    trigger['entity_types'] = list(entity_types)
    workflow.trigger_config = json.dumps(trigger)
    workflow.is_default = is_default
    # An admin's edit of the approval step
    step = next(s for s in workflow.steps if s.step_id == 'request-approval')
    step.config = json.dumps({**json.loads(step.config), 'approvers': approvers})
    db.query(AppSettingDb).filter_by(key=UPGRADE_KEY).delete()
    db.commit()
    return workflow


def _entity_types(db):
    db.expire_all()
    workflow = db.query(ProcessWorkflowDb).filter_by(name='Status Change Request').one()
    return json.loads(workflow.trigger_config)['entity_types']


def test_an_existing_install_gets_contracts_added_once_keeping_the_admins_edits(db_session):
    workflow = _stored_default(db_session, approvers='DomainOwner')
    version = workflow.version

    assert WorkflowsManager(db_session).add_default_entity_types() == 1

    assert _entity_types(db_session) == ['data_product', 'data_contract']
    workflow = db_session.query(ProcessWorkflowDb).filter_by(name='Status Change Request').one()
    step = next(s for s in workflow.steps if s.step_id == 'request-approval')
    assert json.loads(step.config)['approvers'] == 'DomainOwner'
    assert workflow.version == version + 1 and workflow.updated_by == 'system'
    assert db_session.query(AppSettingDb).filter_by(key=UPGRADE_KEY).one().value == 'done'


def test_an_admin_who_removes_contracts_later_keeps_them_removed(db_session):
    _stored_default(db_session)
    WorkflowsManager(db_session).add_default_entity_types()
    workflow = db_session.query(ProcessWorkflowDb).filter_by(name='Status Change Request').one()
    trigger = json.loads(workflow.trigger_config)
    trigger['entity_types'] = ['data_product']
    workflow.trigger_config = json.dumps(trigger)
    db_session.commit()

    assert WorkflowsManager(db_session).add_default_entity_types() == 0

    assert _entity_types(db_session) == ['data_product']


@pytest.mark.parametrize('entity_types, is_default', [
    ([], True),  # matches every entity type already
    (['data_product'], False),  # not the shipped default
])
def test_other_workflows_are_left_as_they_are(db_session, entity_types, is_default):
    _stored_default(db_session, entity_types=entity_types, is_default=is_default)

    assert WorkflowsManager(db_session).add_default_entity_types() == 0

    assert _entity_types(db_session) == entity_types


def test_a_fresh_install_only_records_the_upgrade(db_session):
    WorkflowsManager(db_session).load_from_yaml(str(DEFAULT_WORKFLOWS), requests_only_active=True)
    db_session.query(AppSettingDb).filter_by(key=UPGRADE_KEY).delete()
    db_session.commit()

    assert WorkflowsManager(db_session).add_default_entity_types() == 0

    assert _entity_types(db_session) == ['data_product', 'data_contract']
    assert db_session.query(AppSettingDb).filter_by(key=UPGRADE_KEY).count() == 1


def test_startup_seeding_runs_the_upgrade():
    from src import app as app_module

    manager = MagicMock()
    manager.load_from_yaml.return_value = {'created': 0, 'updated': 0, 'skipped': 1}
    with patch('src.common.database.get_session_factory', return_value=MagicMock()), \
            patch('src.controller.workflows_manager.WorkflowsManager', return_value=manager):
        app_module._seed_default_workflows()

    manager.load_from_yaml.assert_called_once_with(requests_only_active=True)
    manager.add_default_entity_types.assert_called_once_with()
