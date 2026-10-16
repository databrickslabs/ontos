"""After an approval, 'requester' still means the user who made the request.

``resume_workflow`` builds the step context with ``user_email`` set to the
approver. Steps that address the requester (notifications, owner approvers,
the approval card, UC grants) read the requester from the trigger context.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.common.workflow_executor import (
    GrantPermissionsStepHandler,
    StepContext,
    _resolve_role_to_users,
)
from src.db_models.data_contracts import DataContractDb, DataContractTeamDb
from src.db_models.settings import AppRoleDb
from src.models.process_workflows import TriggerContext, TriggerType


def _resumed_context(entity_type='data_product', entity_id='product-1', **overrides):
    """Context as resume_workflow builds it: the approver is the acting user."""
    trigger = TriggerContext(
        entity_type=entity_type, entity_id=entity_id, entity_name='E',
        trigger_type=TriggerType.ON_REQUEST_ACCESS, user_email='requester@example.com',
    )
    defaults = dict(
        entity={}, entity_type=entity_type, entity_id=entity_id, entity_name='E',
        user_email='approver@example.com', trigger_context=trigger,
        execution_id='exec-1', workflow_id='wf-1', workflow_name='W', step_results={},
    )
    defaults.update(overrides)
    return StepContext(**defaults)


@pytest.mark.parametrize('token', ['requester', 'trigger_user'])
def test_requester_tokens_resolve_to_the_requester(db_session, token):
    assert _resolve_role_to_users(db_session, token, _resumed_context()) == [
        ('requester@example.com', None),
    ]


def test_without_a_trigger_context_the_acting_user_is_the_requester(db_session):
    context = SimpleNamespace(
        user_email='requester@example.com', entity={}, entity_type='data_product',
        entity_id='product-1', entity_name='E',
    )

    assert _resolve_role_to_users(db_session, 'requester', context) == [
        ('requester@example.com', None),
    ]


def test_a_later_owner_approval_leaves_out_the_requester_not_the_approver(db_session):
    db_session.add(AppRoleDb(id=str(uuid.uuid4()), name='Data Steward'))
    contract = DataContractDb(
        id=str(uuid.uuid4()), name='c', version='1.0.0', status='approved',
        version_family_id=str(uuid.uuid4()),
    )
    db_session.add(contract)
    db_session.flush()
    for username in ('requester@example.com', 'approver@example.com'):
        db_session.add(DataContractTeamDb(
            id=str(uuid.uuid4()), contract_id=contract.id, username=username, role='owner',
        ))
    db_session.flush()

    resolved = _resolve_role_to_users(
        db_session, 'ContractApprover', _resumed_context('data_contract', contract.id)
    )

    assert resolved == [('approver@example.com', None)]


def test_uc_grant_to_the_requester_goes_to_the_requester():
    handler = GrantPermissionsStepHandler(None, {
        'permission_type': 'SELECT', 'target_source': 'from_entity',
        'principal_source': 'requester',
    })
    context = _resumed_context(
        entity_type='table', entity_id='main.sales.orders',
        entity={'full_name': 'main.sales.orders'},
    )

    with patch('src.common.workspace_client.get_workspace_client',
               side_effect=RuntimeError('no workspace')):
        result = handler.execute(context)

    assert result.data['skipped'] is True
    assert result.data['principal'] == 'requester@example.com'
