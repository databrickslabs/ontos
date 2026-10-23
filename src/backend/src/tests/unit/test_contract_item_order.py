"""A contract keeps the order of its columns and custom properties.

Columns, object custom properties and column custom properties had no order
column: they were read without ORDER BY (in whatever order Postgres returns
the rows) or by name. The columns API listed them by name, so a save from the
schema editor reordered a contract's columns alphabetically, and a table
rewrite (CLUSTER, pg_repack, a restore) could reorder the custom properties of
an export. They now carry a `position` (migration b6_contract_item_position).
"""
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import (
    DataContractDb,
    SchemaObjectCustomPropertyDb,
    SchemaObjectDb,
    SchemaPropertyCustomPropertyDb,
    SchemaPropertyDb,
)
from src.models.data_contracts_api import DataContractUpdate

CUSTOM = [{'property': 'zeta', 'value': 'z'}, {'property': 'alpha', 'value': 'a'},
          {'property': 'mid', 'value': 'm'}]
COLUMNS = ['order_id', 'customer_id', 'amount']


def _manager():
    return DataContractsManager(data_dir=Path("/tmp"))


@pytest.fixture
def imported(db_session: Session):
    manager = _manager()
    contract = manager.create_from_upload(db_session, {
        'apiVersion': 'v3.1.0', 'kind': 'DataContract', 'id': str(uuid.uuid4()),
        'name': f'orders-{uuid.uuid4().hex[:6]}', 'version': '1.0.0', 'status': 'draft',
        'schema': [{
            'name': 'orders', 'customProperties': CUSTOM,
            'properties': [{'name': n, 'logicalType': 'string', 'customProperties': CUSTOM} for n in COLUMNS],
        }],
    }, current_user='alice')
    db_session.commit()
    return manager, contract.id


def _export(manager, db_session, contract_id):
    db_session.expire_all()
    return manager.build_odcs_from_db(db_session.get(DataContractDb, contract_id), db_session)['schema'][0]


def _names(items, key='name'):
    return [i[key] for i in items]


def test_an_import_stores_the_document_order(db_session, imported):
    manager, cid = imported

    obj = _export(manager, db_session, cid)

    assert _names(obj['properties']) == COLUMNS
    assert _names(obj['customProperties'], 'property') == ['zeta', 'alpha', 'mid']
    assert _names(obj['properties'][0]['customProperties'], 'property') == ['zeta', 'alpha', 'mid']


def test_the_export_follows_the_position_not_the_row_order(db_session, imported):
    manager, cid = imported
    obj = db_session.query(SchemaObjectDb).filter_by(contract_id=cid).one()
    # Rows read back in another order (e.g. after a table rewrite): only the
    # stored position says where they go
    for row in db_session.query(SchemaObjectCustomPropertyDb).filter_by(schema_object_id=obj.id):
        db_session.delete(row)
    db_session.flush()
    for position, entry in reversed(list(enumerate(CUSTOM))):
        db_session.add(SchemaObjectCustomPropertyDb(
            schema_object_id=obj.id, property=entry['property'], value='"x"', position=position))
    db_session.commit()

    assert _names(_export(manager, db_session, cid)['customProperties'], 'property') == ['zeta', 'alpha', 'mid']


def test_the_columns_api_lists_the_contract_order(db_session, imported):
    import asyncio
    from src.routes.data_contracts_routes import get_schema_properties
    _, cid = imported

    items = asyncio.run(get_schema_properties(cid, 'orders', db_session, limit=0))['items']

    assert _names(items) == COLUMNS
    assert list(items[0]['customProperties']) == ['zeta', 'alpha', 'mid']


def test_a_schema_editor_save_keeps_the_column_order(db_session, imported):
    import asyncio
    from src.routes.data_contracts_routes import get_schema_properties
    manager, cid = imported
    columns = asyncio.run(get_schema_properties(cid, 'orders', db_session, limit=0))['items']

    manager.update_contract_with_relations(db_session, cid, DataContractUpdate.model_validate(
        {'schema': [{'name': 'orders', 'properties': columns}]}), current_user='alice')

    obj = _export(manager, db_session, cid)
    assert _names(obj['properties']) == COLUMNS
    assert _names(obj['properties'][1]['customProperties'], 'property') == ['zeta', 'alpha', 'mid']


def test_a_column_moved_in_the_editor_stays_where_it_was_put(db_session, imported):
    manager, cid = imported

    manager.update_contract_with_relations(db_session, cid, DataContractUpdate.model_validate(
        {'schema': [{'name': 'orders', 'properties': [
            {'name': n, 'logicalType': 'string'} for n in ['amount', 'order_id', 'customer_id']]}]}),
        current_user='alice')

    assert _names(_export(manager, db_session, cid)['properties']) == ['amount', 'order_id', 'customer_id']


def test_a_new_version_keeps_the_order(db_session, imported):
    manager, cid = imported

    new = manager.clone_contract_for_new_version(db_session, cid, '2.0.0', current_user='alice')

    obj = _export(manager, db_session, new.id)
    assert _names(obj['properties']) == COLUMNS
    assert _names(obj['customProperties'], 'property') == ['zeta', 'alpha', 'mid']
    assert _names(obj['properties'][2]['customProperties'], 'property') == ['zeta', 'alpha', 'mid']


def test_rows_without_a_position_come_last_by_name(db_session: Session):
    manager = _manager()
    cid = str(uuid.uuid4())
    db_session.add(DataContractDb(id=cid, name=f'c-{cid[:6]}', version='1.0.0', status='draft'))
    db_session.add(SchemaObjectDb(id=f'o-{cid}', contract_id=cid, name='t'))
    db_session.add(SchemaPropertyDb(id=f'p1-{cid}', object_id=f'o-{cid}', name='zz', position=None))
    db_session.add(SchemaPropertyDb(id=f'p2-{cid}', object_id=f'o-{cid}', name='bb', position=None))
    db_session.add(SchemaPropertyDb(id=f'p3-{cid}', object_id=f'o-{cid}', name='mm', position=0))
    db_session.add(SchemaPropertyCustomPropertyDb(property_id=f'p3-{cid}', property='y', value='1', position=None))
    db_session.add(SchemaPropertyCustomPropertyDb(property_id=f'p3-{cid}', property='x', value='1', position=0))
    db_session.commit()

    obj = _export(manager, db_session, cid)

    assert _names(obj['properties']) == ['mm', 'bb', 'zz']
    assert _names(obj['properties'][0]['customProperties'], 'property') == ['x', 'y']
