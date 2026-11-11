"""'domain_owners' / 'DomainOwner' / 'ContractApprover' approvers resolve to people.

The default workflows send approvals to these tokens, but a default install
has no app role with those names, so the approvals reached nobody.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from types import SimpleNamespace

import pytest

from src.common.workflow_executor import _resolve_role_to_users
from src.db_models.business_owners import BusinessOwnerDb
from src.db_models.business_roles import BusinessRoleDb
from src.db_models.data_contracts import DataContractDb, DataContractTeamDb
from src.db_models.data_domains import DataDomain
from src.db_models.domain_associations import EntityDomainAssociationDb
from src.db_models.settings import AppRoleDb


def _context(entity_type='data_product', entity_id='product-1'):
    return SimpleNamespace(
        user_email='requester@example.com', entity={}, entity_type=entity_type,
        entity_id=entity_id, entity_name='E',
    )


@pytest.fixture
def data_steward(db_session):
    role = AppRoleDb(id=str(uuid.uuid4()), name='Data Steward')
    db_session.add(role)
    db_session.flush()
    return role


def _domain(db, entity_id='product-1', entity_type='data_product', is_primary=True):
    domain = DataDomain(id=str(uuid.uuid4()), name=f'domain-{uuid.uuid4().hex[:6]}',
                        created_by='admin')
    db.add(domain)
    db.flush()
    db.add(EntityDomainAssociationDb(
        domain_id=domain.id, entity_id=entity_id, entity_type=entity_type,
        is_primary=is_primary,
    ))
    db.flush()
    return domain


def _domain_owner(db, domain, email, role_name='Chief Risk Officer', is_active=True):
    role = db.query(BusinessRoleDb).filter(BusinessRoleDb.name == role_name).first()
    if not role:
        role = BusinessRoleDb(id=uuid.uuid4(), name=role_name)
        db.add(role)
        db.flush()
    db.add(BusinessOwnerDb(
        id=uuid.uuid4(), object_type='data_domain', object_id=domain.id,
        user_email=email, role_id=role.id, is_active=is_active,
    ))
    db.flush()


@pytest.mark.parametrize('token', ['domain_owners', 'DomainOwner', 'domain_owner'])
def test_domain_owner_tokens_resolve_to_the_domain_owners(db_session, data_steward, token):
    domain = _domain(db_session)
    # Any business role: the domain page lists them all under "Owners".
    _domain_owner(db_session, domain, 'cro@example.com')
    _domain_owner(db_session, domain, 'lead@example.com', role_name='Domain Lead')
    _domain_owner(db_session, domain, 'former@example.com', is_active=False)

    assert _resolve_role_to_users(db_session, token, _context()) == [
        ('cro@example.com', None), ('lead@example.com', None),
    ]


def test_only_the_primary_domain_counts_when_there_is_one(db_session, data_steward):
    primary = _domain(db_session)
    other = _domain(db_session, is_primary=False)
    _domain_owner(db_session, primary, 'primary@example.com')
    _domain_owner(db_session, other, 'other@example.com')

    assert _resolve_role_to_users(db_session, 'domain_owners', _context()) == [
        ('primary@example.com', None),
    ]


def test_all_domains_count_when_none_is_primary(db_session, data_steward):
    first = _domain(db_session, is_primary=False)
    second = _domain(db_session, is_primary=False)
    _domain_owner(db_session, first, 'first@example.com')
    _domain_owner(db_session, second, 'second@example.com')

    resolved = _resolve_role_to_users(db_session, 'domain_owners', _context())

    assert sorted(resolved) == [('first@example.com', None), ('second@example.com', None)]


def test_domain_without_owners_falls_back_to_data_stewards(db_session, data_steward):
    _domain(db_session)

    assert _resolve_role_to_users(db_session, 'domain_owners', _context()) == [
        ('Data Steward', data_steward.id), ('Admin', None),
    ]


def test_entity_without_domain_falls_back_to_data_stewards(db_session, data_steward):
    assert _resolve_role_to_users(db_session, 'DomainOwner', _context()) == [
        ('Data Steward', data_steward.id), ('Admin', None),
    ]


def test_an_app_role_with_the_name_wins(db_session, data_steward):
    role = AppRoleDb(id=str(uuid.uuid4()), name='Domain Owner')
    db_session.add(role)
    db_session.flush()
    domain = _domain(db_session)
    _domain_owner(db_session, domain, 'cro@example.com')

    assert _resolve_role_to_users(db_session, 'domain_owners', _context()) == [
        ('Domain Owner', role.id),
    ]


def test_contract_approver_is_the_contract_owners(db_session, data_steward):
    contract = DataContractDb(
        id=str(uuid.uuid4()), name='c', version='1.0.0', status='approved',
        version_family_id=str(uuid.uuid4()),
    )
    db_session.add(contract)
    db_session.flush()
    db_session.add(DataContractTeamDb(
        id=str(uuid.uuid4()), contract_id=contract.id, username='owner@example.com',
        role='owner',
    ))
    db_session.flush()

    resolved = _resolve_role_to_users(
        db_session, 'ContractApprover', _context('data_contract', contract.id)
    )

    assert resolved == [('owner@example.com', None)]


def test_contract_without_owners_falls_back_to_data_stewards(db_session, data_steward):
    resolved = _resolve_role_to_users(
        db_session, 'ContractApprover', _context('data_contract', 'contract-1')
    )

    assert resolved == [('Data Steward', data_steward.id), ('Admin', None)]


def test_the_requester_does_not_approve_their_own_request(db_session, data_steward):
    domain = _domain(db_session)
    _domain_owner(db_session, domain, 'Requester@example.com')
    _domain_owner(db_session, domain, 'cro@example.com')

    assert _resolve_role_to_users(db_session, 'domain_owners', _context()) == [
        ('cro@example.com', None),
    ]


def test_a_requester_who_is_the_only_owner_goes_to_data_stewards(db_session, data_steward):
    contract = DataContractDb(
        id=str(uuid.uuid4()), name='c', version='1.0.0', status='approved',
        version_family_id=str(uuid.uuid4()),
    )
    db_session.add(contract)
    db_session.flush()
    db_session.add(DataContractTeamDb(
        id=str(uuid.uuid4()), contract_id=contract.id, username='requester@example.com',
        role='owner',
    ))
    db_session.flush()

    resolved = _resolve_role_to_users(
        db_session, 'ContractApprover', _context('data_contract', contract.id)
    )

    # Data Stewards and admins; handle-approval refuses the requester's own decision
    assert resolved == [('Data Steward', data_steward.id), ('Admin', None)]


def test_an_app_role_named_like_the_token_is_found(db_session, data_steward):
    # e.g. approvers='Domain Owners' with an app role of that name
    role = AppRoleDb(id=str(uuid.uuid4()), name='Domain Owners')
    db_session.add(role)
    db_session.flush()

    assert _resolve_role_to_users(db_session, 'Domain Owners', _context()) == [
        ('Domain Owners', role.id),
    ]
