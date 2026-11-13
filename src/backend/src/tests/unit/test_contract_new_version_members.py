"""A new version of a contract with team members or roles (#610).

"Create New Version" (`POST /clone`) failed for a contract with team members
or roles: the cloner read attributes the rows don't have (`member.email`,
`role.name`), so the clone raised and nothing was created. It also left out
the team object (name, description, tags ...), most fields of the support
channels, and the ODCS ids of the price, the SLA and the custom properties.
A new version now exports the same document as the version it was made from.
"""
import copy
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import DataContractDb

DOCUMENT = {
    'apiVersion': 'v3.1.0', 'kind': 'DataContract', 'version': '1.0.0', 'status': 'draft',
    'team': {
        'id': 'team-0', 'name': 'Orders team', 'description': 'Owns the orders data',
        'tags': ['sales'], 'customProperties': [{'property': 'costCenter', 'value': 'cc-1'}],
        'members': [
            {'id': 'member-0', 'username': 'alice@example.com', 'name': 'Alice', 'role': 'owner',
             'description': 'Lead', 'dateIn': '2024-01-01', 'dateOut': '2025-01-01',
             'replacedByUsername': 'bob@example.com'},
            {'username': 'bob@example.com', 'role': 'steward'},
        ],
    },
    'roles': [{
        'id': 'role-0', 'role': 'orders_reader', 'description': 'Reads orders', 'access': 'read',
        'firstLevelApprovers': 'Sales lead', 'secondLevelApprovers': 'Data governance',
        'customProperties': [{'id': 'role-cp-0', 'property': 'ttlDays', 'value': '30'}],
    }],
    'support': [{'id': 'sup-0', 'channel': '#orders', 'url': 'https://chat.example.com/orders',
                 'description': 'Questions', 'tool': 'slack', 'scope': 'interactive',
                 'invitationUrl': 'https://chat.example.com/invite'}],
    'price': {'id': 'price-0', 'priceAmount': 9.95, 'priceCurrency': 'USD',
              'priceUnit': 'megabyte'},
    'slaProperties': [{'id': 'sla-0', 'property': 'latency', 'value': 4, 'unit': 'd',
                       'element': 'orders.created_at', 'driver': 'operational'}],
    'customProperties': [{'id': 'cp-0', 'property': 'costCenter', 'value': 'cc-1'}],
}


def _manager():
    return DataContractsManager(data_dir=Path("/tmp"))


def _export(manager, db_session, contract_id):
    db_session.expire_all()
    return manager.build_odcs_from_db(db_session.get(DataContractDb, contract_id), db_session)


@pytest.fixture
def imported(db_session: Session):
    manager = _manager()
    doc = copy.deepcopy(DOCUMENT)
    doc.update({'id': str(uuid.uuid4()), 'name': f'orders-{uuid.uuid4().hex[:6]}'})
    contract = manager.create_from_upload(db_session, doc, current_user='alice')
    db_session.commit()
    return manager, contract.id


def _custom(doc):
    return [cp for cp in doc.get('customProperties', []) if cp['property'] == 'costCenter']


@pytest.mark.parametrize('personal_draft', [False, True])
def test_a_new_version_of_a_contract_with_team_and_roles_is_created(
        db_session, imported, personal_draft):
    manager, cid = imported
    version = '2.0.0-draft' if personal_draft else '2.0.0'

    new = manager.clone_contract_for_new_version(
        db_session, cid, version, current_user='alice', as_personal_draft=personal_draft)

    assert new.version == version


@pytest.mark.parametrize('field', ['team', 'roles', 'support', 'price', 'slaProperties'])
def test_a_new_version_exports_the_same(db_session, imported, field):
    manager, cid = imported
    before = _export(manager, db_session, cid)

    new = manager.clone_contract_for_new_version(db_session, cid, '2.0.0', current_user='alice')

    after = _export(manager, db_session, new.id)
    assert after[field] == before[field]


def test_a_new_version_keeps_the_custom_property_ids(db_session, imported):
    manager, cid = imported
    before = _export(manager, db_session, cid)

    new = manager.clone_contract_for_new_version(db_session, cid, '2.0.0', current_user='alice')

    assert _custom(_export(manager, db_session, new.id)) == _custom(before) == [
        {'property': 'costCenter', 'value': 'cc-1', 'id': 'cp-0'}]
