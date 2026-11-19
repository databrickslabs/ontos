"""Steps that commit or act outside the app can't run in a before_update gate (#1403 review).

An entity action certifies, publishes or unpublishes and commits as the gate runs; an
asset review is created and committed; a delivery and a UC grant act outside the
database. A gate of [Publish] then [a failing check] refused the update and left the
contract published. Saving such a workflow is refused; one stored before fails at
that step, before it acts.
"""
import uuid
from unittest.mock import MagicMock

import pytest

from src.common.workflow_executor import (
    EntityActionStepHandler,
    StepContext,
    WorkflowExecutor,
)
from src.controller.workflows_manager import WorkflowsManager
from src.db_models.data_contracts import DataContractDb
from src.models.process_workflows import (
    ProcessWorkflowCreate,
    StepType,
    TriggerContext,
    TriggerType,
    WorkflowStep,
    WorkflowStepCreate,
    WorkflowTrigger,
)

PUBLISH = {'action': 'publish', 'scope_source': 'fixed', 'fixed_scope': 'organization'}
REFUSED = [
    StepType.ENTITY_ACTION, StepType.DELIVERY, StepType.CREATE_ASSET_REVIEW,
    StepType.GRANT_PERMISSIONS,
]


def _workflow(trigger_type, step_type=StepType.ENTITY_ACTION):
    return ProcessWorkflowCreate(
        name='Gate',
        trigger=WorkflowTrigger(type=trigger_type, entity_types=['data_contract']),
        steps=[
            WorkflowStepCreate(step_id='act', name='Act', order=0, step_type=step_type,
                               config=PUBLISH, on_pass='check'),
            WorkflowStepCreate(step_id='check', name='Check', order=1,
                               step_type=StepType.FAIL),
        ],
    )


def _issues(trigger_type, step_type=StepType.ENTITY_ACTION):
    result = WorkflowsManager(MagicMock()).validate_workflow(_workflow(trigger_type, step_type))
    return [
        (issue.code, issue.params) for issue in result.issues
        if issue.code == 'update_gate_step_not_allowed'
    ]


@pytest.mark.parametrize('step_type', REFUSED, ids=lambda s: s.value)
def test_saving_a_before_update_gate_with_such_a_step_is_refused(step_type):
    assert _issues(TriggerType.BEFORE_UPDATE, step_type) == [
        ('update_gate_step_not_allowed', {'step': 'act', 'stepType': step_type.value}),
    ]


def test_other_triggers_keep_their_entity_actions():
    assert _issues(TriggerType.ON_UPDATE) == []
    assert _issues(TriggerType.BEFORE_STATUS_CHANGE) == []


def _context(contract, trigger_type):
    trigger = TriggerContext(
        entity_type='data_contract', entity_id=contract.id, trigger_type=trigger_type,
        entity_data={'name': 'Renamed'}, user_email='u@example.com',
    )
    return StepContext(
        entity={'name': 'Renamed'}, entity_type='data_contract', entity_id=contract.id,
        entity_name=contract.name, user_email='u@example.com', trigger_context=trigger,
        execution_id='e', workflow_id='w', workflow_name='W', step_results={},
    )


def _contract(db):
    contract = DataContractDb(
        id=str(uuid.uuid4()), name='contract', version='1.0.0', status='active',
        created_by='u@example.com',
    )
    db.add(contract)
    db.flush()
    return contract


def _step(step_type, config):
    return WorkflowStep(step_id='act', name='Act', step_type=step_type, config=config,
                        workflow_id='w')


def test_a_stored_before_update_entity_action_fails_without_publishing(db_session):
    contract = _contract(db_session)

    result = WorkflowExecutor(db_session)._execute_step(
        _step(StepType.ENTITY_ACTION, PUBLISH), _context(contract, TriggerType.BEFORE_UPDATE),
    )

    assert result.passed is False
    assert result.data['error_code'] == 'update_gate_step_not_allowed'
    db_session.refresh(contract)
    assert (contract.publication_scope or 'none') == 'none'


@pytest.mark.parametrize('step_type', REFUSED[1:], ids=lambda s: s.value)
def test_a_stored_before_update_side_effect_step_fails_without_running(
    db_session, monkeypatch, step_type,
):
    contract = _contract(db_session)
    handler = WorkflowExecutor.HANDLERS[step_type.value]
    ran = []
    monkeypatch.setattr(handler, 'execute', lambda self, context: ran.append(step_type))

    result = WorkflowExecutor(db_session)._execute_step(
        _step(step_type, {}), _context(contract, TriggerType.BEFORE_UPDATE),
    )

    assert ran == []
    assert result.passed is False
    assert result.data == {
        'error_code': 'update_gate_step_not_allowed',
        'error_params': {'stepType': step_type.value},
    }


def test_an_on_update_entity_action_still_publishes(db_session):
    contract = _contract(db_session)

    result = EntityActionStepHandler(db_session, PUBLISH).execute(
        _context(contract, TriggerType.ON_UPDATE),
    )

    assert result.passed is True, result.error
    db_session.refresh(contract)
    assert contract.publication_scope == 'organization'
