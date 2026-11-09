"""Property-level (column) ODCS customProperties are stored and round-trip (#609).

Contracts and schema objects had a table for customProperties, schema
properties didn't, so a column's customProperties were dropped on import.
"""
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import (
    DataContractDb,
    SchemaPropertyCustomPropertyDb,
    SchemaPropertyDb,
)

COLUMN_PROPS = [
    {'property': 'avroNamespace', 'value': 'com.example.orders'},
    {'property': 'protobufFieldNumber', 'value': 7, 'id': 'cp-field-number'},
    {'property': 'sourceNativeType', 'value': {'type': 'decimal', 'precision': 18}},
    {'property': 'pii', 'value': False},
]


def _manager():
    return DataContractsManager(data_dir=Path("/tmp"))


def _odcs():
    return {
        'apiVersion': 'v3.1.0',
        'kind': 'DataContract',
        'id': str(uuid.uuid4()),
        'name': f'orders-{uuid.uuid4().hex[:6]}',
        'version': '1.0.0',
        'status': 'draft',
        'schema': [{
            'name': 'orders',
            'properties': [
                {'name': 'amount', 'logicalType': 'number', 'customProperties': COLUMN_PROPS},
                {'name': 'order_id', 'logicalType': 'string'},
            ],
        }],
    }


def _column(odcs_doc, name):
    return next(p for p in odcs_doc['schema'][0]['properties'] if p['name'] == name)


@pytest.fixture
def imported(db_session: Session):
    manager = _manager()
    contract = manager.create_from_upload(db_session, _odcs(), current_user='alice')
    db_session.commit()
    return manager, contract


def test_column_custom_properties_are_stored_on_import(db_session, imported):
    _, contract = imported
    prop = db_session.query(SchemaPropertyDb).filter_by(name='amount').one()

    rows = db_session.query(SchemaPropertyCustomPropertyDb).filter_by(property_id=prop.id).all()

    assert sorted(r.property for r in rows) == sorted(c['property'] for c in COLUMN_PROPS)


def test_an_imported_contract_exports_the_same_column_custom_properties(db_session, imported):
    manager, contract = imported
    db_session.refresh(contract)

    exported = manager.build_odcs_from_db(contract, db_session)

    assert _column(exported, 'amount')['customProperties'] == COLUMN_PROPS
    assert 'customProperties' not in _column(exported, 'order_id')


def test_the_api_returns_them_as_name_value_pairs(db_session, imported):
    manager, contract = imported

    api = manager._build_contract_api_model(db_session, contract).model_dump(by_alias=True)

    amount = next(p for p in api['schema'][0]['properties'] if p['name'] == 'amount')
    assert amount['customProperties'] == {c['property']: c['value'] for c in COLUMN_PROPS}


def test_the_schema_property_editor_form_is_stored_too(db_session: Session):
    # The editor sends {name: value}
    cid = str(uuid.uuid4())
    db_session.add(DataContractDb(id=cid, name='C', version='1.0.0', status='draft'))
    db_session.commit()

    _manager()._create_schema_objects(db_session, cid, [{
        'name': 'orders',
        'properties': [{'name': 'amount', 'customProperties': {'unit': 'EUR', 'scale': 2}}],
    }])
    db_session.commit()

    prop = db_session.query(SchemaPropertyDb).filter_by(name='amount').one()
    assert {(r.property, r.value) for r in prop.custom_properties} == {
        ('unit', '"EUR"'), ('scale', '2'),
    }


def test_a_new_version_keeps_them(db_session, imported):
    manager, contract = imported

    new = manager.clone_contract_for_new_version(
        db_session, contract.id, '2.0.0', current_user='alice',
    )

    exported = manager.build_odcs_from_db(new, db_session)
    assert _column(exported, 'amount')['customProperties'] == COLUMN_PROPS


def test_deleting_the_property_deletes_them(db_session, imported):
    prop = db_session.query(SchemaPropertyDb).filter_by(name='amount').one()

    db_session.delete(prop)
    db_session.commit()

    assert db_session.query(SchemaPropertyCustomPropertyDb).filter_by(property_id=prop.id).count() == 0


def test_an_edit_in_the_schema_editor_keeps_them_and_their_ids(db_session, imported):
    # The editor sends the column's customProperties as {name: value}, without ids
    manager, contract = imported
    editor_form = {c['property']: c['value'] for c in COLUMN_PROPS}

    manager.update_contract_with_relations(db_session, contract.id, {
        'schema': [{
            'name': 'orders',
            'properties': [
                {'name': 'amount', 'logicalType': 'number', 'customProperties': editor_form},
                {'name': 'order_id', 'logicalType': 'string', 'description': 'Order identifier'},
            ],
        }],
    }, current_user='alice')

    db_session.expire_all()
    exported = manager.build_odcs_from_db(db_session.get(DataContractDb, contract.id), db_session)
    assert _column(exported, 'amount')['customProperties'] == COLUMN_PROPS
