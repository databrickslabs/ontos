"""A workflow whose ``policy_check`` steps name no existing policy can't be active.

Such a workflow fails with "Policy not found" on every event it handles (for
``pre-creation-compliance`` that blocks every catalog, schema and table
creation), so activating it, or saving an active one, is refused with a coded
error that names the step. The shipped ``pre-creation-compliance`` workflow has
empty policy ids, with the policy names as hints.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from src.controller.workflows_manager import WorkflowsManager
from src.db_models.compliance import CompliancePolicyDb
from src.models.process_workflows import (
    ProcessWorkflowCreate,
    ProcessWorkflowUpdate,
    StepType,
    TriggerType,
    WorkflowStepCreate,
    WorkflowTrigger,
)
from src.routes.workflows_routes import (
    create_workflow,
    toggle_workflow_active,
    update_workflow,
)


def _policy(db, policy_id='pol-1'):
    db.add(CompliancePolicyDb(id=policy_id, name='Naming', rule='MATCH (o:Object) ASSERT true'))
    db.flush()


def _workflow(policy_id, is_active=True, name='Gate') -> ProcessWorkflowCreate:
    return ProcessWorkflowCreate(
        name=name,
        trigger=WorkflowTrigger(type=TriggerType.BEFORE_CREATE, entity_types=['table']),
        is_active=is_active,
        steps=[
            WorkflowStepCreate(
                step_id='naming-check', name='Naming', order=0, step_type=StepType.POLICY_CHECK,
                config={'policy_id': policy_id, 'policy_name': 'Naming Conventions'},
            ),
        ],
    )


# ``confirm_overlap`` is passed explicitly: called directly, its ``Query`` default is truthy


def _toggle(db, manager, workflow_id, is_active, confirm_overlap=False):
    return asyncio.run(toggle_workflow_active(
        request=MagicMock(), workflow_id=workflow_id, db=db, audit_manager=MagicMock(),
        current_user=None, is_active=is_active, confirm_overlap=confirm_overlap,
        manager=manager,
    ))


def _update(db, manager, workflow_id, body, confirm_overlap=False):
    return asyncio.run(update_workflow(
        request=MagicMock(), workflow_id=workflow_id, workflow=body, db=db,
        audit_manager=MagicMock(), current_user=None, confirm_overlap=confirm_overlap,
        manager=manager,
    ))


def _create(db, manager, workflow, confirm_overlap=False):
    return asyncio.run(create_workflow(
        request=MagicMock(), workflow=workflow, db=db, audit_manager=MagicMock(),
        current_user=None, confirm_overlap=confirm_overlap, manager=manager,
    ))


@pytest.mark.parametrize('policy_id', ['', '   ', 'naming-conventions'])
def test_creating_an_active_workflow_with_a_missing_policy_is_refused(db_session, policy_id):
    manager = WorkflowsManager(db_session)

    with pytest.raises(HTTPException) as raised:
        _create(db_session, manager, _workflow(policy_id))

    assert raised.value.status_code == 400
    [issue] = raised.value.detail['params']['issues']
    assert issue['code'] == 'policy_check_policy_missing'
    assert issue['params'] == {'step': 'naming-check', 'policyId': policy_id.strip()}
    assert "Step 'naming-check'" in issue['message']
    assert manager.list_workflows() == []


def test_an_inactive_workflow_with_a_missing_policy_can_be_saved(db_session):
    result = _create(db_session, WorkflowsManager(db_session), _workflow('', is_active=False))

    assert result.is_active is False


def test_an_active_workflow_with_an_existing_policy_can_be_saved(db_session):
    _policy(db_session)

    result = _create(db_session, WorkflowsManager(db_session), _workflow('pol-1'))

    assert result.is_active is True


def test_activating_a_workflow_with_a_missing_policy_is_refused(db_session):
    manager = WorkflowsManager(db_session)
    created = manager.create_workflow(_workflow('naming-conventions', is_active=False))

    with pytest.raises(HTTPException) as raised:
        _toggle(db_session, manager, created.id, True)

    assert raised.value.status_code == 400
    detail = raised.value.detail
    assert detail['code'] == 'workflow_invalid'
    [issue] = detail['params']['issues']
    assert issue['code'] == 'policy_check_policy_missing'
    assert issue['params'] == {'step': 'naming-check', 'policyId': 'naming-conventions'}
    assert manager.get_workflow(created.id).is_active is False


@pytest.mark.parametrize('confirm_overlap', [False, True])
def test_a_missing_policy_is_refused_before_the_overlap_warning(db_session, confirm_overlap):
    """Overlapping an active workflow must not offer "activate anyway" for one that can't run."""
    _policy(db_session)
    manager = WorkflowsManager(db_session)
    manager.create_workflow(_workflow('pol-1', name='Active gate'))
    created = manager.create_workflow(_workflow('naming-conventions', is_active=False))
    assert manager.activation_conflicts(created.id)

    with pytest.raises(HTTPException) as raised:
        _toggle(db_session, manager, created.id, True, confirm_overlap=confirm_overlap)

    assert raised.value.status_code == 400
    assert raised.value.detail['code'] == 'workflow_invalid'
    assert manager.get_workflow(created.id).is_active is False


