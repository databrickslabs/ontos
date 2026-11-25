"""A clarification asked of an approval step is "no decision yet".

Any approval step with config.on_clarify accepts a clarification; the run then
ends at a pass step. The entity must keep its status (only the notification
goes out), whatever the request type: a clarified data product review is not
activated, a clarified concept review does not send the concept back to
changes_requested.
"""
import json
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.common.workflow_executor import ClarifyNotSupportedError, WorkflowExecutor
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


def _workflow(db, entity_type, trigger_type=TriggerType.ON_REQUEST_REVIEW):
    db_workflow = process_workflow_repo.create(db, ProcessWorkflowCreate(
        name=f'review-{uuid.uuid4().hex[:6]}',
        trigger=WorkflowTrigger(type=trigger_type, entity_types=[entity_type]),
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


def _paused(db, workflow, entity_type, entity_id, name,
            trigger_type=TriggerType.ON_REQUEST_REVIEW):
    execution = WorkflowExecutor(db).execute_workflow(
        workflow=workflow, entity={'id': entity_id, 'name': name}, entity_type=entity_type,
        entity_id=entity_id, entity_name=name, user_email=REQUESTER,
        trigger_context=TriggerContext(
            entity_type=entity_type, entity_id=entity_id, entity_name=name,
            trigger_type=trigger_type, user_email=REQUESTER,
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


def _access_request_execution(db):
    request_id = str(uuid.uuid4())
    execution = _paused(
        db, _workflow(db, EntityType.ACCESS_GRANT, TriggerType.ON_REQUEST_ACCESS),
        'access_grant', request_id, 'requester', TriggerType.ON_REQUEST_ACCESS,
    )
    return execution


def test_an_access_request_step_refuses_a_clarification(db_session):
    # An access request has no "waiting for the requester" state (pending, approved,
    # denied, expired, cancelled): the approver decides it or leaves it pending
    execution = _access_request_execution(db_session)

    assert WorkflowExecutor(db_session).clarify_refusal(execution.id) == 'clarify_not_supported'
    with pytest.raises(ClarifyNotSupportedError):
        _decide(db_session, execution, clarify=True)

    from src.repositories.process_workflows_repository import workflow_execution_repo
    # execute_workflow returns the pydantic model: read the ORM row back
    assert workflow_execution_repo.get(db_session, execution.id).status == 'paused'


def test_an_access_request_step_still_takes_a_decision(db_session):
    execution = _access_request_execution(db_session)

    result = _decide(db_session, execution, clarify=False)

    assert result.status.value == 'succeeded'


def _offered(db, execution):
    from src.db_models.notifications import NotificationDb

    rows = [
        json.loads(n.action_payload) for n in db.query(NotificationDb).all()
        if n.action_payload and execution.id in n.action_payload
    ]
    assert rows
    return [r.get('can_clarify') for r in rows]


def test_the_approval_notice_of_an_access_request_does_not_offer_a_clarification(db_session):
    execution = _access_request_execution(db_session)

    assert _offered(db_session, execution) == [False] * len(_offered(db_session, execution))


def test_the_approval_notice_of_a_review_offers_a_clarification(db_session):
    product = _product(db_session)
    execution = _paused(
        db_session, _workflow(db_session, EntityType.DATA_PRODUCT), 'data_product',
        product.id, product.name,
    )

    assert all(_offered(db_session, execution))


def test_the_approval_of_an_access_request_does_not_offer_a_clarification():
    from src.common.workflow_executor import _takes_clarification

    assert not _takes_clarification('access_grant')
    assert not _takes_clarification('ACCESS_GRANT')
    assert _takes_clarification('data_product')
    assert _takes_clarification(None)


def test_a_review_that_has_no_request_state_does_not_close_one_when_clarified():
    from src.common.workflow_executor import _clarification_closes_request

    assert _clarification_closes_request('data_product', 'on_request_status_change')
    assert _clarification_closes_request('data_contract', TriggerType.ON_REQUEST_STATUS_CHANGE)
    assert _clarification_closes_request('metric_view', 'ON_REQUEST_DEFINITION_CHANGE')
    assert not _clarification_closes_request('data_product', 'on_request_review')
    assert not _clarification_closes_request('data_contract', 'on_request_deploy')
    assert not _clarification_closes_request('metric_view', 'on_request_status_change')
