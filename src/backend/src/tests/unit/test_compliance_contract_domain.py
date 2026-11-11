"""Compliance rules see a stored data contract's primary domain.

AppEntityLoader read ``contract.domain_id``, a column that was dropped when
contracts moved to multi-domain assignment (entity_domain_associations), so
``domain`` was always None for a stored contract: a compliance run's
``WHERE c.domain = ...`` selected no contract, and a workflow policy check on
a stored contract failed ``ASSERT c.domain = ...`` whatever its domain.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from unittest.mock import MagicMock, patch

from src.common.compliance_entities import AppEntityLoader
from src.common.workflow_executor import PolicyCheckStepHandler, StepContext
from src.controller.compliance_manager import ComplianceManager
from src.db_models.compliance import CompliancePolicyDb, ComplianceResultDb
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_domains import DataDomain
from src.db_models.domain_associations import EntityDomainAssociationDb
from src.models.data_contracts_api import DataContractUpdate
from src.models.process_workflows import TriggerContext, TriggerType


def _domain(db, name):
    domain = DataDomain(
        id=str(uuid.uuid4()), name=f'{name}-{uuid.uuid4().hex[:6]}', created_by='u@example.com',
    )
    db.add(domain)
    db.flush()
    return domain.id


def _contract(db, *domain_ids, primary=None):
    contract = DataContractDb(
        id=str(uuid.uuid4()), name=f'contract-{uuid.uuid4().hex[:6]}', version='1.0.0',
        status='active', created_by='u@example.com',
    )
    db.add(contract)
    db.flush()
    for domain_id in domain_ids:
        db.add(EntityDomainAssociationDb(
            domain_id=domain_id, entity_type='data_contract', entity_id=contract.id,
            is_primary=domain_id == primary,
        ))
    db.flush()
    return contract


def _policy(db, rule):
    policy = CompliancePolicyDb(id=str(uuid.uuid4()), name='Gate', rule=rule, is_active=True)
    db.add(policy)
    db.flush()
    return policy


def _step(db, policy, contract, payload, trigger_type):
    trigger = TriggerContext(
        entity_type='data_contract', entity_id=contract.id, trigger_type=trigger_type,
        entity_data=payload, user_email='u@example.com',
    )
    context = StepContext(
        entity=payload, entity_type='data_contract', entity_id=contract.id,
        entity_name=contract.name, user_email='u@example.com', trigger_context=trigger,
        execution_id='e', workflow_id='w', workflow_name='W', step_results={},
    )
    return PolicyCheckStepHandler(db, {'policy_id': policy.id}).execute(context)


def test_a_stored_contract_has_its_primary_domain(db_session):
    primary, other = _domain(db_session, 'sales'), _domain(db_session, 'finance')
    contract = _contract(db_session, other, primary, primary=primary)

    loaded = AppEntityLoader(db_session).load_entity('data_contract', contract.id)

    assert loaded['domain'] == primary


def test_a_contract_without_a_primary_domain_has_none(db_session):
    unassigned = _contract(db_session)
    only_additional = _contract(db_session, _domain(db_session, 'sales'))

    loader = AppEntityLoader(db_session)

    assert loader.load_entity('data_contract', unassigned.id)['domain'] is None
    assert loader.load_entity('data_contract', only_additional.id)['domain'] is None


def test_a_run_selects_contracts_by_domain(db_session):
    domain = _domain(db_session, 'sales')
    in_domain = _contract(db_session, domain, primary=domain)
    elsewhere = _contract(db_session, _domain(db_session, 'finance'), primary=None)
    policy = _policy(
        db_session,
        f"MATCH (c:data_contract) WHERE c.domain = '{domain}' ASSERT c.status = 'active'",
    )

    with patch('src.common.workspace_client.get_workspace_client', return_value=MagicMock()):
        run = ComplianceManager().run_policy_inline(db_session, policy=policy)
    results = {
        r.object_id: r.passed
        for r in db_session.query(ComplianceResultDb).filter_by(run_id=run.id)
    }

    assert results.get(in_domain.id) is True
    assert elsewhere.id not in results


def test_a_policy_check_on_a_stored_contract_sees_its_domain(db_session):
    domain = _domain(db_session, 'sales')
    contract = _contract(db_session, domain, primary=domain)
    policy = _policy(db_session, f"MATCH (c:data_contract) ASSERT c.domain = '{domain}'")

    result = _step(
        db_session, policy, contract, {'contract_id': contract.id, 'name': contract.name},
        TriggerType.ON_UPDATE,
    )

    assert result.passed is True


def test_a_before_update_gate_on_the_domain_applies_when_the_domain_is_kept(db_session):
    # The update doesn't change the domain: the WHERE sees the stored one
    domain = _domain(db_session, 'sales')
    contract = _contract(db_session, domain, primary=domain)
    policy = _policy(
        db_session,
        f"MATCH (c:data_contract) WHERE c.domain = '{domain}' ASSERT c.status = 'active'",
    )

    result = _step(
        db_session, policy, contract,
        DataContractUpdate(status='draft').model_dump(exclude_unset=True),
        TriggerType.BEFORE_UPDATE,
    )

    assert result.passed is False
    assert 'not_applicable' not in result.data
