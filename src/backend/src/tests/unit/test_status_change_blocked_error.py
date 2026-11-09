"""The blocked status change error carries a code and parameters (#1078).

When a before_status_change workflow blocks a status change, the API answers
``detail = {code: 'status_change_blocked', message, params}``: the message is
the English text it always was, and the parameters (statuses, and each
workflow's reason, with a code for the reasons the app writes) let the UI show
it in the user's language.
"""
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.common.api_errors import CodedValueError, coded_http_exception_handler
from src.common.workflow_triggers import (
    StatusChangeBlockedError,
    describe_failed_executions,
    failed_execution_reasons,
)
from src.models.process_workflows import (
    ExecutionStatus,
    StepExecutionStatus,
    WorkflowExecution,
    WorkflowStepExecutionResult,
)


def _execution(status, *, name='Gate', error=None, steps=(), current_step_name=None):
    return WorkflowExecution(
        workflow_id='wf-1', workflow_name=name, status=status, current_step_id='approve',
        current_step_name=current_step_name, error_message=error, step_executions=list(steps),
    )


def _failed_step(error, **data):
    return WorkflowStepExecutionResult(
        step_id='s', status=StepExecutionStatus.FAILED, passed=False,
        error_message=error, result_data=data or None,
    )


PAUSED = _execution(ExecutionStatus.PAUSED, name='Steward Gate', current_step_name='Steward approval')
AUTHORED = _execution(ExecutionStatus.FAILED, name='Owner Gate', error='Add an owner before activating')
LOAD_FAILED = _execution(ExecutionStatus.FAILED, name='Rule Gate', steps=[_failed_step(
    'Could not load data_product p-1 to evaluate the rule',
    error_code='rule_entity_load_failed',
    error_params={'entityType': 'data_product', 'entityId': 'p-1'},
)])
BARE = _execution(ExecutionStatus.CANCELLED, name='Old Gate')


class TestReasons:
    def test_each_reason_has_its_workflow_and_text_and_a_code_when_the_app_wrote_it(self):
        assert failed_execution_reasons([PAUSED, AUTHORED, LOAD_FAILED, BARE]) == [
            {'workflow': 'Steward Gate', 'text': 'waiting for approval (Steward approval)',
             'code': 'waiting_for_approval', 'params': {'step': 'Steward approval'}},
            {'workflow': 'Owner Gate', 'text': 'Add an owner before activating'},
            {'workflow': 'Rule Gate', 'text': 'Could not load data_product p-1 to evaluate the rule',
             'code': 'rule_entity_load_failed',
             'params': {'entityType': 'data_product', 'entityId': 'p-1'}},
            {'workflow': 'Old Gate', 'text': 'cancelled',
             'code': 'execution_status', 'params': {'status': 'cancelled'}},
        ]

    def test_the_english_text_is_unchanged(self):
        assert describe_failed_executions([PAUSED, AUTHORED, LOAD_FAILED, BARE]) == (
            'Steward Gate: waiting for approval (Steward approval); '
            'Owner Gate: Add an owner before activating; '
            'Rule Gate: Could not load data_product p-1 to evaluate the rule; '
            'Old Gate: cancelled'
        )


class TestBlockedError:
    def test_it_is_a_value_error_with_the_same_message(self):
        error = StatusChangeBlockedError('deprecated', 'active', [PAUSED, AUTHORED])

        assert isinstance(error, ValueError)
        assert str(error) == (
            "Status transition from 'deprecated' to 'active' blocked by workflow: "
            "Steward Gate: waiting for approval (Steward approval); "
            "Owner Gate: Add an owner before activating"
        )
        assert error.code == 'status_change_blocked'
        assert error.params == {
            'fromStatus': 'deprecated', 'toStatus': 'active',
            'reasons': failed_execution_reasons([PAUSED, AUTHORED]),
        }

    def test_the_product_and_contract_managers_raise_it(self, db_session):
        import uuid
        from pathlib import Path

        from src.controller.data_contracts_manager import DataContractsManager
        from src.controller.data_products_manager import DataProductsManager
        from src.db_models.data_contracts import DataContractDb
        from src.db_models.data_products import DataProductDb

        product = DataProductDb(
            id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct',
            name='Gated Product', version='1.0.0', status='approved',
        )
        contract = DataContractDb(
            id=str(uuid.uuid4()), name='gated_contract', version='1.0.0', status='draft',
        )
        db_session.add_all([product, contract])
        db_session.commit()

        with patch('src.common.workflow_triggers.get_trigger_registry') as get_registry:
            get_registry.return_value.before_status_change.return_value = (False, [AUTHORED])
            with pytest.raises(StatusChangeBlockedError) as on_product:
                DataProductsManager(db=db_session, ws_client=MagicMock()).transition_status(
                    product.id, 'active', 'test@example.com')
            with pytest.raises(StatusChangeBlockedError) as on_contract:
                DataContractsManager(data_dir=Path('/tmp')).transition_status(
                    db=db_session, contract_id=contract.id, new_status='proposed',
                    current_user='test@example.com')

        assert on_product.value.params['fromStatus'] == 'approved'
        assert on_product.value.params['toStatus'] == 'active'
        assert on_contract.value.params['toStatus'] == 'proposed'
        assert str(on_contract.value) == (
            "Status transition from 'draft' to 'proposed' blocked by workflow: "
            "Owner Gate: Add an owner before activating"
        )


class TestHttpAnswer:
    """Routes keep turning a ValueError into ``HTTPException(detail=str(e))``."""

    @pytest.fixture
    def client(self):
        app = FastAPI()
        app.add_exception_handler(StarletteHTTPException, coded_http_exception_handler)

        def as_route(error):
            try:
                raise error
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

        @app.post('/blocked')
        def blocked():
            as_route(StatusChangeBlockedError('approved', 'active', [AUTHORED]))

        @app.post('/other')
        def other():
            as_route(ValueError('Invalid status transition from draft to active'))

        @app.post('/rewritten')
        def rewritten():
            try:
                raise StatusChangeBlockedError('approved', 'active', [AUTHORED])
            except ValueError:
                raise HTTPException(status_code=500, detail='Failed to change status')

        @app.post('/plain')
        def plain():
            raise HTTPException(status_code=404, detail='Product not found', headers={'X-A': 'b'})

        return TestClient(app)

    def test_the_blocked_error_is_answered_with_its_code_and_parameters(self, client):
        response = client.post('/blocked')

        assert response.status_code == 400
        assert response.json() == {'detail': {
            'code': 'status_change_blocked',
            'message': (
                "Status transition from 'approved' to 'active' blocked by workflow: "
                "Owner Gate: Add an owner before activating"
            ),
            'params': {
                'fromStatus': 'approved', 'toStatus': 'active',
                'reasons': [{'workflow': 'Owner Gate', 'text': 'Add an owner before activating'}],
            },
        }}

    def test_other_errors_are_answered_as_before(self, client):
        assert client.post('/other').json() == {
            'detail': 'Invalid status transition from draft to active'}
        assert client.post('/rewritten').json() == {'detail': 'Failed to change status'}
        plain = client.post('/plain')
        assert plain.status_code == 404
        assert plain.json() == {'detail': 'Product not found'}
        assert plain.headers['X-A'] == 'b'

    def test_the_app_answers_coded_errors_this_way(self):
        from src.app import app

        assert app.exception_handlers[StarletteHTTPException] is coded_http_exception_handler

    def test_a_coded_error_without_a_code_is_still_a_value_error(self):
        assert isinstance(CodedValueError('x'), ValueError)
