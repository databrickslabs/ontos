"""Compliance rules see a stored data domain's owners.

AppEntityLoader read ``domain.owner_team_id``, a column that data domains no
longer have (their owners are Business Owners, listed on the domain page under
"Owners"), so ``owner`` was always None for a domain: ``LENGTH(d.owner) > 0``
failed on every domain, and ``d.owner CONTAINS '<email>'`` matched none.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from src.common.compliance_entities import AppEntityLoader
from src.common.workflow_executor import PolicyCheckStepHandler, StepContext
from src.controller.compliance_manager import ComplianceManager
from src.db_models.business_owners import BusinessOwnerDb
from src.db_models.business_roles import BusinessRoleDb
from src.db_models.compliance import CompliancePolicyDb, ComplianceResultDb
from src.db_models.data_domains import DataDomain
from src.models.process_workflows import TriggerContext, TriggerType


def _domain(db, name):
    domain = DataDomain(
        id=str(uuid.uuid4()), name=f'{name}-{uuid.uuid4().hex[:6]}',
        created_by='creator@example.com',
    )
    db.add(domain)
    db.flush()
    return domain


def _role(db, name):
    role = BusinessRoleDb(id=uuid.uuid4(), name=f'{name}-{uuid.uuid4().hex[:6]}')
    db.add(role)
    db.flush()
    return role


def _owner(db, domain, email, role, *, active=True, minutes_ago=0):
    db.add(BusinessOwnerDb(
        id=uuid.uuid4(), object_type='data_domain', object_id=domain.id, user_email=email,
        role_id=role.id, is_active=active,
        assigned_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    ))
    db.flush()


def _policy(db, rule):
    policy = CompliancePolicyDb(
        id=str(uuid.uuid4()), name='Domain owners', rule=rule, is_active=True,
    )
    db.add(policy)
    db.flush()
    return policy


def test_a_stored_domain_has_its_active_owners(db_session):
    domain, other = _domain(db_session, 'sales'), _domain(db_session, 'finance')
    data_owner, steward = _role(db_session, 'Data Owner'), _role(db_session, 'Data Steward')
    # Any business role, as the domain page lists them, in assignment order
    _owner(db_session, domain, 'second@example.com', steward, minutes_ago=1)
    _owner(db_session, domain, 'first@example.com', data_owner, minutes_ago=5)
    _owner(db_session, domain, 'former@example.com', data_owner, active=False)
    _owner(db_session, other, 'elsewhere@example.com', data_owner)

    loaded = AppEntityLoader(db_session).load_entity('domain', domain.id)

    assert loaded['owner'] == ['first@example.com', 'second@example.com']


def test_a_domain_without_owners_has_an_empty_list(db_session):
    domain = _domain(db_session, 'sales')
    _owner(db_session, domain, 'former@example.com', _role(db_session, 'Data Owner'), active=False)

    assert AppEntityLoader(db_session).load_entity('domain', domain.id)['owner'] == []


def test_all_domains_load_with_their_owners(db_session):
    owned, unowned = _domain(db_session, 'sales'), _domain(db_session, 'finance')
    _owner(db_session, owned, 'owner@example.com', _role(db_session, 'Data Owner'))

    loaded = {
        e['id']: e['owner'] for e in AppEntityLoader(db_session).load_entities(['domain'])
    }

    assert loaded[owned.id] == ['owner@example.com']
    assert loaded[unowned.id] == []


def test_a_run_checks_that_domains_have_an_owner(db_session):
    owned, unowned = _domain(db_session, 'sales'), _domain(db_session, 'finance')
    _owner(db_session, owned, 'owner@example.com', _role(db_session, 'Data Owner'))
    policy = _policy(db_session, "MATCH (d:domain) ASSERT LENGTH(d.owner) > 0")

    with patch('src.common.workspace_client.get_workspace_client', return_value=MagicMock()):
        run = ComplianceManager().run_policy_inline(db_session, policy=policy)
    results = {
        r.object_id: r.passed
        for r in db_session.query(ComplianceResultDb).filter_by(run_id=run.id)
    }

    assert results[owned.id] is True
    assert results[unowned.id] is False


def test_a_policy_check_on_a_stored_domain_sees_its_owners(db_session):
    domain = _domain(db_session, 'sales')
    _owner(db_session, domain, 'owner@example.com', _role(db_session, 'Data Owner'))
    policy = _policy(db_session, "MATCH (d:domain) ASSERT d.owner CONTAINS 'owner@example.com'")
    payload = {'id': domain.id, 'name': domain.name}
    trigger = TriggerContext(
        entity_type='domain', entity_id=domain.id, trigger_type=TriggerType.ON_UPDATE,
        entity_data=payload, user_email='u@example.com',
    )
    context = StepContext(
        entity=payload, entity_type='domain', entity_id=domain.id, entity_name=domain.name,
        user_email='u@example.com', trigger_context=trigger,
        execution_id='e', workflow_id='w', workflow_name='W', step_results={},
    )

    result = PolicyCheckStepHandler(db_session, {'policy_id': policy.id}).execute(context)

    assert result.passed is True
