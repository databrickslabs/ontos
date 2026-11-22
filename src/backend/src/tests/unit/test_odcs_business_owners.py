"""A contract's business owners through ODCS export and re-import (#610).

The export merges the active business owners (the "Owners" card) into the
team as members with a mapped role, so a re-import made them imported team
contacts (e.g. a Business Sponsor came back as a "business steward" member),
not owners. The export also writes them as the custom property
`ontosOwners` (`[{email, name, role}]`); the import restores each one whose
business role exists as an owner, without a duplicate team member, and keeps
the others as a custom property. Restoring needs `business-owners` write (as
`POST /api/business-owners` does) and is audited as that route audits it.
"""
import copy
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.business_owners import BusinessOwnerDb
from src.db_models.business_roles import BusinessRoleDb
from src.db_models.data_contracts import DataContractDb
from src.utils.contract_owners import OwnerRestorer

PROPERTY = 'ontosOwners'


def _manager():
    return DataContractsManager(data_dir=Path("/tmp"))


def _odcs(**extra):
    return {
        'apiVersion': 'v3.1.0', 'kind': 'DataContract', 'id': str(uuid.uuid4()),
        'name': f'orders-{uuid.uuid4().hex[:6]}', 'version': '1.0.0', 'status': 'draft', **extra,
    }


def _upload(manager, db_session, document, restorer=None):
    contract = manager.create_from_upload(
        db_session, copy.deepcopy(document), current_user='alice',
        owner_restorer=restorer if restorer is not None else OwnerRestorer(allowed=True))
    db_session.commit()
    return contract.id


def _kept(manager, db_session, contract_id):
    return [cp['value'] for cp in _export(manager, db_session, contract_id)['customProperties']
            if cp['property'] == PROPERTY]


def _export(manager, db_session, contract_id):
    db_session.expire_all()
    return manager.build_odcs_from_db(db_session.get(DataContractDb, contract_id), db_session)


def _owners(db_session, contract_id):
    rows = db_session.query(BusinessOwnerDb).filter_by(
        object_type='data_contract', object_id=contract_id, is_active=True).all()
    return sorted((o.user_email, o.user_name, o.role.name) for o in rows)


@pytest.fixture
def role(db_session: Session):
    row = BusinessRoleDb(id=uuid.uuid4(), name=f'Business Sponsor {uuid.uuid4().hex[:4]}')
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture
def owned(db_session, role):
    manager = _manager()
    cid = _upload(manager, db_session, _odcs(team=[{'username': 'bob@example.com',
                                                    'role': 'steward'}]))
    db_session.add(BusinessOwnerDb(
        id=uuid.uuid4(), object_type='data_contract', object_id=cid,
        user_email='carol@example.com', user_name='Carol', role_id=role.id, is_active=True))
    db_session.commit()
    return manager, cid


def test_the_export_writes_the_owners(db_session, role, owned):
    manager, cid = owned

    props = [cp['value'] for cp in _export(manager, db_session, cid)['customProperties']
             if cp['property'] == PROPERTY]

    assert props == [[{'email': 'carol@example.com', 'name': 'Carol', 'role': role.name}]]


def test_a_reimport_restores_the_owners_not_as_team_contacts(db_session, role, owned):
    manager, cid = owned

    again = _upload(manager, db_session, _export(manager, db_session, cid))

    assert _owners(db_session, again) == [('carol@example.com', 'Carol', role.name)]
    contract = db_session.get(DataContractDb, again)
    assert [m.username for m in contract.team] == ['bob@example.com']
    assert all(cp.property != PROPERTY for cp in contract.custom_properties)
    # And the next export is the same
    assert _export(manager, db_session, again)['team'] == _export(manager, db_session, cid)['team']


def test_an_owner_with_an_unknown_role_is_kept_as_a_custom_property(db_session):
    manager = _manager()
    value = [{'email': 'dan@example.com', 'role': 'No such role'}]
    cid = _upload(manager, db_session, _odcs(customProperties=[
        {'property': PROPERTY, 'value': value}]))

    assert _owners(db_session, cid) == []
    exported = [cp['value'] for cp in _export(manager, db_session, cid)['customProperties']
                if cp['property'] == PROPERTY]
    assert exported == [value]


def test_without_the_permission_the_owners_stay_a_custom_property(db_session, role, owned):
    manager, cid = owned
    audited = []
    exported = _export(manager, db_session, cid)

    again = _upload(manager, db_session, exported,
                    OwnerRestorer(allowed=False, audit=audited.append))

    assert _owners(db_session, again) == []
    assert _kept(manager, db_session, again) == [
        [{'email': 'carol@example.com', 'name': 'Carol', 'role': role.name}]]
    # The member the export added stays a team contact, as before
    assert sorted(m.username for m in db_session.get(DataContractDb, again).team) == [
        'bob@example.com', 'carol@example.com']
    assert audited == []


def test_each_restored_owner_is_audited(db_session, role, owned):
    manager, cid = owned
    audited = []

    again = _upload(manager, db_session, _export(manager, db_session, cid),
                    OwnerRestorer(allowed=True, audit=audited.append))

    assert [a['params'] for a in audited] == [{
        'object': f'data_contract:{again}', 'user': 'carol@example.com',
        'role_id': str(role.id)}]
    assert audited[0]['created_resource_id']


def test_malformed_and_unknown_entries_stay_and_the_rest_is_restored(db_session, role):
    manager = _manager()
    bad = [{'email': 42, 'role': role.name}, {'email': 'not-an-email', 'role': role.name},
           {'email': 'x@example.com', 'role': ['list']}, 'text',
           {'email': 'y@example.com', 'role': role.name, 'name': 7},
           {'email': 'z@example.com', 'role': 'No such role'}]
    good = {'email': '  Erin@Example.com ', 'role': role.name, 'name': ' Erin '}
    cid = _upload(manager, db_session, _odcs(customProperties=[
        {'property': PROPERTY, 'value': bad + [good]}]))

    assert _owners(db_session, cid) == [('Erin@Example.com', 'Erin', role.name)]
    # The export writes the owner, then the entries the import kept
    assert _kept(manager, db_session, cid) == [
        [{'email': 'Erin@Example.com', 'name': 'Erin', 'role': role.name}] + bad]


def test_a_duplicate_entry_is_restored_once(db_session, role):
    manager = _manager()
    entries = [{'email': 'erin@example.com', 'role': role.name},
               {'email': 'ERIN@example.com', 'role': role.name}]
    cid = _upload(manager, db_session, _odcs(customProperties=[
        {'property': PROPERTY, 'value': entries}]))

    assert [o[0] for o in _owners(db_session, cid)] == ['erin@example.com']
    # The duplicate the import kept is the same owner: the export writes it once
    assert _kept(manager, db_session, cid) == [[entries[0]]]


def test_a_real_team_member_matching_an_owner_is_kept(db_session, role):
    manager = _manager()
    # Same person and mapped role as the owner, but not added by an export (no marker)
    team_role = role.name.lower()
    cid = _upload(manager, db_session, _odcs(
        team=[{'username': 'erin@example.com', 'role': team_role}],
        customProperties=[{'property': PROPERTY,
                           'value': [{'email': 'erin@example.com', 'role': role.name}]}]))

    assert [o[0] for o in _owners(db_session, cid)] == ['erin@example.com']
    assert [m.username for m in db_session.get(DataContractDb, cid).team] == ['erin@example.com']
