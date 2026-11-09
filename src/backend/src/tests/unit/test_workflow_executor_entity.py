"""The execution model returned by the executor carries the trigger entity."""
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.common.workflow_executor import WorkflowExecutor
from src.models.process_workflows import TriggerContext, TriggerType


def _db_execution(trigger_context):
    return SimpleNamespace(
        id='exec-1',
        workflow_id='wf-1',
        trigger_context=trigger_context,
        status='succeeded',
        current_step_id=None,
        success_count=1,
        failure_count=0,
        error_message=None,
        started_at=None,
        finished_at=None,
        triggered_by='user@example.com',
        step_executions=[],
    )


def _executor():
    return WorkflowExecutor(MagicMock())


def test_db_to_model_carries_entity_from_trigger_context():
    tc = TriggerContext(
        entity_type='data_product',
        entity_id='dp-1',
        entity_name='Orders',
        trigger_type=TriggerType.MANUAL,
    )
    model = _executor()._db_to_model(
        _db_execution(tc.model_dump_json()), 'My workflow'
    )
    assert model.entity_type == 'data_product'
    assert model.entity_id == 'dp-1'
    assert model.entity_name == 'Orders'


def test_db_to_model_without_trigger_context_leaves_entity_empty():
    model = _executor()._db_to_model(_db_execution(None), 'My workflow')
    assert model.entity_type is None
    assert model.entity_id is None
    assert model.entity_name is None


def test_db_to_model_ignores_invalid_trigger_context():
    model = _executor()._db_to_model(_db_execution('not json'), 'My workflow')
    assert model.entity_id is None


@pytest.mark.parametrize(
    'entity_name,entity_id,expected',
    [
        ('Orders', 'main.sales.orders', 'table: Orders'),
        (None, 'main.sales.orders', 'table: main.sales.orders'),
        ('', 'main.sales.orders', 'table: main.sales.orders'),
        (None, '', None),
    ],
)
def test_notification_subtitle_falls_back_to_entity_id(entity_name, entity_id, expected):
    from src.common.workflow_executor import NotificationStepHandler, StepContext

    ctx = StepContext(
        entity={}, entity_type='table', entity_id=entity_id, entity_name=entity_name,
        user_email='user@example.com', trigger_context=None, execution_id='exec-1',
        workflow_id='wf-1', workflow_name='Test Workflow', step_results={},
    )
    handler = NotificationStepHandler(
        db=MagicMock(),
        config={'recipients': 'requester', 'template': 'validation_passed', 'channels': ['in_app']},
    )
    with patch('src.repositories.notification_repository.notification_repo') as repo:
        result = handler.execute(ctx)
    assert result.passed is True
    created = repo.create.call_args.kwargs['obj_in']
    assert created.subtitle == expected
