"""A column's `physicalName`, `description`, `transformDescription` and `tags` (#610).

None of them had a column of their own: the import stored the description in
`transform_description` and dropped `transformDescription`, `physicalName` and
`tags`; the export then wrote the description twice, a `physicalName` derived
from the name, and `tags: []`. They are stored, exported, returned to the schema
editor, and kept by an editor save and by a new version.
"""
import asyncio
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import DataContractDb, SchemaPropertyDb
from src.models.data_contracts_api import DataContractUpdate

ORDER_ID = {
    'name': 'order_id', 'logicalType': 'string', 'physicalName': 'ord_id_col',
    'description': 'The order number', 'transformDescription': 'Copied from the source system',
    'tags': ['pii', 'key'],
}
AMOUNT = {'name': 'Order Amount', 'logicalType': 'number'}


def _manager():
    return DataContractsManager(data_dir=Path("/tmp"))


def _odcs():
    return {
        'apiVersion': 'v3.1.0', 'kind': 'DataContract', 'id': str(uuid.uuid4()),
        'name': f'orders-{uuid.uuid4().hex[:6]}', 'version': '1.0.0', 'status': 'draft',
        'schema': [{'name': 'orders', 'properties': [dict(ORDER_ID), dict(AMOUNT)]}],
    }


def _export(manager, db_session, contract_id):
    db_session.expire_all()
    return manager.build_odcs_from_db(db_session.get(DataContractDb, contract_id), db_session)


def _columns(doc):
    return {p['name']: p for p in doc['schema'][0]['properties']}


@pytest.fixture
def imported(db_session: Session):
    manager = _manager()
    contract = manager.create_from_upload(db_session, _odcs(), current_user='alice')
    db_session.commit()
    return manager, contract.id


FIELDS = ('physicalName', 'description', 'transformDescription', 'tags')
EXPECTED = {k: ORDER_ID[k] for k in FIELDS}


def _fields(column):
    return {k: column.get(k) for k in FIELDS}


def test_the_column_fields_are_stored_apart(db_session, imported):
    _, cid = imported

    row = db_session.query(SchemaPropertyDb).filter_by(name='order_id').one()

    assert (row.physical_name, row.description, row.transform_description) == (
        'ord_id_col', 'The order number', 'Copied from the source system')


def test_the_export_writes_them_as_imported(db_session, imported):
    manager, cid = imported

    columns = _columns(_export(manager, db_session, cid))

    assert _fields(columns['order_id']) == EXPECTED
    # Nothing is made up for a column that has none of them
    assert not set(FIELDS) & set(columns['Order Amount'])


def _editor_save(manager, db_session, contract_id, edit=None):
    """What the schema editor sends: the object as the contract API returns it
    and its columns as the properties endpoint returns them."""
    from src.routes.data_contracts_routes import get_schema_properties

    contract = db_session.get(DataContractDb, contract_id)
    api = manager._build_contract_api_model(db_session, contract).model_dump(by_alias=True)
    obj = api['schema'][0]
    columns = asyncio.run(
        get_schema_properties(contract_id, obj['name'], db_session, limit=0))['items']
    if edit:
        edit(columns)
    form = {'name': obj['name'], 'properties': columns}
    manager.update_contract_with_relations(
        db_session, contract_id, DataContractUpdate.model_validate({'schema': [form]}),
        current_user='alice',
    )


def test_the_schema_editor_gets_them(db_session, imported):
    from src.routes.data_contracts_routes import get_schema_properties

    _, cid = imported

    items = asyncio.run(get_schema_properties(cid, 'orders', db_session, limit=0))['items']

    assert _fields({c['name']: c for c in items}['order_id']) == EXPECTED


def test_the_contract_api_returns_them(db_session, imported):
    manager, cid = imported

    api = manager._build_contract_api_model(db_session, db_session.get(DataContractDb, cid))

    column = api.model_dump(by_alias=True)['schema'][0]['properties'][0]
    assert {k: column.get(k) for k in ('physicalName', 'description', 'transformDescription')} == {
        k: ORDER_ID[k] for k in ('physicalName', 'description', 'transformDescription')}


def test_an_editor_save_keeps_them(db_session, imported):
    manager, cid = imported

    _editor_save(manager, db_session, cid)

    assert _fields(_columns(_export(manager, db_session, cid))['order_id']) == EXPECTED


def test_an_editor_save_changes_them_separately(db_session, imported):
    manager, cid = imported

    def edit(columns):
        column = next(c for c in columns if c['name'] == 'order_id')
        column['description'] = 'Order number (edited)'

    _editor_save(manager, db_session, cid, edit)

    column = _columns(_export(manager, db_session, cid))['order_id']
    assert column['description'] == 'Order number (edited)'
    assert column['transformDescription'] == 'Copied from the source system'


def test_a_new_version_keeps_them(db_session, imported):
    manager, cid = imported

    new = manager.clone_contract_for_new_version(db_session, cid, '2.0.0', current_user='alice')

    assert _fields(_columns(_export(manager, db_session, new.id))['order_id']) == EXPECTED
