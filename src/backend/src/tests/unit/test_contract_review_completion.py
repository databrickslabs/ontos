"""A contract review decided in its workflow sets the contract status.

Approving a contract review from the notification (the workflow's approval
step) used to leave the contract in ``proposed``, while the contract page's
approve endpoint moves it to ``approved`` (#1066).
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
import logging
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.common.workflow_executor import WorkflowExecutor
from src.db_models.data_contracts import DataContractDb
from src.db_models.notifications import NotificationDb
from src.models.process_workflows import TriggerContext, TriggerType


def _contract(db, status='proposed'):
    contract = DataContractDb(
        id=str(uuid.uuid4()), name='Orders', version='1.0.0', status=status,
        version_family_id=str(uuid.uuid4()),
    )
    db.add(contract)
    db.commit()
    return contract


def _complete(db, contract, approved, succeeded=True):
    workflow = SimpleNamespace(
        name='Data Contract Review Request',
        trigger=SimpleNamespace(type=TriggerType.ON_REQUEST_REVIEW),
    )
    context = TriggerContext(
        entity_type='data_contract', entity_id=contract.id, entity_name=contract.name,
        trigger_type=TriggerType.ON_REQUEST_REVIEW, user_email='requester@example.com',
    )
    WorkflowExecutor(db)._handle_workflow_completion(
        trigger_context=context, workflow=workflow, succeeded=succeeded,
        responded_by='steward@example.com', approved=approved,
    )
    db.refresh(contract)


def _notices(db):
    return db.query(NotificationDb).filter(NotificationDb.recipient == 'steward@example.com').all()


@pytest.mark.parametrize('from_status', ['proposed', 'under_review'])
def test_an_approved_review_approves_the_contract(db_session, from_status):
    contract = _contract(db_session, from_status)

    _complete(db_session, contract, approved=True)

    assert contract.status == 'approved'
    assert contract.updated_by == 'steward@example.com'


def test_a_rejected_review_returns_the_contract_to_draft(db_session):
    contract = _contract(db_session)

    # The default workflow ends with a notification, so the run succeeds
    _complete(db_session, contract, approved=False, succeeded=True)

    assert contract.status == 'draft'


@pytest.mark.parametrize('succeeded', [True, False])
def test_a_review_workflow_without_approval_leaves_the_status(db_session, succeeded):
    contract = _contract(db_session)

    _complete(db_session, contract, approved=None, succeeded=succeeded)

    assert contract.status == 'proposed'


def test_the_status_change_goes_through_transition_status(db_session):
    contract = _contract(db_session)

    with patch('src.common.workflow_triggers.fire_trigger_safe') as fire:
        _complete(db_session, contract, approved=True)

    fire.assert_called_once()
    assert fire.call_args.args[1] == 'on_status_change'
    assert fire.call_args.kwargs['to_status'] == 'approved'


def test_a_contract_decided_meanwhile_is_left_alone(db_session):
    # Approved from the contract page while the workflow waited
    contract = _contract(db_session, 'approved')

    _complete(db_session, contract, approved=True)

    assert contract.status == 'approved'
    assert _notices(db_session) == []


def test_a_contract_that_left_review_is_not_moved(db_session, caplog):
    # Rejected from the contract page (back to draft), then approved in the workflow
    contract = _contract(db_session, 'draft')

    with caplog.at_level(logging.WARNING):
        _complete(db_session, contract, approved=True)

    assert contract.status == 'draft'
    assert 'not under review' in caplog.text
    [notice] = _notices(db_session)
    assert 'draft' in notice.description
    # Keys of the frontend's notifications namespace, for the bell to translate
    assert json.loads(notice.data)['i18n'] == {
        'title': 'notifications:contractStatusNotChanged.title',
        'description': 'notifications:contractStatusNotChanged.notUnderReview',
        'params': {'toStatus': 'approved', 'currentStatus': 'draft'},
        # The contract status labels translate toStatus / currentStatus
        'statusNamespace': 'data-contracts',
    }


def test_a_blocked_transition_is_reported_to_the_approver(db_session):
    contract = _contract(db_session)
    registry = MagicMock()
    registry.before_status_change.return_value = (False, [])

    with patch('src.common.workflow_triggers.get_trigger_registry', return_value=registry):
        _complete(db_session, contract, approved=True)

    assert contract.status == 'proposed'
    [notice] = _notices(db_session)
    assert notice.title == 'Contract status not changed'
    assert 'blocked by workflow' in notice.description
    i18n = json.loads(notice.data)['i18n']
    assert i18n['description'] == 'notifications:contractStatusNotChanged.notApplied'
    assert i18n['params']['toStatus'] == 'approved'
    assert 'blocked by workflow' in i18n['params']['reason']


def test_a_gate_refusal_is_sent_with_its_code_to_approver_and_requester(db_session):
    """A gate that blocks the decision reaches both people with a coded reason.

    The bell translates the reason with the same keys as the status change
    dialogs (``workflow-gates``), so no English text is shown in pt.
    """
    from src.common.workflow_triggers import StatusChangeBlockedError

    contract = _contract(db_session)
    blocked = StatusChangeBlockedError.without_reasons('proposed', 'approved')
    blocked.params['reasons'] = [{'workflow': 'Contract Gate', 'text': 'Not yet'}]

    with patch(
        'src.controller.data_contracts_manager.DataContractsManager.transition_status',
        side_effect=blocked,
    ):
        _complete(db_session, contract, approved=True)

    assert contract.status == 'proposed'
    notes = {n.recipient: n for n in db_session.query(NotificationDb).all()}
    assert set(notes) == {'steward@example.com', 'requester@example.com'}
    approver = json.loads(notes['steward@example.com'].data)['i18n']
    requester = json.loads(notes['requester@example.com'].data)['i18n']
    assert approver['description'] == 'notifications:contractStatusNotChanged.notApplied'
    assert requester['description'] == 'notifications:contractStatusNotChanged.requesterNotApplied'
    for i18n in (approver, requester):
        assert i18n['statusNamespace'] == 'data-contracts'
        assert i18n['error']['code'] == 'status_change_blocked'
        assert i18n['error']['params']['toStatus'] == 'approved'
        assert i18n['error']['params']['reasons'][0]['workflow'] == 'Contract Gate'
    assert 'was decided' in notes['requester@example.com'].description


def test_an_uncoded_refusal_keeps_only_its_english_reason(db_session):
    contract = _contract(db_session)

    with patch(
        'src.controller.data_contracts_manager.DataContractsManager.transition_status',
        side_effect=ValueError('Invalid transition'),
    ):
        _complete(db_session, contract, approved=True)

    for notice in db_session.query(NotificationDb).all():
        i18n = json.loads(notice.data)['i18n']
        assert 'error' not in i18n
        assert i18n['params']['reason'] == 'Invalid transition'
