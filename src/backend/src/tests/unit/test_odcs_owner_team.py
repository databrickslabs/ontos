"""The contract's owner team in the ODCS export (#610).

ODCS has no field for the Ontos owner team, and the export left it out, so an
export imported again gave a contract without an owner team. The export
writes it as the custom property `ontosOwnerTeam` (`{id, name}`); the import
resolves it to an existing team, by id and then by name, and keeps it as a
custom property when no team matches.
"""
import copy
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import DataContractDb
from src.db_models.teams import TeamDb

PROPERTY = 'ontosOwnerTeam'


def _manager():
    return DataContractsManager(data_dir=Path("/tmp"))


def _odcs(**extra):
    return {
        'apiVersion': 'v3.1.0', 'kind': 'DataContract', 'id': str(uuid.uuid4()),
        'name': f'orders-{uuid.uuid4().hex[:6]}', 'version': '1.0.0', 'status': 'draft', **extra,
    }


def _upload(manager, db_session, document):
    contract = manager.create_from_upload(db_session, copy.deepcopy(document), current_user='alice')
    db_session.commit()
    return contract.id


def _export(manager, db_session, contract_id):
    db_session.expire_all()
    return manager.build_odcs_from_db(db_session.get(DataContractDb, contract_id), db_session)


def _owner_property(doc):
    return [cp['value'] for cp in doc.get('customProperties', []) if cp['property'] == PROPERTY]


@pytest.fixture
def team(db_session: Session):
    row = TeamDb(id=str(uuid.uuid4()), name=f'orders-team-{uuid.uuid4().hex[:6]}',
                 created_by='alice', updated_by='alice')
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture
def owned(db_session, team):
    manager = _manager()
    cid = _upload(manager, db_session, _odcs())
    db_session.get(DataContractDb, cid).owner_team_id = team.id
    db_session.commit()
    return manager, cid


def test_the_export_writes_the_owner_team(db_session, team, owned):
    manager, cid = owned

    assert _owner_property(_export(manager, db_session, cid)) == [
        {'id': team.id, 'name': team.name}]


def test_a_reimport_of_the_export_keeps_the_owner_team(db_session, team, owned):
    manager, cid = owned

    again = _upload(manager, db_session, _export(manager, db_session, cid))

    contract = db_session.get(DataContractDb, again)
    assert contract.owner_team_id == team.id
    # Resolved: not stored as a custom property, written again from the column
    assert all(cp.property != PROPERTY for cp in contract.custom_properties)
    assert _owner_property(_export(manager, db_session, again)) == [
        {'id': team.id, 'name': team.name}]


def test_the_team_is_found_by_name_when_the_id_is_unknown(db_session, team):
    manager = _manager()
    cid = _upload(manager, db_session, _odcs(customProperties=[
        {'property': PROPERTY, 'value': {'id': 'from-another-instance', 'name': team.name}}]))

    assert db_session.get(DataContractDb, cid).owner_team_id == team.id


def test_an_unknown_team_is_kept_as_a_custom_property(db_session):
    manager = _manager()
    value = {'id': 'nope', 'name': 'No such team'}
    cid = _upload(manager, db_session, _odcs(customProperties=[
        {'property': PROPERTY, 'value': value}]))

    assert db_session.get(DataContractDb, cid).owner_team_id is None
    assert _owner_property(_export(manager, db_session, cid)) == [value]


def test_a_contract_without_owner_team_exports_none(db_session):
    manager = _manager()

    cid = _upload(manager, db_session, _odcs())

    assert _owner_property(_export(manager, db_session, cid)) == []
