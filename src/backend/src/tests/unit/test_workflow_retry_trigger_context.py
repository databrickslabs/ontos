"""A retried execution runs with the trigger context it was started with.

The retry route re-ran the workflow without it, so the steps saw no trigger
type: a retried on_delete policy check tried to load the deleted entity and
failed with rule_entity_not_found instead of evaluating the payload.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import asyncio
import json
import uuid
from unittest.mock import MagicMock

import pytest

from src.common.workflow_executor import WorkflowExecutor
from src.controller.workflows_manager import WorkflowsManager
from src.db_models.compliance import CompliancePolicyDb
from src.models.process_workflows import (
    EntityType,
    ProcessWorkflowCreate,
    StepType,
    TriggerContext,
    TriggerType,
    WorkflowStepCreate,
    WorkflowTrigger,
)
from src.repositories.process_workflows_repository import (
    process_workflow_repo,
    workflow_execution_repo,
)
from src.routes.workflows_routes import retry_execution


def _on_delete_workflow(db):
    policy = CompliancePolicyDb(
        id=str(uuid.uuid4()), name='Gate', is_active=True,
        rule="MATCH (p:data_product) ASSERT p.status = 'active'",
    )
    db.add(policy)
    db.flush()
    db_workflow = process_workflow_repo.create(db, ProcessWorkflowCreate(
        name=f'wf-{uuid.uuid4().hex[:6]}',
        trigger=WorkflowTrigger(
            type=TriggerType.ON_DELETE, entity_types=[EntityType.DATA_PRODUCT],
        ),
        steps=[WorkflowStepCreate(
            step_id='gate', step_type=StepType.POLICY_CHECK,
            config={'policy_id': policy.id}, order=0,
        )],
    ))
    return WorkflowsManager(db).get_workflow(db_workflow.id)


def _failed_on_delete_execution(db, workflow):
    # The product is gone: on_delete fires after the row is deleted
    product_id = str(uuid.uuid4())
    payload = {'product_id': product_id, 'name': 'gone', 'status': 'active'}
    execution = WorkflowExecutor(db).execute_workflow(
        workflow=workflow, entity=payload, entity_type='data_product',
        entity_id=product_id, entity_name='gone', user_email='pat@example.com',
        trigger_context=TriggerContext(
            entity_type='data_product', entity_id=product_id, entity_name='gone',
            trigger_type=TriggerType.ON_DELETE, entity_data=payload,
            user_email='pat@example.com',
        ),
    )
    # It failed for another reason (e.g. a step that later got fixed)
    db_execution = workflow_execution_repo.get(db, execution.id)
    db_execution.status = 'failed'
    db.commit()
    return execution


def _retry(db, execution_id):
    return asyncio.run(retry_execution(
        execution_id=execution_id, request=MagicMock(), db=db,
        audit_manager=MagicMock(), current_user=None,
        executor=WorkflowExecutor(db), _=True,
    ))


def _gate_result(db, execution_id):
    db.expire_all()
    [step] = workflow_execution_repo.get(db, execution_id).step_executions
    return step.passed, json.loads(step.result_data or '{}')


def test_a_retried_on_delete_execution_evaluates_the_payload(db_session):
    workflow = _on_delete_workflow(db_session)
    execution = _failed_on_delete_execution(db_session, workflow)

    response = _retry(db_session, execution.id)

    passed, data = _gate_result(db_session, execution.id)
    assert not data.get('error_code')
    assert passed is True
    assert response['status'] == 'succeeded'


@pytest.mark.parametrize('stored', ['not json', '["a list"]'], ids=['not-json', 'not-a-dict'])
def test_a_trigger_context_that_cannot_be_read_does_not_stop_the_retry(db_session, stored):
    # As on resume: the workflow is re-run without a context instead of a 500
    workflow = _on_delete_workflow(db_session)
    execution = _failed_on_delete_execution(db_session, workflow)
    db_execution = workflow_execution_repo.get(db_session, execution.id)
    db_execution.trigger_context = stored
    db_session.commit()

    response = _retry(db_session, execution.id)

    assert response['execution_id'] == execution.id
    # No entity type, so the data_product policy doesn't apply
    passed, data = _gate_result(db_session, execution.id)
    assert passed is True
    assert data['not_applicable'] is True
