"""Edge cases of the typed ODCS values (#610 review follow-ups).

- Legacy text `NaN` / `Infinity` must stay text: decoded as floats they made
  the contract API answer 500 (not JSON compliant) and the export write `.nan`.
- Text values that read as JSON are stored JSON-quoted (`'"99.9"'`): the SLA
  form and the contract page's custom properties must read them as the text.
- A custom check's string `implementation` that looks like JSON stays a string.
"""
import copy
import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import (
    DataContractCustomPropertyDb, DataContractDb, DataContractRolePropertyDb,
    DataContractSlaPropertyDb,
)
from src.models.data_contracts_api import DataContractUpdate


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


def _api(manager, db_session, contract_id):
    db_session.expire_all()
    contract = db_session.get(DataContractDb, contract_id)
    return manager._build_contract_api_model(db_session, contract)


# --- NaN / Infinity -------------------------------------------------------

@pytest.mark.parametrize('text', ['NaN', 'Infinity', '-Infinity'])
def test_legacy_nan_text_stays_text(db_session, text):
    manager = _manager()
    cid = _upload(manager, db_session, _odcs(roles=[{'role': 'reader'}]))
    contract = db_session.get(DataContractDb, cid)
    db_session.add(DataContractSlaPropertyDb(contract_id=cid, property='p', value=text))
    db_session.add(DataContractCustomPropertyDb(contract_id=cid, property='c', value=text))
    db_session.add(DataContractRolePropertyDb(role_id=contract.roles[0].id, property='r',
                                              value=text))
    db_session.commit()

    api = _api(manager, db_session, cid)
    json.dumps(api.model_dump(mode='json'), allow_nan=False)  # the API answer is valid JSON
    doc = _export(manager, db_session, cid)
    json.dumps(doc, allow_nan=False, default=str)

    assert {s['property']: s['value'] for s in doc['slaProperties']}['p'] == text
    assert {c['property']: c['value'] for c in doc['customProperties']}['c'] == text
    assert doc['roles'][0]['customProperties'] == [{'property': 'r', 'value': text}]


@pytest.mark.parametrize('text', ['NaN', 'Infinity'])
def test_an_uploaded_nan_text_round_trips_as_text(db_session, text):
    manager = _manager()
    cid = _upload(manager, db_session, _odcs(
        slaProperties=[{'property': 'p', 'value': text}],
        customProperties=[{'property': 'c', 'value': text}]))

    doc = _export(manager, db_session, cid)

    assert doc['slaProperties'][0]['value'] == text
    assert {c['property']: c['value'] for c in doc['customProperties']}['c'] == text


# --- text that reads as JSON ----------------------------------------------

def test_the_sla_form_reads_an_sla_value_stored_json_quoted(db_session):
    manager = _manager()
    cid = _upload(manager, db_session, _odcs(
        slaProperties=[{'property': 'uptimeTarget', 'value': '99.9', 'unit': 'percent'}]))

    sla = _api(manager, db_session, cid).sla.model_dump(by_alias=True)
    assert 99.9 in sla.values()


def test_the_contract_page_shows_text_custom_properties_without_quotes(db_session):
    manager = _manager()
    cid = _upload(manager, db_session, _odcs(customProperties=[
        {'property': 'code', 'value': '42'}, {'property': 'flag', 'value': 'true'},
        {'property': 'plain', 'value': 'text'}, {'property': 'obj', 'value': {'a': 1}}]))

    shown = _api(manager, db_session, cid).customProperties

    assert (shown['code'], shown['flag'], shown['plain']) == ('42', 'true', 'text')
    assert json.loads(shown['obj']) == {'a': 1}  # objects stay JSON text, as the page expects


def test_saving_the_page_map_keeps_text_and_types(db_session):
    manager = _manager()
    custom = [{'property': 'code', 'value': '42'}, {'property': 'num', 'value': 42},
              {'property': 'flag', 'value': True}, {'property': 'obj', 'value': {'a': 1}}]
    cid = _upload(manager, db_session, _odcs(customProperties=custom))

    for _ in range(2):
        shown = _api(manager, db_session, cid).customProperties
        manager.update_contract_with_relations(
            db_session, cid, DataContractUpdate.model_validate({'customProperties': shown}),
            current_user='alice')

    exported = {c['property']: c['value'] for c in _export(manager, db_session, cid)[
        'customProperties']}
    for item in custom:
        assert (type(exported[item['property']]), exported[item['property']]) == (
            type(item['value']), item['value'])


# --- implementation -------------------------------------------------------

@pytest.mark.parametrize('implementation', ['{"checks": ["row_count > 0"]}', '[1, 2]', '"x"'])
def test_a_string_implementation_that_looks_like_json_stays_a_string(db_session, implementation):
    manager = _manager()
    cid = _upload(manager, db_session, _odcs(schema=[{'name': 'orders', 'quality': [
        {'id': 'q', 'type': 'custom', 'engine': 'soda', 'implementation': implementation}]}]))

    check = _export(manager, db_session, cid)['schema'][0]['quality'][0]

    assert check['implementation'] == implementation
