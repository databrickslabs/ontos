"""LLM_CHECK is refused where it's evaluated without a model (#1479 review).

Workflow policy_check and validation steps, maturity gates and the self-service
compliance mapping evaluate a rule without an LLM checker, so LLM_CHECK fails there
(llm_check_not_available) for every entity, and a policy check would block every
update. Saving such a step (a policy check in an active workflow), adding such a gate,
naming such a policy in the mapping, or giving a policy they use an LLM_CHECK rule is
refused with a code.
"""
import asyncio
import os
import uuid

import yaml
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


def test_policy_gate_uses_counts_steps_of_active_workflows_only(db_session):
    policy = _policy(db_session, PLAIN_RULE)
    workflows = WorkflowsManager(db_session)
    workflows.create_workflow(_workflow(policy.id, is_active=False))
    assert ComplianceManager.policy_gate_uses(db_session, policy.id)['workflowSteps'] == 0

    workflows.create_workflow(_workflow(policy.id, is_active=True))
    assert ComplianceManager.policy_gate_uses(db_session, policy.id)['workflowSteps'] == 1


def test_an_llm_check_rule_is_saved_for_a_policy_only_inactive_workflows_check(db_session):
    from src.routes import compliance_routes

    policy = _policy(db_session, PLAIN_RULE)
    workflows = WorkflowsManager(db_session)
    stored = workflows.create_workflow(_workflow(policy.id, is_active=False))
    compliance_routes.refuse_llm_check_where_it_cannot_run(db_session, policy.id, LLM_RULE)

    # That workflow can't be activated afterwards: the step fails closed
    policy.rule = LLM_RULE
    db_session.flush()
    assert [e.code for e in workflows.policy_reference_errors(stored.steps)] == [
        'policy_check_policy_uses_llm_check',
    ]


def test_policy_gate_uses_counts_steps_and_gates(db_session):
    from src.db_models.maturity import MaturityGateDb, MaturityLevelDb

    policy = _policy(db_session, PLAIN_RULE)
    other = _policy(db_session, PLAIN_RULE)
    workflows = WorkflowsManager(db_session)
    workflows.create_workflow(_workflow(policy.id, is_active=True))
    workflows.create_workflow(_workflow(other.id, is_active=True))
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


GRAIN = 'states the grain of the table'


# --- Workflow validation steps -----------------------------------------------------

def _validation_workflow(rule):
    return ProcessWorkflowCreate(
        name='Check docs',
        trigger=WorkflowTrigger(type=TriggerType.ON_CREATE, entity_types=['data_product']),
        steps=[WorkflowStepCreate(
            step_id='docs', step_type=StepType.VALIDATION, config={'rule': rule},
        )],
    )


def test_a_validation_step_with_llm_check_is_refused_on_save(db_session):
    from src.controller.workflows_manager import WorkflowsManager

    result = WorkflowsManager(db_session).validate_workflow(_validation_workflow(
        f"ASSERT LLM_CHECK(obj.description, '{GRAIN}')",
    ))

    assert result.valid is False
    issue = next(i for i in result.issues if i.code == 'validation_rule_uses_llm_check')
    assert issue.params == {'step': 'docs'}


def test_a_validation_step_without_llm_check_saves(db_session):
    from src.controller.workflows_manager import WorkflowsManager

    result = WorkflowsManager(db_session).validate_workflow(_validation_workflow(
        "ASSERT obj.description != ''",
    ))

    assert not [i for i in result.issues if i.code == 'validation_rule_uses_llm_check']


# --- Self-service compliance mapping -----------------------------------------------

OBJ_LLM_RULE = f"ASSERT LLM_CHECK(obj.description, '{GRAIN}')"


def test_a_mapping_naming_an_llm_check_policy_is_refused(db_session):
    from src.controller.self_service_manager import (
        MappingPolicyUsesLlmCheckError, refuse_llm_check_in_mapping,
    )

    _slugged(db_session, OBJ_LLM_RULE, slug='docs-judged')
    _slugged(db_session, "ASSERT obj.name != ''", slug='named')

    with pytest.raises(MappingPolicyUsesLlmCheckError) as raised:
        refuse_llm_check_in_mapping(db_session, {
            'catalog': {'policies': ['named']},
            'table': {'policies': ['named', 'docs-judged']},
        })

    assert raised.value.params == {'objectType': 'table', 'policy': 'docs-judged'}


def test_a_mapping_of_policies_without_llm_check_or_unknown_ones_saves(db_session):
    from src.controller.self_service_manager import refuse_llm_check_in_mapping

    _slugged(db_session, "ASSERT obj.name != ''", slug='named')

    refuse_llm_check_in_mapping(db_session, {
        'table': {'policies': ['named', 'not-a-policy']}, 'schema': 'not a section',
    })


