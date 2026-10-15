"""Contract team member names reach the API model and the MCP projection.

``_build_contract_api_model`` copied username / role / dates but not the
stored ``name``, so GET /api/data-contracts/{id} and the get_data_contract
tool returned ``name: null`` for every member.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from pathlib import Path

from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import DataContractDb, DataContractTeamDb
from src.repositories.data_contracts_repository import data_contract_repo
from src.tools.data_contracts import _serialize_contract


def _contract_with_member(db, name):
    contract = DataContractDb(
        id=str(uuid.uuid4()), name='c', version='1.0.0', status='draft',
        version_family_id=str(uuid.uuid4()),
    )
    db.add(contract)
    db.flush()
    db.add(DataContractTeamDb(
        id=str(uuid.uuid4()), contract_id=contract.id, username='jane@example.com',
        name=name, role='steward',
    ))
    db.flush()
    return data_contract_repo.get_with_all(db, id=contract.id)


def _build(db, db_contract):
    return DataContractsManager(data_dir=Path('/tmp'))._build_contract_api_model(db, db_contract)


def test_the_member_name_reaches_the_api_model_and_the_mcp_projection(db_session):
    contract = _build(db_session, _contract_with_member(db_session, 'Jane Steward'))

    assert [(m.username, m.name) for m in contract.team] == [('jane@example.com', 'Jane Steward')]
    assert _serialize_contract(contract)['team'][0]['name'] == 'Jane Steward'


def test_a_member_without_name_stays_without_name(db_session):
    contract = _build(db_session, _contract_with_member(db_session, None))

    assert contract.team[0].name is None
