"""A request whose workflow fails says so instead of promising a decision (#1065)."""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import asyncio
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.common.workflow_triggers import request_submitted_message, request_workflow_outcome
from src.controller.change_log_manager import change_log_manager
from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import DataContractDb, SchemaObjectDb
from src.models.process_workflows import (
    ExecutionStatus, ProcessWorkflowCreate, StepExecutionStatus, StepType, TriggerType,
    WorkflowExecution, WorkflowStepCreate, WorkflowStepExecutionResult, WorkflowTrigger,
)
from src.models.process_workflows import EntityType
from src.repositories.process_workflows_repository import process_workflow_repo


def _execution(status, steps=(), error=None):
    return WorkflowExecution(
        workflow_id='wf', status=status, error_message=error, workflow_name='Review',
        step_executions=[
            WorkflowStepExecutionResult(step_id=step_id, status=StepExecutionStatus.FAILED,
                                        passed=False, error_message=message)
            for step_id, message in steps
        ],
    )


def test_no_workflow_and_a_paused_workflow():
    assert request_workflow_outcome([]) == {'workflow_triggered': False}

    paused = _execution(ExecutionStatus.PAUSED)
    assert request_workflow_outcome([paused]) == {
        'workflow_triggered': True, 'execution_id': paused.id, 'workflow_status': 'paused',
    }
    assert request_submitted_message('Review', request_workflow_outcome([paused])) == (
        'Review request submitted successfully'
    )


def test_a_failed_workflow_reports_its_first_failed_step():
    failed = _execution(
        ExecutionStatus.FAILED, error='Request was rejected',
        steps=[('ask', 'Could not resolve any approvers'), ('rejected', 'Request was rejected')],
    )

    # Another matching workflow paused: the request still did not reach everyone
    outcome = request_workflow_outcome([_execution(ExecutionStatus.PAUSED), failed])

    assert outcome == {
        'workflow_triggered': False, 'execution_id': failed.id, 'workflow_status': 'failed',
        'workflow_error': 'Could not resolve any approvers',
    }
    assert request_submitted_message('Publish', outcome) == (
        'Publish request submitted, but its workflow failed: Could not resolve any approvers'
    )


def _review_workflow(db):
    """A contract review workflow whose approval step has no approvers."""
    process_workflow_repo.create(db, ProcessWorkflowCreate(
        name=f'Review {uuid.uuid4().hex[:6]}', is_active=True,
        trigger=WorkflowTrigger(type=TriggerType.ON_REQUEST_REVIEW,
                                entity_types=[EntityType.DATA_CONTRACT]),
        steps=[
            WorkflowStepCreate(step_id='ask', step_type=StepType.APPROVAL,
                               config={'approvers': ''}, on_pass='done', on_fail='rejected'),
            WorkflowStepCreate(step_id='done', step_type=StepType.PASS),
            WorkflowStepCreate(step_id='rejected', step_type=StepType.FAIL,
                               config={'message': 'Review request was rejected'}),
        ],
    ))


def _draft_contract(db):
    contract = DataContractDb(
        id=str(uuid.uuid4()), name='c', version='1.0.0', status='draft',
        version_family_id=str(uuid.uuid4()),
    )
    db.add(contract)
    db.flush()
    db.add(SchemaObjectDb(contract_id=contract.id, name='accounts'))
    db.flush()
    return contract


def test_a_contract_review_whose_approval_cannot_be_routed(db_session):
    _review_workflow(db_session)
    contract = _draft_contract(db_session)
    manager = DataContractsManager(data_dir=Path('/tmp'))

    with patch.object(manager, '_update_search_index'):
        result = manager.request_steward_review(
            db=db_session, notifications_manager=MagicMock(), contract_id=contract.id,
            requester_email='alice@example.com', current_user='alice',
        )

    assert result['workflow_status'] == 'failed'
    assert result['workflow_error'] == 'No approvers configured'
    assert result['message'] == (
        'Review request submitted, but its workflow failed: No approvers configured'
    )
    [change] = change_log_manager.get_changes_for_entity(db_session, 'data_contract', contract.id)
    assert change.details['workflow_triggered'] is False
    assert change.details['workflow_error'] == 'No approvers configured'


def test_a_product_publication_request_returns_the_workflow_failure():
    from src.routes import data_product_routes

    failed = _execution(
        ExecutionStatus.FAILED, steps=[('approval-gate', 'Could not resolve any approvers')],
    )
    manager = MagicMock()
    manager._repo.get.return_value = SimpleNamespace(name='p', status='active')
    request = MagicMock()
    request.client.host = '127.0.0.1'

    with patch.object(data_product_routes, 'get_trigger_registry') as registry:
        registry.return_value.on_request_publish.return_value = [failed]
        response = asyncio.run(data_product_routes.request_publish_product(
            product_id='p-1', request=request, db=MagicMock(), audit_manager=MagicMock(),
            change_log_manager=MagicMock(), current_user=SimpleNamespace(username='alice'),
            body={'scope': 'organization'}, manager=manager, _=True,
        ))

    body = json.loads(response.body)
    assert body['workflow_status'] == 'failed'
    assert body['workflow_error'] == 'Could not resolve any approvers'
    assert 'workflow failed' in body['message']
