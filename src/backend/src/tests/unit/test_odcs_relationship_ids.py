"""Relationship ids (#610 review follow-ups).

A relationship's `id` is its ODCS id only in an ODCS document: in an API
payload it is the row id (the ODCS id is `stableId`). The export writes it only
for ODCS v3.2.0+ (v3.1.0 relationships don't allow it).
"""
import copy
import uuid
from pathlib import Path

from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import (
    DataContractDb, SchemaObjectDb, SchemaObjectRelationshipDb,
)
from src.models.data_contracts_api import DataContractUpdate
from src.utils.schema_editor_fields import keep_unsent_fields


def _manager():
    return DataContractsManager(data_dir=Path("/tmp"))


def _odcs(api_version='v3.1.0', **extra):
    return {
        'apiVersion': api_version, 'kind': 'DataContract', 'id': str(uuid.uuid4()),
        'name': f'orders-{uuid.uuid4().hex[:6]}', 'version': '1.0.0', 'status': 'draft', **extra,
    }


def _upload(manager, db_session, document):
    contract = manager.create_from_upload(db_session, copy.deepcopy(document), current_user='alice')
    db_session.commit()
    return contract.id


def _export(manager, db_session, contract_id):
    db_session.expire_all()
    return manager.build_odcs_from_db(db_session.get(DataContractDb, contract_id), db_session)


def _relationships(api_version):
    return _odcs(api_version, schema=[
        {'name': 'customers', 'properties': [{'name': 'customer_id', 'logicalType': 'string'}]},
        {'name': 'orders',
         'relationships': [{'id': 'rel-1', 'type': 'foreignKey',
                            'from': 'orders.customer_id', 'to': 'customers.customer_id'}],
         'properties': [{'name': 'customer_id', 'logicalType': 'string',
                         'relationships': [{'id': 'rel-2', 'type': 'foreignKey',
                                            'to': 'customers.customer_id'}]}]},
    ])


def _orders(doc):
    return {o['name']: o for o in doc['schema']}['orders']


def test_a_v3_1_0_export_writes_no_relationship_id(db_session):
    manager = _manager()
    cid = _upload(manager, db_session, _relationships('v3.1.0'))

    orders = _orders(_export(manager, db_session, cid))

    assert 'id' not in orders['relationships'][0]
    assert 'id' not in orders['properties'][0]['relationships'][0]


def test_a_v3_2_0_export_writes_the_relationship_ids(db_session):
    manager = _manager()
    cid = _upload(manager, db_session, _relationships('v3.2.0'))

    orders = _orders(_export(manager, db_session, cid))

    assert orders['relationships'][0]['id'] == 'rel-1'
    assert orders['properties'][0]['relationships'][0]['id'] == 'rel-2'


def test_a_relationship_resent_with_its_row_id_only_keeps_no_odcs_id(db_session):
    manager = _manager()
    cid = _upload(manager, db_session, _odcs('v3.2.0', schema=[
        {'name': 'orders', 'relationships': [{'type': 'foreignKey', 'from': 'orders.a',
                                              'to': 'customers.a'}],
         'properties': [{'name': 'a', 'logicalType': 'string'}]}]))
    row_id = db_session.query(SchemaObjectRelationshipDb).one().id
    # A client sends the relationship as the routes return it, without stableId
    form = {'name': 'orders', 'properties': [{'name': 'a', 'logicalType': 'string'}],
            'relationships': [{'id': row_id, 'type': 'foreignKey', 'from': 'orders.a',
                               'to': 'customers.a'}]}

    manager.update_contract_with_relations(
        db_session, cid, DataContractUpdate.model_validate({'schema': [form]}),
        current_user='alice')

    db_session.expire_all()
    obj = db_session.query(SchemaObjectDb).filter_by(contract_id=cid).one()
    assert [r.stable_id for r in obj.relationships] == [None]


def test_an_editor_save_keeps_the_column_relationship_ids_it_does_not_send():
    stored = {'name': 'orders', 'properties': [
        {'name': 'a', 'relationships': [{'id': 'rel-2', 'type': 'foreignKey', 'to': 'c.a'}]}]}

    merged = keep_unsent_fields({'name': 'orders', 'properties': [{'name': 'a'}]}, stored)

    assert merged['properties'][0]['relationships'][0]['stableId'] == 'rel-2'
