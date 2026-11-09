"""The contract page's SLA requirements and servers are saved (#896).

The page sends `PUT /api/data-contracts/{id}` with `{sla: {...}}` or
`{servers: [...]}`. Neither was stored: the SLA had nowhere to go and the
update model had no `servers` field, so both saves answered 200 and dropped
the values. The SLA values are kept as ODCS slaProperties, so they also go out
with the export.
"""
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import DataContractDb, DataContractSlaPropertyDb
from src.models.data_contracts_api import DataContractUpdate

SLA_FORM = {'uptimeTarget': 99.9, 'maxDowntimeMinutes': 60, 'queryResponseTimeMs': 1000,
            'dataFreshnessMinutes': 15}


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
        'slaProperties': [{'property': 'latency', 'value': 4, 'unit': 'd'}],
        'servers': [{'server': 'prod', 'id': 'srv-prod', 'type': 'databricks', 'catalog': 'main', 'schema': 'sales'}],
    }


@pytest.fixture
def imported(db_session: Session):
    manager = _manager()
    contract = manager.create_from_upload(db_session, _odcs(), current_user='alice')
    db_session.commit()
    return manager, contract.id


def _save(manager, db_session, contract_id, body):
    # As the route does: the JSON body parsed into the update model
    manager.update_contract_with_relations(
        db_session, contract_id, DataContractUpdate.model_validate(body), current_user='alice',
    )
    db_session.expire_all()
    return db_session.get(DataContractDb, contract_id)


def test_the_sla_form_is_saved_and_read_back(db_session, imported):
    manager, cid = imported

    contract = _save(manager, db_session, cid, {'sla': SLA_FORM})

    api = manager._build_contract_api_model(db_session, contract).model_dump(by_alias=True)
    assert api['sla'] == SLA_FORM


def test_the_sla_goes_out_with_the_export_and_keeps_the_other_sla_properties(db_session, imported):
    manager, cid = imported

    contract = _save(manager, db_session, cid, {'sla': SLA_FORM})

    exported = {p['property']: p for p in manager.build_odcs_from_db(contract, db_session)['slaProperties']}
    assert exported['latency'] == {'property': 'latency', 'value': 4, 'unit': 'd'}
    assert exported['uptimeTarget'] == {'property': 'uptimeTarget', 'value': 99.9, 'unit': 'percent'}
    assert exported['dataFreshnessMinutes']['value'] == 15


def test_an_exported_sla_imports_back(db_session, imported):
    manager, cid = imported
    contract = _save(manager, db_session, cid, {'sla': SLA_FORM})
    doc = manager.build_odcs_from_db(contract, db_session)
    doc['id'] = str(uuid.uuid4())
    doc['name'] = f'orders-copy-{uuid.uuid4().hex[:6]}'

    copy = manager.create_from_upload(db_session, doc, current_user='alice')
    db_session.commit()

    api = manager._build_contract_api_model(db_session, copy).model_dump(by_alias=True)
    assert api['sla'] == SLA_FORM


def test_a_field_left_empty_is_removed(db_session, imported):
    manager, cid = imported
    _save(manager, db_session, cid, {'sla': SLA_FORM})

    # The form leaves out an empty field
    contract = _save(manager, db_session, cid, {'sla': {'uptimeTarget': 99.5}})

    api = manager._build_contract_api_model(db_session, contract).model_dump(by_alias=True)
    assert api['sla'] == {'uptimeTarget': 99.5, 'maxDowntimeMinutes': None,
                          'queryResponseTimeMs': None, 'dataFreshnessMinutes': None}
    names = {r.property for r in db_session.query(DataContractSlaPropertyDb).filter_by(contract_id=cid)}
    assert names == {'latency', 'uptimeTarget'}


def test_a_contract_without_these_values_has_no_sla(db_session, imported):
    manager, cid = imported
    contract = db_session.get(DataContractDb, cid)

    api = manager._build_contract_api_model(db_session, contract).model_dump(by_alias=True)

    # Only the imported latency: nothing for the SLA card to show
    assert api['sla'] is None
    assert api['slaProperties'] == [{'property': 'latency', 'value': '4', 'valueExt': None, 'unit': 'd',
                                     'element': None, 'driver': None}]


def test_an_unreadable_value_is_skipped(db_session, imported):
    manager, cid = imported
    db_session.add(DataContractSlaPropertyDb(contract_id=cid, property='uptimeTarget', value='high'))
    db_session.commit()

    api = manager._build_contract_api_model(db_session, db_session.get(DataContractDb, cid)).model_dump(by_alias=True)

    assert api['sla'] is None


def test_odcs_sla_properties_can_be_replaced(db_session, imported):
    manager, cid = imported

    contract = _save(manager, db_session, cid, {
        'slaDefaultElement': 'orders.created_at',
        'slaProperties': [{'property': 'retention', 'value': 3, 'unit': 'y'}],
    })

    exported = manager.build_odcs_from_db(contract, db_session)
    assert exported['slaProperties'] == [{'property': 'retention', 'value': 3, 'unit': 'y'}]
    assert exported['slaDefaultElement'] == 'orders.created_at'


def test_servers_added_on_the_contract_page_are_saved(db_session, imported):
    manager, cid = imported

    contract = _save(manager, db_session, cid, {'servers': [
        {'server': 'prod', 'type': 'databricks', 'catalog': 'main', 'schema': 'sales'},
        {'server': 'dev', 'type': 'postgres', 'host': 'db.local', 'port': 5432, 'database': 'orders'},
    ]})

    exported = {s['server']: s for s in manager.build_odcs_from_db(contract, db_session)['servers']}
    assert exported['dev'] == {'server': 'dev', 'type': 'postgres', 'host': 'db.local', 'port': 5432,
                               'database': 'orders'}
    # The page doesn't send the server's ODCS id: it is kept
    assert exported['prod']['id'] == 'srv-prod'
    assert exported['prod']['schema'] == 'sales'


def test_deleting_the_last_server_saves_an_empty_list(db_session, imported):
    manager, cid = imported

    contract = _save(manager, db_session, cid, {'servers': []})

    assert 'servers' not in manager.build_odcs_from_db(contract, db_session)


def test_an_update_without_servers_or_sla_leaves_them_alone(db_session, imported):
    manager, cid = imported

    contract = _save(manager, db_session, cid, {'description': {'purpose': 'Orders'}})

    exported = manager.build_odcs_from_db(contract, db_session)
    assert [s['server'] for s in exported['servers']] == ['prod']
    assert exported['slaProperties'] == [{'property': 'latency', 'value': 4, 'unit': 'd'}]
