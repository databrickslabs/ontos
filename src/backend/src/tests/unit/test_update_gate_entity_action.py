"""An entity action can't run in a before_update gate (#1403 review).

Its certify, publish and unpublish paths commit as the gate runs, so a gate of
[Publish] then [a failing check] refused the update and left the contract published.
Saving such a workflow is refused; one stored before fails at that step, before it
commits anything.
"""
import uuid
from unittest.mock import MagicMock

from src.common.workflow_executor import EntityActionStepHandler, StepContext
from src.controller.workflows_manager import WorkflowsManager
from src.db_models.data_contracts import DataContractDb
from src.models.process_workflows import (
    ProcessWorkflowCreate,
    StepType,
    TriggerContext,
    TriggerType,
    WorkflowStepCreate,
    WorkflowTrigger,
)

PUBLISH = {'action': 'publish', 'scope_source': 'fixed', 'fixed_scope': 'organization'}


def _workflow(trigger_type):
    return ProcessWorkflowCreate(
        name='Gate',
        trigger=WorkflowTrigger(type=trigger_type, entity_types=['data_contract']),
        steps=[
            WorkflowStepCreate(step_id='publish', name='Publish', order=0,
                               step_type=StepType.ENTITY_ACTION, config=PUBLISH,
                               on_pass='check'),
            WorkflowStepCreate(step_id='check', name='Check', order=1,
                               step_type=StepType.FAIL),
        ],
    )


def _issues(trigger_type):
    result = WorkflowsManager(MagicMock()).validate_workflow(_workflow(trigger_type))
    return [(issue.code, issue.params) for issue in result.issues]


def test_saving_a_before_update_gate_with_an_entity_action_is_refused():
    assert _issues(TriggerType.BEFORE_UPDATE) == [
        ('update_gate_entity_action', {'step': 'publish'}),
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


def test_a_stored_before_update_entity_action_fails_without_publishing(db_session):
    contract = DataContractDb(
        id=str(uuid.uuid4()), name='contract', version='1.0.0', status='active',
        created_by='u@example.com',
    )
    db_session.add(contract)
    db_session.flush()

    result = EntityActionStepHandler(db_session, PUBLISH).execute(
        _context(contract, TriggerType.BEFORE_UPDATE),
    )

    assert result.passed is False
    assert result.data['error_code'] == 'update_gate_entity_action'
    db_session.refresh(contract)
    assert (contract.publication_scope or 'none') == 'none'


def test_an_on_update_entity_action_still_publishes(db_session):
    contract = DataContractDb(
        id=str(uuid.uuid4()), name='contract', version='1.0.0', status='active',
        created_by='u@example.com',
    )
    db_session.add(contract)
    db_session.flush()

    result = EntityActionStepHandler(db_session, PUBLISH).execute(
        _context(contract, TriggerType.ON_UPDATE),
    )

    assert result.passed is True, result.error
    db_session.refresh(contract)
    assert contract.publication_scope == 'organization'
