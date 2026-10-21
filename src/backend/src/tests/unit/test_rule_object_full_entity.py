"""Workflow rules evaluate the stored entity, not just the trigger payload.

Trigger payloads are small (e.g. ``{name, status}`` on a product status
change), so the default rules on contracts and schemas passed whatever the
entity looked like.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from src.common.workflow_executor import (
    StepContext,
    ValidationStepHandler,
    _rule_object,
)
from src.db_models.data_contracts import DataContractDb, SchemaObjectDb
from src.db_models.data_products import DataProductDb, OutputPortDb

_DEFAULT_WORKFLOWS = Path(__file__).resolve().parents[2] / 'data' / 'default_workflows.yaml'


def _default_rule(workflow_name, step_id):
    workflows = yaml.safe_load(_DEFAULT_WORKFLOWS.read_text())['workflows']
    workflow = next(w for w in workflows if w['name'] == workflow_name)
    return next(s for s in workflow['steps'] if s['id'] == step_id)['config']['rule']


def _context(entity_type, entity_id, payload):
    return StepContext(
        entity=payload, entity_type=entity_type, entity_id=entity_id, entity_name='E',
        user_email='u@example.com', trigger_context=None, execution_id='exec-1',
        workflow_id='wf-1', workflow_name='W', step_results={},
    )


def _product(db, contract_id=None):
    product = DataProductDb(
        id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct',
        status='active', name='p', version='1.0.0',
    )
    db.add(product)
    db.flush()
    db.add(OutputPortDb(
        id=str(uuid.uuid4()), product_id=product.id, name='orders', version='1.0.0',
        contract_id=contract_id,
    ))
    db.flush()
    return product


def _contract(db, with_schema=False, owner_team_id=None):
    contract = DataContractDb(
        id=str(uuid.uuid4()), name='c', version='1.0.0', status='draft',
        version_family_id=str(uuid.uuid4()), owner_team_id=owner_team_id,
    )
    db.add(contract)
    db.flush()
    if with_schema:
        db.add(SchemaObjectDb(id=str(uuid.uuid4()), contract_id=contract.id, name='orders'))
        db.flush()
    return contract


def _validate(db, rule, context):
    return ValidationStepHandler(db, {'rule': rule}).execute(context)


def test_the_payload_overrides_the_stored_entity(db_session):
    product = _product(db_session, contract_id='contract-1')

    obj = _rule_object(db_session, _context(
        'data_product', product.id, {'status': 'approved', 'requested_scope': 'domain'},
    ))

    assert obj['status'] == 'approved'
    assert obj['requested_scope'] == 'domain'
    assert obj['output_port_contract_count'] == 1
    assert obj['name'] == 'p'


@pytest.mark.parametrize('contract_id, passed', [(None, False), ('contract-1', True)])
def test_product_publish_approval_checks_the_output_port_contracts(
    db_session, contract_id, passed
):
    product = _product(db_session, contract_id=contract_id)
    rule = _default_rule('Data Product Publish Approval', 'check-contract')

    # The on_status_change payload: just name and status.
    result = _validate(db_session, rule, _context(
        'data_product', product.id, {'name': 'p', 'status': 'active'},
    ))

    assert result.passed is passed


@pytest.mark.parametrize('with_schema, passed', [(False, False), (True, True)])
def test_contract_schema_validation_checks_the_schema(db_session, with_schema, passed):
    contract = _contract(db_session, with_schema=with_schema)
    rule = _default_rule('Data Contract Schema Validation', 'check-schema')

    result = _validate(db_session, rule, _context(
        'data_contract', contract.id, {'contract_id': contract.id, 'name': 'c', 'status': 'draft'},
    ))

    assert result.passed is passed


@pytest.mark.parametrize('owner_team_id, passed', [(None, False), ('team-1', True)])
def test_contract_owner_check_uses_the_owner_team(db_session, owner_team_id, passed):
    contract = _contract(db_session, owner_team_id=owner_team_id)
    rule = _default_rule('Data Contract Schema Validation', 'check-owner')

    result = _validate(db_session, rule, _context('data_contract', contract.id, {'name': 'c'}))

    assert result.passed is passed


def test_other_entity_types_get_the_payload(db_session):
    payload = {'name': 'sales_orders'}

    assert _rule_object(db_session, _context('table', 'main.sales.orders', payload)) == payload


def test_unknown_entity_ids_get_the_payload(db_session):
    payload = {'name': 'p'}

    assert _rule_object(db_session, _context('data_product', 'missing', payload)) == payload


def test_a_failing_entity_load_raises(db_session):
    with patch('src.controller.entity_dict_builder.build_data_product_dict',
               side_effect=RuntimeError('db down')):
        with pytest.raises(RuntimeError, match='Could not load data_product product-1'):
            _rule_object(db_session, _context('data_product', 'product-1', {'name': 'p'}))


def test_a_rule_step_fails_when_the_entity_cannot_be_loaded(db_session):
    # On the payload alone ({name, status}) this rule passes vacuously.
    rule = "MATCH (obj:data_product) ASSERT obj.missing_field != 'x'"

    with patch('src.controller.entity_dict_builder.build_data_product_dict',
               side_effect=RuntimeError('db down')):
        result = _validate(db_session, rule, _context(
            'data_product', 'product-1', {'name': 'p', 'status': 'active'},
        ))

    assert result.passed is False
    assert result.error == 'Could not load data_product product-1 to evaluate the rule'
    # A code and parameters the UI can translate the error from
    assert result.data == {
        'error_code': 'rule_entity_load_failed',
        'error_params': {'entityType': 'data_product', 'entityId': 'product-1'},
    }


def test_conditional_and_policy_steps_carry_the_same_error_code(db_session):
    from src.common.workflow_executor import ConditionalStepHandler, PolicyCheckStepHandler
    from src.db_models.compliance import CompliancePolicyDb

    policy = CompliancePolicyDb(
        id=str(uuid.uuid4()), name='p', description='d', is_active=True,
        rule="MATCH (obj:data_product) ASSERT obj.name != ''",
    )
    db_session.add(policy)
    db_session.flush()
    context = _context('data_product', 'product-1', {'name': 'p'})

    with patch('src.controller.entity_dict_builder.build_data_product_dict',
               side_effect=RuntimeError('db down')):
        conditional = ConditionalStepHandler(
            db_session, {'condition': "obj.name = 'p'"},
        ).execute(context)
        policy_check = PolicyCheckStepHandler(
            db_session, {'policy_id': policy.id},
        ).execute(context)

    for result in (conditional, policy_check):
        assert result.passed is False
        assert result.data['error_code'] == 'rule_entity_load_failed'
        assert result.data['error_params']['entityId'] == 'product-1'
    assert policy_check.data['policy_id'] == policy.id


def test_other_rule_step_errors_have_no_code(db_session):
    result = _validate(db_session, 'MATCH (obj:data_product) ASSERT', _context(
        'data_product', 'product-1', {'name': 'p'},
    ))

    assert result.passed is False
    assert not (result.data or {}).get('error_code')


def test_before_update_gates_see_only_the_proposed_change(db_session):
    from src.models.process_workflows import TriggerContext, TriggerType

    contract = _contract(db_session, owner_team_id='team-1')
    context = _context('data_contract', contract.id, {'owner_team_id': None})
    context.trigger_context = TriggerContext(
        entity_type='data_contract', entity_id=contract.id,
        trigger_type=TriggerType.BEFORE_UPDATE,
    )

    # The stored row's has_owner=True would contradict the proposed change.
    assert _rule_object(db_session, context) == {'owner_team_id': None}
