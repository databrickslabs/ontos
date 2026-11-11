"""A server's ODCS id survives page edits and new versions.

It was kept on a page edit only when the server had a `server` identifier,
because the contract API didn't return the id (and the server form dropped
it), and a new version didn't copy it at all.
"""
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import DataContractDb
from src.models.data_contracts_api import DataContractRead, DataContractUpdate, ServerConfig

SERVERS = [
    {'id': 'srv-named', 'server': 'prod-db', 'type': 'postgres', 'host': 'db.example.com'},
    # ODCS requires `server`, but imports accept a server without it
    {'id': 'srv-unnamed', 'type': 'databricks', 'catalog': 'main'},
]


def _manager():
    return DataContractsManager(data_dir=Path("/tmp"))


@pytest.fixture
def imported(db_session: Session):
    manager = _manager()
    doc = {
        'apiVersion': 'v3.1.0', 'kind': 'DataContract', 'id': str(uuid.uuid4()),
        'name': f'orders-{uuid.uuid4().hex[:6]}', 'version': '1.0.0', 'status': 'draft',
        'servers': [dict(s) for s in SERVERS],
    }
    contract = manager.create_from_upload(db_session, doc, current_user='alice')
    db_session.commit()
    return manager, contract.id


def _exported_server_ids(manager, db_session, contract_id):
    db_session.expire_all()
    doc = manager.build_odcs_from_db(db_session.get(DataContractDb, contract_id), db_session)
    return sorted(s.get('id') for s in doc['servers'])


# --- server ids -----------------------------------------------------------

def test_the_contract_api_returns_each_server_id(db_session, imported):
    manager, cid = imported

    api = manager._build_contract_api_model(db_session, db_session.get(DataContractDb, cid))

    assert sorted(s.id for s in api.servers) == ['srv-named', 'srv-unnamed']


def test_a_page_edit_keeps_the_id_of_a_server_without_an_identifier(db_session, imported):
    manager, cid = imported
    api = manager._build_contract_api_model(db_session, db_session.get(DataContractDb, cid))
    # What the page sends: the servers as the API returned them, one of them edited
    servers = [s.model_dump(by_alias=True, exclude_none=True) for s in api.servers]
    servers[0]['description'] = 'edited on the page'

    manager.update_contract_with_relations(
        db_session, cid, DataContractUpdate.model_validate({'servers': servers}), current_user='alice',
    )

    assert _exported_server_ids(manager, db_session, cid) == ['srv-named', 'srv-unnamed']


def test_an_orm_server_row_reads_its_odcs_id_not_its_primary_key(db_session, imported):
    _, cid = imported
    contract = db_session.get(DataContractDb, cid)

    read = DataContractRead.model_validate(contract, from_attributes=True)

    assert sorted(s.id for s in read.servers) == ['srv-named', 'srv-unnamed']
    assert all(s.id not in {row.id for row in contract.servers} for s in read.servers)


def test_a_server_config_without_an_id_still_validates():
    assert ServerConfig.model_validate({'server': 'dev', 'type': 'databricks'}).id is None


def test_a_new_version_keeps_the_server_ids(db_session, imported):
    manager, cid = imported

    new = manager.clone_contract_for_new_version(db_session, cid, '2.0.0', current_user='alice')

    assert _exported_server_ids(manager, db_session, new.id) == ['srv-named', 'srv-unnamed']
