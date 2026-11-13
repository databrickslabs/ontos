"""Every field of an ODCS server, with its `roles` and `customProperties` (#610).

The import kept nine fixed keys (host, port, database ...) and dropped the other
fields of the server types (an S3 server's `format`, `delimiter` and
`endpointUrl`, an Athena server's `stagingDir` and `regionName` ...), plus the
server `roles` and `customProperties`. The ODCS v3.1.0 schema requires some of
those fields (`format` for azure and local servers, `stagingDir` for athena,
`dataset` for bigquery, `serviceName` for oracle), so the export of such a
server failed validation.
"""
import json
import uuid
from pathlib import Path

import jsonschema
import pytest
from sqlalchemy.orm import Session

from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import DataContractDb
from src.models.data_contracts_api import DataContractUpdate

SCHEMA = Path(__file__).parent.parent.parent / "schemas" / "odcs-json-schema-v3.1.0.json"

ROLES = [{
    'id': 'srv-role-0', 'role': 'srv_reader', 'access': 'read', 'description': 'reads the files',
    'firstLevelApprovers': 'a', 'secondLevelApprovers': 'b',
    'customProperties': [{'id': 'srv-role-cp-0', 'property': 'ttlDays', 'value': 30}],
}]
SERVERS = [
    {'id': 'srv-s3', 'server': 's3-landing', 'type': 's3', 'environment': 'prod',
     'location': 's3://bucket/orders/', 'format': 'csv', 'delimiter': 'new_line',
     'endpointUrl': 'https://s3.example.com', 'roles': ROLES,
     'customProperties': [{'id': 'srv-cp-0', 'property': 'owner', 'value': 'ingest'},
                          {'id': 'srv-cp-1', 'property': 'replicas', 'value': 3}]},
    {'id': 'srv-athena', 'server': 'athena', 'type': 'athena', 'stagingDir': 's3://staging/',
     'schema': 'sales', 'catalog': 'awsdatacatalog', 'regionName': 'eu-west-1'},
    {'id': 'srv-pg', 'server': 'pg', 'type': 'postgres', 'host': 'db.example.com', 'port': 5432,
     'database': 'orders', 'schema': 'public'},
    {'id': 'srv-oracle', 'server': 'ora', 'type': 'oracle', 'host': 'ora.example.com',
     'port': 1521, 'serviceName': 'ORCL'},
]


def _manager():
    return DataContractsManager(data_dir=Path("/tmp"))


def _odcs():
    return {
        'apiVersion': 'v3.1.0', 'kind': 'DataContract', 'id': str(uuid.uuid4()),
        'name': f'orders-{uuid.uuid4().hex[:6]}', 'version': '1.0.0', 'status': 'draft',
        'servers': json.loads(json.dumps(SERVERS)),
    }


def _export(manager, db_session, contract_id):
    db_session.expire_all()
    return manager.build_odcs_from_db(db_session.get(DataContractDb, contract_id), db_session)


def _servers(doc):
    return {s['id']: s for s in doc['servers']}


@pytest.fixture
def imported(db_session: Session):
    manager = _manager()
    contract = manager.create_from_upload(db_session, _odcs(), current_user='alice')
    db_session.commit()
    return manager, contract.id


def test_every_server_field_is_exported_as_imported(db_session, imported):
    manager, cid = imported

    assert _servers(_export(manager, db_session, cid)) == {s['id']: s for s in SERVERS}


def test_the_server_exports_are_valid_odcs_v3_1_0(db_session, imported):
    manager, cid = imported
    validator = jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text()))

    errors = [e.message for e in validator.iter_errors(_export(manager, db_session, cid))]

    assert not errors


def test_a_server_edit_on_the_contract_page_keeps_roles_and_custom_properties(db_session, imported):
    manager, cid = imported
    api = manager._build_contract_api_model(db_session, db_session.get(DataContractDb, cid))
    servers = [s.model_dump(by_alias=True, exclude_none=True) for s in api.servers]
    # The server form sends back what it shows, not the roles or custom properties
    edited = next(s for s in servers if s['id'] == 'srv-s3')
    edited.pop('roles', None)
    edited.pop('customProperties', None)
    edited['environment'] = 'dev'

    manager.update_contract_with_relations(
        db_session, cid, DataContractUpdate.model_validate({'servers': servers}),
        current_user='alice')

    exported = _servers(_export(manager, db_session, cid))
    assert exported['srv-s3'] == {**SERVERS[0], 'environment': 'dev'}
    assert exported['srv-athena'] == SERVERS[1]


def test_a_new_version_keeps_every_server_field(db_session, imported):
    manager, cid = imported

    new = manager.clone_contract_for_new_version(db_session, cid, '2.0.0', current_user='alice')

    assert _servers(_export(manager, db_session, new.id)) == {s['id']: s for s in SERVERS}
