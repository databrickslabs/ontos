"""LLM_CHECK is refused where it's evaluated without a model (#1479 review).

Workflow policy_check steps and maturity gates evaluate a policy's rule
without an LLM checker, so LLM_CHECK fails there (llm_check_not_available) for
every entity, and a policy check would block every update. Saving such a step
(in an active workflow), adding such a gate, or giving a policy they use an
LLM_CHECK rule is refused with a code.
"""
import asyncio
import os
import uuid
from unittest.mock import MagicMock

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import pytest
from fastapi import HTTPException

from src.controller.compliance_manager import ComplianceManager
from src.controller.workflows_manager import WorkflowsManager
from src.db_models.compliance import CompliancePolicyDb
from src.models.process_workflows import (
    ProcessWorkflowCreate,
    StepType,
    TriggerType,
    WorkflowStepCreate,
    WorkflowTrigger,
)

LLM_RULE = "MATCH (t:table)\nASSERT LLM_CHECK(t.comment, 'states the grain')"
PLAIN_RULE = "MATCH (t:table)\nASSERT t.comment != ''"


def _policy(db, rule, policy_id=None):
    policy = CompliancePolicyDb(id=policy_id or str(uuid.uuid4()), name='P', rule=rule)
    db.add(policy)
    db.flush()
    return policy


def _workflow(policy_id, is_active=True) -> ProcessWorkflowCreate:
    return ProcessWorkflowCreate(
        name=f'Gate {uuid.uuid4().hex[:6]}',
        trigger=WorkflowTrigger(type=TriggerType.BEFORE_CREATE, entity_types=['table']),
        is_active=is_active,
        steps=[
            WorkflowStepCreate(
                step_id='grain-check', name='Grain', order=0, step_type=StepType.POLICY_CHECK,
                config={'policy_id': policy_id},
            ),
        ],
    )


def test_a_policy_check_step_on_an_llm_check_policy_is_an_error(db_session):
    policy = _policy(db_session, LLM_RULE)

    [error] = WorkflowsManager(db_session).policy_reference_errors(
        _workflow(policy.id).steps,
    )

    assert error.code == 'policy_check_policy_uses_llm_check'
    assert error.params == {'step': 'grain-check', 'policyId': policy.id}


def test_a_policy_check_step_on_a_plain_policy_is_fine(db_session):
    policy = _policy(db_session, PLAIN_RULE)

    assert WorkflowsManager(db_session).policy_reference_errors(
        _workflow(policy.id).steps,
    ) == []


def test_creating_an_active_workflow_on_an_llm_check_policy_is_refused(db_session):
    from src.routes.workflows_routes import create_workflow

    policy = _policy(db_session, LLM_RULE)
    manager = WorkflowsManager(db_session)

    with pytest.raises(HTTPException) as raised:
        asyncio.run(create_workflow(
            request=MagicMock(), workflow=_workflow(policy.id), db=db_session,
            audit_manager=MagicMock(), current_user=None, confirm_overlap=False,
            manager=manager,
        ))

    assert raised.value.status_code == 400
    [issue] = raised.value.detail['params']['issues']
    assert issue['code'] == 'policy_check_policy_uses_llm_check'


def test_policy_gate_uses_counts_steps_and_gates(db_session):
    from src.db_models.maturity import MaturityGateDb, MaturityLevelDb

    policy = _policy(db_session, PLAIN_RULE)
    other = _policy(db_session, PLAIN_RULE)
    workflows = WorkflowsManager(db_session)
    workflows.create_workflow(_workflow(policy.id, is_active=False))
    workflows.create_workflow(_workflow(other.id, is_active=False))
    level = MaturityLevelDb(name='L1', level_order=901, entity_type='all')
    db_session.add(level)
    db_session.flush()
    db_session.add(MaturityGateDb(maturity_level_id=level.id, compliance_policy_id=policy.id))
    db_session.flush()

    assert ComplianceManager.policy_gate_uses(db_session, policy.id) == {
        'workflowSteps': 1, 'maturityGates': 1,
    }
    assert ComplianceManager.policy_gate_uses(db_session, str(uuid.uuid4())) == {
        'workflowSteps': 0, 'maturityGates': 0,
    }


def test_an_llm_check_rule_for_a_policy_in_use_is_refused():
    from unittest.mock import patch

    from src.routes import compliance_routes

    with patch.object(compliance_routes, 'manager') as manager:
        manager.policy_gate_uses.return_value = {'workflowSteps': 1, 'maturityGates': 0}
        with pytest.raises(HTTPException) as raised:
            compliance_routes.refuse_llm_check_where_it_cannot_run(MagicMock(), 'p1', LLM_RULE)
        assert raised.value.status_code == 409

        # A rule without LLM_CHECK, or a policy nothing evaluates without a model, saves
        compliance_routes.refuse_llm_check_where_it_cannot_run(MagicMock(), 'p1', PLAIN_RULE)
        manager.policy_gate_uses.return_value = {'workflowSteps': 0, 'maturityGates': 0}
        compliance_routes.refuse_llm_check_where_it_cannot_run(MagicMock(), 'p1', LLM_RULE)


def test_a_maturity_gate_on_an_llm_check_policy_is_refused(db_session):
    from src.db_models.maturity import MaturityGateDb, MaturityLevelDb
    from src.models.maturity import MaturityGateCreate
    from src.routes.maturity_routes import add_gate

    policy = _policy(db_session, LLM_RULE)
    level = MaturityLevelDb(name='L1', level_order=902, entity_type='all')
    db_session.add(level)
    db_session.flush()

    with pytest.raises(HTTPException) as raised:
        asyncio.run(add_gate(
            level_id=level.id, db=db_session,
            body=MaturityGateCreate(compliance_policy_id=policy.id),
        ))

    assert raised.value.status_code == 422
    assert raised.value.__cause__.code == 'maturity_gate_policy_uses_llm_check'
    assert db_session.query(MaturityGateDb).filter_by(
        compliance_policy_id=policy.id,
    ).count() == 0