@pytest.mark.parametrize('with_steps', [False, True])
def test_a_save_that_activates_refuses_a_missing_policy_before_the_overlap(db_session, with_steps):
    _policy(db_session)
    manager = WorkflowsManager(db_session)
    manager.create_workflow(_workflow('pol-1', name='Active gate'))
    created = manager.create_workflow(_workflow('', is_active=False))
    body = ProcessWorkflowUpdate(
        is_active=True, steps=_workflow('').steps if with_steps else None,
    )

    with pytest.raises(HTTPException) as raised:
        _update(db_session, manager, created.id, body)

    assert raised.value.status_code == 400
    assert raised.value.detail['code'] == 'workflow_invalid'


def test_a_runnable_overlapping_workflow_still_gets_the_overlap_warning(db_session):
    _policy(db_session)
    manager = WorkflowsManager(db_session)
    manager.create_workflow(_workflow('pol-1', name='Active gate'))
    created = manager.create_workflow(_workflow('pol-1', is_active=False))

    with pytest.raises(HTTPException) as raised:
        _toggle(db_session, manager, created.id, True)

    assert raised.value.status_code == 409
    assert raised.value.detail['code'] == 'workflow_activation_overlap'


def test_activating_a_workflow_with_an_existing_policy_is_allowed(db_session):
    _policy(db_session)
    manager = WorkflowsManager(db_session)
    created = manager.create_workflow(_workflow('pol-1', is_active=False))

    result = _toggle(db_session, manager, created.id, True)

    assert result.is_active is True


def test_disabling_a_workflow_with_a_missing_policy_is_allowed(db_session):
    manager = WorkflowsManager(db_session)
    created = manager.create_workflow(_workflow('naming-conventions'))

    result = _toggle(db_session, manager, created.id, False)

    assert result.is_active is False


def test_saving_an_active_workflow_with_a_missing_policy_is_refused(db_session):
    manager = WorkflowsManager(db_session)
    created = manager.create_workflow(_workflow('', is_active=False))
    body = ProcessWorkflowUpdate(is_active=True, steps=_workflow('').steps)

    with pytest.raises(HTTPException) as raised:
        _update(db_session, manager, created.id, body)

    [issue] = raised.value.detail['params']['issues']
    assert issue['code'] == 'policy_check_policy_missing'
    assert issue['params']['step'] == 'naming-check'


def test_activating_through_a_save_without_steps_is_refused(db_session):
    manager = WorkflowsManager(db_session)
    created = manager.create_workflow(_workflow('', is_active=False))

    with pytest.raises(HTTPException) as raised:
        _update(db_session, manager, created.id, ProcessWorkflowUpdate(is_active=True))

    assert raised.value.detail['params']['issues'][0]['code'] == 'policy_check_policy_missing'


def test_saving_the_description_of_an_active_workflow_without_steps_is_allowed(db_session):
    manager = WorkflowsManager(db_session)
    created = manager.create_workflow(_workflow('naming-conventions'))

    result = _update(db_session, manager, created.id, ProcessWorkflowUpdate(description='x'))

    assert result.description == 'x'


def test_the_shipped_pre_creation_compliance_workflow_has_no_placeholder_ids(db_session):
    manager = WorkflowsManager(db_session)
    manager.load_from_yaml(requests_only_active=True)

    workflow = next(
        w for w in manager.list_workflows() if w.name == 'Pre-Creation Compliance Validation'
    )
    checks = [s for s in workflow.steps if s.step_type == StepType.POLICY_CHECK]

    assert workflow.is_active is False
    assert [s.config['policy_id'] for s in checks] == ['', '']
    assert [s.config['policy_name'] for s in checks] == ['Naming Conventions', 'Required Tags']
    # and it can't be enabled until the policies are selected
    assert [e.params['step'] for e in manager.policy_reference_errors(workflow.steps)] == [
        'naming-policy-check', 'tagging-policy-check',
    ]


def test_other_validation_errors_keep_their_codes_next_to_the_policy_error(db_session):
    from src.models.process_workflows import CodedMessage, WorkflowValidationResult
    from src.routes.workflows_routes import _with_policy_errors

    earlier = WorkflowValidationResult(
        valid=False, errors=[CodedMessage('Bad condition', 'condition_invalid', step='c1')],
    )
    steps = [WorkflowStepCreate(step_id='check', step_type=StepType.POLICY_CHECK,
                                config={'policy_id': 'missing'})]

    result = _with_policy_errors(WorkflowsManager(db_session), earlier, steps, True)

    assert [(i.code, i.params) for i in result.issues] == [
        ('condition_invalid', {'step': 'c1'}),
        ('policy_check_policy_missing', {'step': 'check', 'policyId': 'missing'}),
    ]
