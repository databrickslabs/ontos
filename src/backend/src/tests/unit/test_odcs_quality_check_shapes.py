"""Quality checks with `tags` or an object `implementation` (#610).

ODCS gives a quality check `tags` (an array of strings) and lets a custom check's
`implementation` be a string or an object. Both were bound as-is to text
columns: the insert failed (SQLite) or wrote a Postgres array literal, and the
whole contract upload failed. They are stored as JSON and exported in the
shape they came in.
"""
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import DataContractDb, DataQualityCheckDb
from src.models.data_contracts_api import DataContractUpdate

IMPLEMENTATION = {'checks': [{'row_count > 0': None}], 'engine_options': {'strict': True}}


def _manager():
    return DataContractsManager(data_dir=Path("/tmp"))


def _odcs():
    return {
        'apiVersion': 'v3.1.0', 'kind': 'DataContract', 'id': str(uuid.uuid4()),
        'name': f'orders-{uuid.uuid4().hex[:6]}', 'version': '1.0.0', 'status': 'draft',
        'schema': [{
            'name': 'orders',
            'quality': [
                {'id': 'q-rows', 'type': 'library', 'metric': 'rowCount', 'mustBeGreaterThan': 0,
                 'tags': ['volume', 'daily']},
                {'id': 'q-impl-object', 'type': 'custom', 'engine': 'soda',
                 'implementation': IMPLEMENTATION, 'tags': ['custom']},
                {'id': 'q-impl-text', 'type': 'custom', 'engine': 'greatExpectations',
                 'implementation': 'checks:\n  - row_count > 0'},
            ],
            'properties': [{
                'name': 'order_id', 'logicalType': 'string',
                'quality': [{'id': 'q-null', 'type': 'library', 'metric': 'nullValues',
                             'mustBe': 0, 'tags': ['completeness']}],
            }],
        }],
    }


def _export(manager, db_session, contract_id):
    db_session.expire_all()
    return manager.build_odcs_from_db(db_session.get(DataContractDb, contract_id), db_session)


@pytest.fixture
def imported(db_session: Session):
    manager = _manager()
    contract = manager.create_from_upload(db_session, _odcs(), current_user='alice')
    db_session.commit()
    return manager, contract.id


def _checks(doc):
    obj = doc['schema'][0]
    checks = {q['id']: q for q in obj['quality']}
    checks.update({q['id']: q for q in obj['properties'][0]['quality']})
    return checks


def test_an_upload_with_check_tags_and_an_object_implementation_succeeds(db_session, imported):
    _, cid = imported

    rows = db_session.query(DataQualityCheckDb).join(DataQualityCheckDb.schema_object).filter_by(
        contract_id=cid).all()
    assert len(rows) == 4


def test_tags_and_implementations_are_exported_in_their_shape(db_session, imported):
    manager, cid = imported

    checks = _checks(_export(manager, db_session, cid))

    assert checks['q-rows']['tags'] == ['volume', 'daily']
    assert checks['q-null']['tags'] == ['completeness']
    assert checks['q-impl-object']['implementation'] == IMPLEMENTATION
    assert checks['q-impl-object']['tags'] == ['custom']
    assert checks['q-impl-text']['implementation'] == 'checks:\n  - row_count > 0'
    assert 'tags' not in checks['q-impl-text']


def test_tags_stored_as_text_by_the_check_form_go_out_as_a_list(db_session, imported):
    manager, cid = imported
    row = db_session.query(DataQualityCheckDb).filter_by(stable_id='q-impl-text').one()
    row.tags = 'volume, nightly'  # what the quality rule form stores
    db_session.commit()

    checks = _checks(_export(manager, db_session, cid))
    assert checks['q-impl-text']['tags'] == ['volume', 'nightly']


def test_the_contract_api_still_reads_the_checks(db_session, imported):
    manager, cid = imported

    api = manager._build_contract_api_model(db_session, db_session.get(DataContractDb, cid))

    rules = {r.query or r.rule or r.engine: r for r in api.quality_rules}
    assert len(api.quality_rules) == 4
    assert all(r.tags is None or isinstance(r.tags, str) for r in api.quality_rules)
    assert rules['soda'].implementation is not None


def test_an_update_with_odcs_tags_and_implementation_is_accepted(db_session, imported):
    manager, cid = imported
    body = {'qualityRules': [
        {'name': 'rows', 'type': 'library', 'rule': 'rowCount', 'mustBeGreaterThan': 1,
         'tags': ['volume']},
        {'name': 'impl', 'type': 'custom', 'engine': 'soda', 'implementation': IMPLEMENTATION},
    ]}

    manager.update_contract_with_relations(
        db_session, cid, DataContractUpdate.model_validate(body), current_user='alice')

    quality = {q['name']: q for q in _export(manager, db_session, cid)['schema'][0]['quality']}
    assert quality['rows']['tags'] == ['volume']
    assert quality['impl']['implementation'] == IMPLEMENTATION
