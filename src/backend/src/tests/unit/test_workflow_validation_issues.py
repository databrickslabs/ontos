"""Workflow validation errors carry a code and parameters the designer translates.

A refused save used to return only English text (``detail.errors``), which the
designer showed as is. The English list stays for older clients.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from src.controller.workflows_manager import WorkflowsManager
from src.models.process_workflows import (
    ProcessWorkflowCreate,
    StepType,
    TriggerType,
    WorkflowStepCreate,
    WorkflowTrigger,
)
from src.routes.workflows_routes import create_workflow


def _workflow(*steps: WorkflowStepCreate, name: str = 'Issues') -> ProcessWorkflowCreate:
    return ProcessWorkflowCreate(
        name=name,
        trigger=WorkflowTrigger(type=TriggerType.MANUAL, entity_types=['data_product']),
        steps=list(steps),
    )


def _step(step_id: str, **kwargs) -> WorkflowStepCreate:
    kwargs.setdefault('step_type', StepType.PASS)
    return WorkflowStepCreate(step_id=step_id, name=step_id.title(), order=0, **kwargs)


def test_an_unknown_step_reference_has_a_code_and_params(db_session):
    result = WorkflowsManager(db_session).validate_workflow(
        _workflow(_step('prepare', step_type=StepType.CONDITIONAL,
                        config={'condition': "obj.name = 'x'"}, on_pass='old-check'))
    )

    assert not result.valid
    assert result.errors == ["Step 'prepare' references unknown step 'old-check' in on_pass"]
    [issue] = result.issues
    assert issue.code == 'step_unknown_reference'
    assert issue.params == {'step': 'prepare', 'target': 'old-check', 'field': 'on_pass'}
    assert issue.message == result.errors[0]


def test_each_error_has_an_issue(db_session):
    result = WorkflowsManager(db_session).validate_workflow(
        _workflow(
            _step('a', step_type=StepType.VALIDATION, config={}),
            _step('a', step_type=StepType.CONDITIONAL, config={'condition': "obj.name == 'x'"}),
            name=' ',
        )
    )

    codes = [issue.code for issue in result.issues]
    assert codes == [
        'workflow_name_required',
        'duplicate_step_ids',
        'step_config_missing',
        'condition_syntax_error',
    ]
    assert [issue.message for issue in result.issues] == result.errors
    missing = result.issues[2]
    assert missing.params == {'step': 'a', 'fields': ['rule']}
    syntax = result.issues[3]
    assert syntax.params['step'] == 'a' and syntax.params['line'] == 1


def test_a_valid_workflow_has_no_issues(db_session):
    result = WorkflowsManager(db_session).validate_workflow(_workflow(_step('done')))

    assert result.valid and result.errors == [] and result.issues == []


def test_a_refused_save_returns_the_code_the_issues_and_the_english_list(db_session):
    manager = WorkflowsManager(db_session)
    workflow = _workflow(_step('prepare', on_pass='old-check'))

    with pytest.raises(HTTPException) as raised:
        asyncio.run(create_workflow(
            request=MagicMock(), workflow=workflow, db=db_session,
            audit_manager=MagicMock(), current_user=None, manager=manager,
        ))

    assert raised.value.status_code == 400
    detail = raised.value.detail
    assert detail['code'] == 'workflow_invalid'
    assert detail['errors'] == ["Step 'prepare' references unknown step 'old-check' in on_pass"]
    assert detail['message'] == detail['errors'][0]
    assert detail['params']['issues'] == [{
        'code': 'step_unknown_reference',
        'message': detail['errors'][0],
        'params': {'step': 'prepare', 'target': 'old-check', 'field': 'on_pass'},
    }]
