"""A clarification asked of an approval step is "no decision yet".

Any approval step with config.on_clarify accepts a clarification; the run then
ends at a pass step. The entity must keep its status (only the notification
goes out), whatever the request type: a clarified data product review is not
activated, a clarified concept review does not send the concept back to
changes_requested.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.common.workflow_executor import WorkflowExecutor
from src.controller.workflows_manager import WorkflowsManager
from src.db_models.data_products import DataProductDb
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


def _workflow(db, entity_type):
    db_workflow = process_workflow_repo.create(db, ProcessWorkflowCreate(
        name=f'review-{uuid.uuid4().hex[:6]}',
        trigger=WorkflowTrigger(type=TriggerType.ON_REQUEST_REVIEW, entity_types=[entity_type]),
        steps=[
            WorkflowStepCreate(
                step_id='approve', step_type=StepType.APPROVAL,
                config={'approvers': 'steward@example.com', 'on_clarify': 'notify-clarify'},
                on_pass='done', on_fail='done', order=0,
            ),
            WorkflowStepCreate(
                step_id='notify-clarify', step_type=StepType.NOTIFICATION,
                config={'recipients': REQUESTER, 'template': 'request_approved',
                        'custom_message': 'Please clarify.'},
                on_pass='done', order=1,
            ),
            WorkflowStepCreate(step_id='done', step_type=StepType.PASS, order=2),
        ],
    ))
    return WorkflowsManager(db).get_workflow(db_workflow.id)


def _paused(db, workflow, entity_type, entity_id, name):
    execution = WorkflowExecutor(db).execute_workflow(
        workflow=workflow, entity={'id': entity_id, 'name': name}, entity_type=entity_type,
        entity_id=entity_id, entity_name=name, user_email=REQUESTER,
        trigger_context=TriggerContext(
            entity_type=entity_type, entity_id=entity_id, entity_name=name,
            trigger_type=TriggerType.ON_REQUEST_REVIEW, user_email=REQUESTER,
        ),
    )
    assert execution.status.value == 'paused'
    return execution


def _decide(db, execution, *, clarify):
    return WorkflowExecutor(db).resume_workflow(
        execution_id=execution.id, step_result=not clarify,
        result_data={'decision': 'clarify' if clarify else 'approved', 'message': 'Why?'},
        user_email='steward@example.com', clarify=clarify,
    )


def _product(db):
    product = DataProductDb(
        id=str(uuid.uuid4()), name='Sales', version='1.0.0', status='under_review',
    )
    db.add(product)
    db.commit()
    return product


def test_a_clarified_data_product_review_is_not_activated(db_session):
    product = _product(db_session)
    execution = _paused(
        db_session, _workflow(db_session, EntityType.DATA_PRODUCT), 'data_product',
        product.id, product.name,
    )

    result = _decide(db_session, execution, clarify=True)

    assert result.status.value == 'succeeded'
    db_session.refresh(product)
    assert product.status == 'under_review'


def test_an_approved_data_product_review_is_still_activated(db_session):
    product = _product(db_session)
    execution = _paused(
        db_session, _workflow(db_session, EntityType.DATA_PRODUCT), 'data_product',
        product.id, product.name,
    )

    _decide(db_session, execution, clarify=False)

    db_session.refresh(product)
    assert product.status == 'active'


def test_a_clarified_concept_review_leaves_the_concept_alone(db_session):
    iri = 'http://example.com/concepts#Thing'
    execution = _paused(
        db_session, _workflow(db_session, EntityType.ONTOLOGY_CONCEPT), 'ontology_concept',
        iri, 'Thing',
    )
    smm = MagicMock()

    with patch('src.common.app_state.get_app_state_manager', return_value=smm):
        _decide(db_session, execution, clarify=True)

    smm.apply_review_decision.assert_not_called()


def test_a_denied_concept_review_still_requests_changes(db_session):
    iri = 'http://example.com/concepts#Thing'
    execution = _paused(
        db_session, _workflow(db_session, EntityType.ONTOLOGY_CONCEPT), 'ontology_concept',
        iri, 'Thing',
    )
    smm = MagicMock()

    with patch('src.common.app_state.get_app_state_manager', return_value=smm):
        WorkflowExecutor(db_session).resume_workflow(
            execution_id=execution.id, step_result=False,
            result_data={'decision': 'denied', 'reason': 'No'},
            user_email='steward@example.com',
        )

    assert smm.apply_review_decision.call_args.kwargs['decision'] == 'changes_requested'
