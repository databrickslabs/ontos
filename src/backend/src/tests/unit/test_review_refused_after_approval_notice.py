"""A review or status change request approved in its workflow, then not applied.

The default review workflows notify the requester right after the approval
("Request Approved"); the status change runs when the workflow completes. When
a before_status_change gate refused it, the requester also got "Contract status
not changed", two notices that contradict each other. The approval notice of
that run is now withdrawn, so the requester gets only the "not applied" one.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from unittest.mock import MagicMock, patch

import pytest

from src.common.workflow_executor import WorkflowExecutor
from src.controller.workflows_manager import WorkflowsManager
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb
from src.db_models.notifications import NotificationDb
from src.models.process_workflows import (
    EntityType,
    ProcessWorkflowCreate,
    StepType,
    TriggerContext,
    TriggerType,
    WorkflowStepCreate,
    WorkflowTrigger,
)
from src.repositories.process_workflows_repository import process_workflow_repo

REQUESTER = 'requester@example.com'


def _review_workflow(db, entity_type, approved_template, trigger=TriggerType.ON_REQUEST_REVIEW):
    """Approval, then the requester's approved / rejected notice, as the defaults do.

    The notices name the requester by email: the defaults' ``requester`` means
    the requester after a resume only with #1017.
    """
    db_workflow = process_workflow_repo.create(db, ProcessWorkflowCreate(
        name=f'review-{uuid.uuid4().hex[:6]}',
        trigger=WorkflowTrigger(type=trigger, entity_types=[entity_type]),
        steps=[
            WorkflowStepCreate(
                step_id='request-approval', step_type=StepType.APPROVAL,
                config={'approvers': 'steward@example.com'},
                on_pass='notify-approved', on_fail='notify-rejected', order=0,
            ),
            WorkflowStepCreate(
                step_id='notify-approved', step_type=StepType.NOTIFICATION,
                config={'recipients': REQUESTER, 'template': approved_template,
                        'custom_message': 'Your request has been approved.'},
                on_pass='success', order=1,
            ),
            WorkflowStepCreate(
                step_id='notify-rejected', step_type=StepType.NOTIFICATION,
                config={'recipients': REQUESTER, 'template': 'request_rejected'},
                order=2,
            ),
            WorkflowStepCreate(step_id='success', step_type=StepType.PASS, order=3),
        ],
    ))
    return WorkflowsManager(db).get_workflow(db_workflow.id)


def _contract(db):
    contract = DataContractDb(
        id=str(uuid.uuid4()), name='Orders', version='1.0.0', status='proposed',
        version_family_id=str(uuid.uuid4()),
    )
    db.add(contract)
    db.commit()
    return contract


def _product(db):
    product = DataProductDb(
        id=str(uuid.uuid4()), name='Sales', version='1.0.0', status='under_review',
    )
    db.add(product)
    db.commit()
    return product


def _paused(db, workflow, entity_type, entity, trigger=TriggerType.ON_REQUEST_REVIEW, **context):
    execution = WorkflowExecutor(db).execute_workflow(
        workflow=workflow,
        entity={'id': entity.id, 'name': entity.name},
        entity_type=entity_type,
        entity_id=entity.id,
        entity_name=entity.name,
        user_email=REQUESTER,
        trigger_context=TriggerContext(
            entity_type=entity_type, entity_id=entity.id, entity_name=entity.name,
            trigger_type=trigger, user_email=REQUESTER, **context,
        ),
    )
    assert execution.status.value == 'paused'
    return execution


def _approve(db, execution, gate_passes):
    registry = MagicMock()
    registry.before_status_change.return_value = (gate_passes, [])
    with patch('src.common.workflow_triggers.get_trigger_registry', return_value=registry):
        WorkflowExecutor(db).resume_workflow(
            execution_id=execution.id, step_result=True,
            result_data={'decision': 'approved', 'reason': None},
            user_email='steward@example.com',
        )


def _requester_titles(db):
    return sorted(
        n.title for n in db.query(NotificationDb).filter(NotificationDb.recipient == REQUESTER).all()
    )


def test_a_refused_contract_approval_leaves_the_requester_one_notice(db_session):
    contract = _contract(db_session)
    workflow = _review_workflow(db_session, EntityType.DATA_CONTRACT, 'request_approved')
    execution = _paused(db_session, workflow, 'data_contract', contract)

    _approve(db_session, execution, gate_passes=False)

    db_session.refresh(contract)
    assert contract.status == 'proposed'
    assert _requester_titles(db_session) == ['Contract status not changed']


def test_an_applied_contract_approval_keeps_the_approved_notice(db_session):
    contract = _contract(db_session)
    workflow = _review_workflow(db_session, EntityType.DATA_CONTRACT, 'request_approved')
    execution = _paused(db_session, workflow, 'data_contract', contract)

    _approve(db_session, execution, gate_passes=True)

    db_session.refresh(contract)
    assert contract.status == 'approved'
    assert _requester_titles(db_session) == ['Request Approved']


@pytest.mark.parametrize('template', ['request_approved', 'product_approved'])
def test_a_refused_product_activation_leaves_the_requester_one_notice(db_session, template):
    product = _product(db_session)
    workflow = _review_workflow(db_session, EntityType.DATA_PRODUCT, template)
    execution = _paused(db_session, workflow, 'data_product', product)

    _approve(db_session, execution, gate_passes=False)

    db_session.refresh(product)
    assert product.status == 'under_review'
    assert _requester_titles(db_session) == ['Status change not applied']


def _request_deprecation(db, product):
    workflow = _review_workflow(
        db, EntityType.DATA_PRODUCT, 'request_approved', TriggerType.ON_REQUEST_STATUS_CHANGE,
    )
    return _paused(
        db, workflow, 'data_product', product, TriggerType.ON_REQUEST_STATUS_CHANGE,
        from_status='active', to_status='deprecated',
    )


def test_a_refused_requested_status_change_leaves_the_requester_one_notice(db_session):
    product = _product(db_session)
    product.status = 'active'
    db_session.commit()
    execution = _request_deprecation(db_session, product)

    _approve(db_session, execution, gate_passes=False)

    db_session.refresh(product)
    assert product.status == 'active'
    assert _requester_titles(db_session) == ['Status change not applied']


def test_a_requested_status_change_made_stale_leaves_the_requester_one_notice(db_session):
    product = _product(db_session)
    product.status = 'active'
    db_session.commit()
    execution = _request_deprecation(db_session, product)
    product.status = 'draft'  # changed while the request waited
    db_session.commit()

    _approve(db_session, execution, gate_passes=True)

    db_session.refresh(product)
    assert product.status == 'draft'
    assert _requester_titles(db_session) == ['Status change not applied']
