"""A request whose workflow fails says so instead of promising a decision (#1065).

The requester gets a code, never the step's error text (it can carry exception text).
"""
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


def test_a_failed_workflow_reports_a_code(caplog):
    failed = _execution(
        ExecutionStatus.FAILED, error='Request was rejected',
        steps=[('ask', 'Could not resolve any approvers'), ('rejected', 'Request was rejected')],
    )

    # Only this workflow failed (total failure)
    with caplog.at_level('WARNING'):
        outcome = request_workflow_outcome([failed])

    assert outcome == {
        'workflow_triggered': False, 'execution_id': failed.id, 'workflow_status': 'failed',
        'workflow_error_code': 'request_workflow_failed',
        'workflow_error_params': {'workflow': 'Review'},
    }
    assert request_submitted_message('Publish', outcome) == (
        'Publish request submitted, but its workflow could not start. '
        'Please contact an administrator.'
    )
    # The first failed step's error stays in the server log
    assert 'Could not resolve any approvers' in caplog.text


def test_an_exception_text_does_not_reach_the_requester():
    sql_error = (
        "SQL execution FAILED: [TABLE_OR_VIEW_NOT_FOUND] The table `main.hr.salaries` "
        "cannot be found (SQLSTATE 42P01)"
    )
    failed = _execution(ExecutionStatus.FAILED, error=sql_error, steps=[('check', sql_error)])

    outcome = request_workflow_outcome([failed])
    response = {**outcome, 'message': request_submitted_message('Review', outcome)}

    assert 'salaries' not in json.dumps(response)
    assert 'SQLSTATE' not in json.dumps(response)


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
    assert result['workflow_error_code'] == 'request_workflow_failed'
    assert 'No approvers configured' not in json.dumps(result)
    assert result['message'] == (
        'Review request submitted, but its workflow could not start. '
        'Please contact an administrator.'
    )
    [change] = change_log_manager.get_changes_for_entity(db_session, 'data_contract', contract.id)
    assert change.details['workflow_triggered'] is False
    assert change.details['workflow_error_code'] == 'request_workflow_failed'


def test_partial_failure_paused_and_failed(caplog):
    """When one workflow is paused (waiting for approval) and another failed,
    it's a partial failure: the request reached at least one approver."""
    failed = _execution(
        ExecutionStatus.FAILED, error='Some step error',
        steps=[('step1', 'Some step error')],
    )
    paused = _execution(ExecutionStatus.PAUSED)

    with caplog.at_level('WARNING'):
        outcome = request_workflow_outcome([paused, failed])

    assert outcome == {
        'workflow_triggered': True, 'execution_id': paused.id, 'workflow_status': 'partially_failed',
        'workflow_error_code': 'request_workflow_partially_failed',
        'workflow_error_params': {'failed_workflows': ['Review']},
    }
    # The failed step's error stays in the server log
    assert 'Some step error' in caplog.text


def test_partial_failure_succeeded_and_failed(caplog):
    """When one workflow succeeded and another failed, it's a partial failure."""
    failed = _execution(
        ExecutionStatus.FAILED, error='Some step error',
        steps=[('step1', 'Some step error')],
    )
    succeeded = _execution(ExecutionStatus.SUCCEEDED)

    with caplog.at_level('WARNING'):
        outcome = request_workflow_outcome([succeeded, failed])

    assert outcome == {
        'workflow_triggered': True, 'execution_id': succeeded.id, 'workflow_status': 'partially_failed',
        'workflow_error_code': 'request_workflow_partially_failed',
        'workflow_error_params': {'failed_workflows': ['Review']},
    }


def test_partial_failure_multiple_failed_and_paused(caplog):
    """Multiple failed workflows and one paused: partial failure."""
    failed1 = _execution(
        ExecutionStatus.FAILED, error='Error 1',
        steps=[('s1', 'Error 1')],
    )
    failed1.workflow_name = 'Review'
    failed2 = _execution(
        ExecutionStatus.FAILED, error='Error 2',
        steps=[('s2', 'Error 2')],
    )
    failed2.workflow_name = 'Audit'
    paused = _execution(ExecutionStatus.PAUSED)
    paused.workflow_name = 'Approval'

    with caplog.at_level('WARNING'):
        outcome = request_workflow_outcome([paused, failed1, failed2])

    assert outcome['workflow_triggered'] is True
    assert outcome['workflow_status'] == 'partially_failed'
    assert set(outcome['workflow_error_params']['failed_workflows']) == {'Review', 'Audit'}


def test_all_failed_workflows(caplog):
    """When all workflows fail, it's total failure."""
    failed1 = _execution(
        ExecutionStatus.FAILED, error='Error 1',
        steps=[('s1', 'Error 1')],
    )
    failed1.workflow_name = 'Review'
    failed2 = _execution(
        ExecutionStatus.FAILED, error='Error 2',
        steps=[('s2', 'Error 2')],
    )
    failed2.workflow_name = 'Audit'

    with caplog.at_level('WARNING'):
        outcome = request_workflow_outcome([failed1, failed2])

    assert outcome == {
        'workflow_triggered': False, 'execution_id': failed1.id, 'workflow_status': 'failed',
        'workflow_error_code': 'request_workflow_failed',
        'workflow_error_params': {'workflow': 'Review'},
    }


def test_a_product_publication_request_returns_the_workflow_failure():
    from src.routes import data_product_routes

    failed = _execution(
        ExecutionStatus.FAILED,
        steps=[('approval-gate', 'psycopg2.errors.UndefinedTable: relation "x" does not exist')],
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
    assert body['workflow_error_code'] == 'request_workflow_failed'
    assert body['workflow_error_params'] == {'workflow': 'Review'}
    assert 'psycopg2' not in response.body.decode()
    assert 'could not start' in body['message']
