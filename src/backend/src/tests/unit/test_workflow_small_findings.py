"""Three small workflow defects found while writing the authoring guide (#969).

- A failed validation step kept no error: the rule's message was dropped, so
  the step showed only "Failed" in Recent Executions.
- On resume after an approval, the fields of the requester's last completed
  wizard for the entity replaced the approver's ``reason`` (and ``message``)
  in ``${step_results.<approval>.reason}``.
- The documented script example used ``return``, which fails: the code is not
  a function body.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
import uuid

from src.common.workflow_executor import WorkflowExecutor
from src.controller.workflows_manager import WorkflowsManager
from src.db_models.agreement_wizard_sessions import AgreementWizardSessionDb
from src.db_models.process_workflows import WorkflowStepExecutionDb
from src.models.process_workflows import (
    EntityType,
    ProcessWorkflowCreate,
    ScriptStepConfig,
    StepType,
    TriggerContext,
    TriggerType,
    WorkflowStepCreate,
    WorkflowTrigger,
)
from src.repositories.process_workflows_repository import process_workflow_repo


def _workflow(db, steps):
    db_workflow = process_workflow_repo.create(db, ProcessWorkflowCreate(
        name=f'wf-{uuid.uuid4().hex[:6]}',
        trigger=WorkflowTrigger(type=TriggerType.MANUAL, entity_types=[EntityType.DATA_PRODUCT]),
        steps=steps,
    ))
    return WorkflowsManager(db).get_workflow(db_workflow.id)


def _stored_product(db, product_id='p-1', name='sales_prod'):
    """A data product in the database: rules evaluate the stored entity, and a
    rule step on an entity that doesn't exist fails."""
    from src.db_models.data_products import DataProductDb

    db.add(DataProductDb(
        id=product_id, api_version='v1.0.0', kind='DataProduct', status='draft',
        name=name, version='1.0.0',
    ))
    db.flush()


def _run(db, workflow, entity_id='p-1', entity_name='sales_prod'):
    return WorkflowExecutor(db).execute_workflow(
        workflow=workflow,
        entity={'id': entity_id, 'name': entity_name},
        entity_type='data_product',
        entity_id=entity_id,
        entity_name=entity_name,
        user_email='pat@example.com',
        trigger_context=TriggerContext(
            entity_type='data_product', entity_id=entity_id, entity_name=entity_name,
            trigger_type=TriggerType.MANUAL, user_email='pat@example.com',
        ),
    )


def _results(db, execution_id):
    return {
        r.step.step_id: r
        for r in db.query(WorkflowStepExecutionDb)
        .filter(WorkflowStepExecutionDb.execution_id == execution_id)
        .all()
    }


def test_a_failed_validation_keeps_the_rule_message(db_session):
    workflow = _workflow(db_session, [
        WorkflowStepCreate(
            step_id='check-name', name='Name starts with fin_', step_type=StepType.VALIDATION,
            config={'rule': "MATCH (obj:Object) ASSERT obj.name MATCHES '^fin_'"},
            on_pass='ok', on_fail='stop', order=0,
        ),
        WorkflowStepCreate(step_id='ok', step_type=StepType.PASS, order=1),
        WorkflowStepCreate(step_id='stop', step_type=StepType.FAIL, order=2),
    ])

    _stored_product(db_session)
    execution = _run(db_session, workflow)

    check = _results(db_session, execution.id)['check-name']
    assert check.status == 'failed'
    assert check.error_message == "Assertion failed: obj.name MATCHES '^fin_'"


def test_a_passed_validation_has_no_error(db_session):
    workflow = _workflow(db_session, [
        WorkflowStepCreate(
            step_id='check-name', step_type=StepType.VALIDATION,
            config={'rule': "MATCH (obj:Object) ASSERT obj.name MATCHES '^sales'"},
            on_pass='ok', order=0,
        ),
        WorkflowStepCreate(step_id='ok', step_type=StepType.PASS, order=1),
    ])

    _stored_product(db_session)
    execution = _run(db_session, workflow)

    assert _results(db_session, execution.id)['check-name'].error_message is None


def _approval_then_echo(db):
    """Approval, then a script that puts the approval's reason in its result data."""
    return _workflow(db, [
        WorkflowStepCreate(
            step_id='approve', step_type=StepType.APPROVAL,
            config={'approvers': 'reviewer@example.com'},
            on_pass='echo', on_fail='stop', order=0,
        ),
        WorkflowStepCreate(
            step_id='echo', step_type=StepType.SCRIPT,
            config={'language': 'python', 'code': (
                "a = step_results['approve']\n"
                "result = {'passed': True, 'data': {\n"
                "    'reason': a.get('reason'), 'workspace': a.get('workspaceId')}}"
            )},
            on_pass='ok', order=1,
        ),
        WorkflowStepCreate(step_id='ok', step_type=StepType.PASS, order=2),
        WorkflowStepCreate(step_id='stop', step_type=StepType.FAIL, order=3),
    ])


def _requester_wizard(db, workflow_id, entity_id):
    db.add(AgreementWizardSessionDb(
        id=str(uuid.uuid4()), workflow_id=workflow_id, entity_type='data_product',
        entity_id=entity_id, status='completed', current_step_index=1,
        step_results=json.dumps([{'step_id': 'ask', 'payload': {
            'reason': 'Requester wizard reason', 'workspaceId': 'ws-42',
        }}]),
    ))
    db.commit()


def _resume_with_reason(db, workflow, entity_id):
    execution = _run(db, workflow, entity_id=entity_id)
    assert execution.status.value == 'paused'
    resumed = WorkflowExecutor(db).resume_workflow(
        execution_id=execution.id,
        step_result=True,
        result_data={'message': 'Approver reason', 'reason': 'Approver reason',
                     'decision': 'approved'},
        user_email='reviewer@example.com',
    )
    assert resumed.status.value == 'succeeded'
    return json.loads(_results(db, execution.id)['echo'].result_data)


def test_the_approver_reason_wins_over_the_requester_wizard(db_session):
    workflow = _approval_then_echo(db_session)
    _requester_wizard(db_session, workflow.id, 'p-2')

    echoed = _resume_with_reason(db_session, workflow, 'p-2')

    assert echoed['reason'] == 'Approver reason'


def test_other_wizard_fields_still_reach_later_steps(db_session):
    workflow = _approval_then_echo(db_session)
    _requester_wizard(db_session, workflow.id, 'p-3')

    echoed = _resume_with_reason(db_session, workflow, 'p-3')

    assert echoed['workspace'] == 'ws-42'


def test_the_script_example_runs(db_session):
    example = ScriptStepConfig.model_json_schema()['example']
    workflow = _workflow(db_session, [
        WorkflowStepCreate(step_id='run', step_type=StepType.SCRIPT,
                           config=example, on_pass='ok', on_fail='stop', order=0),
        WorkflowStepCreate(step_id='ok', step_type=StepType.PASS, order=1),
        WorkflowStepCreate(step_id='stop', step_type=StepType.FAIL, order=2),
    ])

    execution = _run(db_session, workflow)

    run = _results(db_session, execution.id)['run']
    assert run.status == 'succeeded', run.error_message