def test_the_object_types_whose_mapping_names_a_policy(db_session):
    from src.controller.self_service_manager import mapping_object_types_of

    policy = _slugged(db_session, OBJ_LLM_RULE, slug='docs-judged')
    mapping = {
        'catalog': {'policies': [policy.id]},
        'schema': {'policies': ['other']},
        'table': {'policies': [policy.name]},
    }

    assert mapping_object_types_of(mapping, policy) == ['catalog', 'table']
    assert mapping_object_types_of(None, policy) == []


def _slugged(db, rule, slug):
    policy = CompliancePolicyDb(id=str(uuid.uuid4()), name=f'P {slug}', slug=slug, rule=rule)
    db.add(policy)
    db.flush()
    return policy


def test_an_llm_check_rule_for_a_policy_in_the_self_service_mapping_is_refused(db_session):
    from unittest.mock import patch

    from src.routes import compliance_routes

    policy = _slugged(db_session, PLAIN_RULE, slug='grain')
    mapping = {'table': {'policies': ['grain']}}
    with patch('src.controller.self_service_manager.load_compliance_mapping',
               return_value=mapping):
        with pytest.raises(HTTPException) as raised:
            compliance_routes.refuse_llm_check_where_it_cannot_run(
                db_session, policy.id, LLM_RULE,
            )
        assert raised.value.status_code == 409
        assert raised.value.__cause__.code == 'llm_check_policy_in_self_service'
        assert raised.value.__cause__.params == {'objectTypes': 'table'}

        # A rule without LLM_CHECK saves
        compliance_routes.refuse_llm_check_where_it_cannot_run(
            db_session, policy.id, PLAIN_RULE,
        )
    # A policy the mapping doesn't name saves with LLM_CHECK
    with patch('src.controller.self_service_manager.load_compliance_mapping',
               return_value={'table': {'policies': ['other']}}):
        compliance_routes.refuse_llm_check_where_it_cannot_run(
            db_session, policy.id, LLM_RULE,
        )


def test_saving_a_mapping_that_names_an_llm_check_policy_is_refused(db_session):
    from unittest.mock import patch

    from src.routes.settings_routes import save_compliance_mapping

    _slugged(db_session, OBJ_LLM_RULE, slug='docs-judged')
    config = MagicMock()
    with patch('src.common.config.get_config_manager', return_value=config):
        with pytest.raises(HTTPException) as raised:
            asyncio.run(save_compliance_mapping(
                request=MagicMock(), db=db_session, audit_manager=MagicMock(),
                current_user=None, payload={'table': {'policies': ['docs-judged']}},
                manager=MagicMock(), _=True,
            ))

    assert raised.value.status_code == 422
    assert raised.value.__cause__.code == 'compliance_mapping_policy_uses_llm_check'
    config.save_yaml.assert_not_called()


def test_activating_a_stored_workflow_with_an_llm_check_validation_step_is_refused(db_session):
    # Stored without the designer's save check (the YAML load, an import)
    from src.routes.workflows_routes import _refuse_unrunnable_policy_steps

    manager = WorkflowsManager(db_session)
    stored = manager.create_workflow(_validation_workflow(
        f"ASSERT LLM_CHECK(obj.description, '{GRAIN}')",
    ))

    with pytest.raises(HTTPException) as raised:
        _refuse_unrunnable_policy_steps(manager, stored)

    assert raised.value.status_code == 400
    [issue] = raised.value.detail['params']['issues']
    assert issue['code'] == 'validation_rule_uses_llm_check'
    # A validation step without LLM_CHECK activates
    plain = manager.create_workflow(_validation_workflow("ASSERT obj.description != ''"))
    _refuse_unrunnable_policy_steps(manager, plain)


def test_the_yaml_load_skips_an_llm_check_policy_the_self_service_mapping_lists(
    db_session, tmp_path,
):
    from unittest.mock import patch

    listed, free, plain = (str(uuid.uuid4()) for _ in range(3))

    def entry(policy_id, name, rule, **extra):
        return {
            'id': policy_id, 'name': name, 'description': 'd', 'rule': rule,
            'category': 'general', 'severity': 'low', **extra,
        }

    path = tmp_path / 'policies.yaml'
    path.write_text(yaml.safe_dump([
        entry(listed, 'Listed by slug', LLM_RULE, slug='judged-docs'),
        entry(free, 'Not listed', LLM_RULE),
        entry(plain, 'Listed plain', PLAIN_RULE),
    ]))
    mapping = {'table': {'policies': ['judged-docs', plain]}}

    with patch('src.controller.self_service_manager.load_compliance_mapping',
               return_value=mapping):
        ComplianceManager().load_from_yaml(db_session, str(path))

    assert db_session.get(CompliancePolicyDb, listed) is None
    assert db_session.get(CompliancePolicyDb, free) is not None
    assert db_session.get(CompliancePolicyDb, plain) is not None
