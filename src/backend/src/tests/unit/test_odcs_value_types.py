"""ODCS values keep their JSON type and their ids (#610).

- An SLA property's `value` was stored with `str()`: `true` came back as the
  string "True", and a string that looks like a number came back as a number.
- A contract custom property did the same (`true` -> "True").
- A role's `customProperties` went out as a `{property: value}` map (the ODCS
  list is required: the export failed validation) with the values as text, and
  without their ids; a re-import of that export dropped them.
- `price.id` and a relationship's `id` (ODCS v3.2.0) were not stored.
"""
import copy
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import DataContractDb

VALUES = ['text', '42', 42, 4.5, True, False, {'nested': [1, 'two']}, [1, 2]]
SLA = [{'id': f'sla-{i}', 'property': f'p{i}', 'value': v}
       for i, v in enumerate(VALUES[:6])] + [
    {'id': 'sla-ext', 'property': 'latency', 'value': 4, 'valueExt': 'p99', 'unit': 'd'}]
CUSTOM = [{'id': f'cp-{i}', 'property': f'cp{i}', 'value': v} for i, v in enumerate(VALUES)]
ROLES = [{
    'id': 'role-0', 'role': 'reader', 'access': 'read',
    'customProperties': [{'id': f'role-cp-{i}', 'property': f'rcp{i}', 'value': v}
                         for i, v in enumerate(VALUES)],
}]
PRICE = {'id': 'price-0', 'priceAmount': 9.95, 'priceCurrency': 'USD', 'priceUnit': 'megabyte'}


def _manager():
    return DataContractsManager(data_dir=Path("/tmp"))


def _odcs(api_version='v3.1.0'):
    return {
        'apiVersion': api_version, 'kind': 'DataContract', 'id': str(uuid.uuid4()),
        'name': f'orders-{uuid.uuid4().hex[:6]}', 'version': '1.0.0', 'status': 'draft',
        'slaProperties': copy.deepcopy(SLA), 'customProperties': copy.deepcopy(CUSTOM),
        'roles': copy.deepcopy(ROLES), 'price': dict(PRICE),
    }


def _export(manager, db_session, contract_id):
    db_session.expire_all()
    return manager.build_odcs_from_db(db_session.get(DataContractDb, contract_id), db_session)


def _upload(manager, db_session, document):
    contract = manager.create_from_upload(db_session, document, current_user='alice')
    db_session.commit()
    return contract.id


@pytest.fixture
def imported(db_session: Session):
    manager = _manager()
    return manager, _upload(manager, db_session, _odcs())


def _typed(value):
    """The value with its type, so that 1 == True and '42' == 42 don't pass."""
    return (type(value).__name__, value)


def _by(items, key='property'):
    return {i[key]: i for i in items}


def test_sla_values_keep_their_type(db_session, imported):
    manager, cid = imported

    exported = _by(_export(manager, db_session, cid)['slaProperties'])

    for item in SLA:
        assert _typed(exported[item['property']]['value']) == _typed(item['value'])
        assert exported[item['property']]['id'] == item['id']
    assert exported['latency']['valueExt'] == 'p99'


def test_contract_custom_properties_keep_their_type(db_session, imported):
    manager, cid = imported

    exported = _by(_export(manager, db_session, cid)['customProperties'])

    for item in CUSTOM:
        assert _typed(exported[item['property']]['value']) == _typed(item['value'])
        assert exported[item['property']]['id'] == item['id']


def test_role_custom_properties_go_out_as_the_odcs_list(db_session, imported):
    manager, cid = imported

    role = _export(manager, db_session, cid)['roles'][0]

    assert role['customProperties'] == ROLES[0]['customProperties']
    assert [_typed(cp['value']) for cp in role['customProperties']] == [_typed(v) for v in VALUES]


def test_a_reimport_of_the_export_keeps_the_role_custom_properties(db_session, imported):
    manager, cid = imported
    exported = _export(manager, db_session, cid)

    again = _export(manager, db_session, _upload(manager, db_session, copy.deepcopy(exported)))

    assert again['roles'] == exported['roles'] == ROLES


def test_the_price_id_is_kept(db_session, imported):
    manager, cid = imported

    assert _export(manager, db_session, cid)['price'] == PRICE


def test_a_new_version_keeps_ids_types_and_roles(db_session, imported):
    manager, cid = imported
    before = _export(manager, db_session, cid)

    new = manager.clone_contract_for_new_version(db_session, cid, '2.0.0', current_user='alice')

    after = _export(manager, db_session, new.id)
    assert after['price'] == before['price']
    assert after['roles'] == before['roles']
    assert after['slaProperties'] == before['slaProperties']
    custom = lambda doc: [cp for cp in doc['customProperties']  # noqa: E731
                          if cp['property'].startswith('cp')]
    assert custom(after) == custom(before)


def _with_relationship_ids():
    doc = _odcs('v3.2.0')
    doc['schema'] = [
        {'name': 'customers', 'properties': [{'name': 'customer_id', 'logicalType': 'string'}]},
        {'name': 'orders',
         'relationships': [{'id': 'rel-orders-customer', 'type': 'foreignKey',
                            'from': 'orders.customer_id', 'to': 'customers.customer_id'}],
         'properties': [{'name': 'customer_id', 'logicalType': 'string',
                         'relationships': [{'id': 'rel-prop-customer', 'type': 'foreignKey',
                                            'to': 'customers.customer_id'}]}]},
    ]
    return doc


def test_relationship_ids_are_kept(db_session):
    manager = _manager()
    cid = _upload(manager, db_session, _with_relationship_ids())

    orders = _by(_export(manager, db_session, cid)['schema'], 'name')['orders']

    assert orders['relationships'][0]['id'] == 'rel-orders-customer'
    assert orders['properties'][0]['relationships'][0]['id'] == 'rel-prop-customer'


def test_a_new_version_keeps_the_relationship_ids(db_session):
    manager = _manager()
    cid = _upload(manager, db_session, _with_relationship_ids())

    new = manager.clone_contract_for_new_version(db_session, cid, '2.0.0', current_user='alice')

    orders = _by(_export(manager, db_session, new.id)['schema'], 'name')['orders']
    assert orders['relationships'][0]['id'] == 'rel-orders-customer'
    assert orders['properties'][0]['relationships'][0]['id'] == 'rel-prop-customer'
