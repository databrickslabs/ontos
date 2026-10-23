"""What #1077 left open in #295: the schema editor, new versions, quality names.

- Saving a schema in the schema editor recreates the schema object from what
  the editor sends, and the editor neither loads nor sends the ODCS ids, tags,
  custom properties and quality of the object, nor the ids, quality,
  relationships and authoritative definitions of its columns: all were lost.
  The primary key was lost too (the editor got `primaryKey: false`), and so were
  the granularity and the relationships (the contract API didn't return them).
- A new version didn't copy the quality checks, the relationships, the ODCS
  ids, the examples or the primary keys.
- A v3.1.0 library check went out as `rule` (v3.1.0 requires `metric`), a
  check's `name` went out as its `rule`, and the contract's `name` wasn't
  exported.
"""
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import DataContractDb, SchemaPropertyDb
from src.models.data_contracts_api import DataContractUpdate
from src.utils.schema_editor_fields import SEMANTIC_ASSIGNMENT

OBJECT = {
    'name': 'orders',
    'id': 'obj-orders',
    'physicalName': 'main.sales.orders',
    'physicalType': 'table',
    'businessName': 'Orders',
    'description': 'All orders',
    'dataGranularityDescription': 'One row per order',
    'tags': ['finance', 'gold'],
    'authoritativeDefinitions': [{'type': 'businessDefinition', 'url': 'https://wiki.example.com/orders'}],
    'customProperties': [{'property': 'zeta', 'value': 'z'}, {'property': 'alpha', 'value': 'a'}],
    'quality': [
        {'id': 'q-rows', 'name': 'enough rows', 'type': 'library', 'metric': 'rowCount', 'mustBeGreaterThan': 10},
        {'id': 'q-future', 'name': 'no future dates', 'type': 'sql',
         'query': 'SELECT COUNT(*) FROM orders WHERE order_date > current_date()', 'mustBe': 0},
    ],
    'relationships': [{'type': 'foreignKey', 'from': 'orders.customer_id', 'to': 'customers.id'}],
    'properties': [
        {
            'name': 'order_id', 'id': 'prop-order-id', 'logicalType': 'integer', 'physicalType': 'bigint',
            'required': True, 'primaryKey': True, 'primaryKeyPosition': 1, 'examples': ['1001', '1002'],
            'customProperties': [{'property': 'zeta', 'value': '1'}, {'property': 'alpha', 'value': '2'}],
            'authoritativeDefinitions': [{'type': 'businessDefinition', 'url': 'https://wiki.example.com/id'}],
            'quality': [{'id': 'q-id-null', 'name': 'order id not null', 'type': 'library',
                         'metric': 'nullValues', 'mustBe': 0}],
        },
        {
            'name': 'customer_id', 'id': 'prop-customer-id', 'logicalType': 'integer',
            'relationships': [{'type': 'foreignKey', 'to': 'customers.id'}],
        },
    ],
}


def _manager():
    return DataContractsManager(data_dir=Path("/tmp"))


def _odcs(api_version='v3.1.0'):
    return {
        'apiVersion': api_version,
        'kind': 'DataContract',
        'id': str(uuid.uuid4()),
        'name': f'orders-{uuid.uuid4().hex[:6]}',
        'version': '1.0.0',
        'status': 'draft',
        'schema': [OBJECT],
    }


@pytest.fixture
def imported(db_session: Session):
    manager = _manager()
    contract = manager.create_from_upload(db_session, _odcs(), current_user='alice')
    db_session.commit()
    db_session.refresh(contract)
    return manager, contract


def _export(manager, db_session, contract_id):
    db_session.expire_all()
    return manager.build_odcs_from_db(db_session.get(DataContractDb, contract_id), db_session)


def _object(doc):
    return doc['schema'][0]


def _columns(doc):
    return {p['name']: p for p in _object(doc)['properties']}


def _without_order(doc):
    """The schema object, its columns keyed by name (the column order is not
    stored: the editor lists them by name)."""
    obj = {k: v for k, v in _object(doc).items() if k != 'properties'}
    return obj, _columns(doc)


def _editor_save(manager, db_session, contract, edit=None):
    """What the schema editor sends: the object as the contract API returns
    it, its columns as the properties endpoint returns them, with the form's
    fields only."""
    from src.routes.data_contracts_routes import get_schema_properties
    import asyncio

    api = manager._build_contract_api_model(db_session, contract).model_dump(by_alias=True)
    obj = api['schema'][0]
    columns = asyncio.run(get_schema_properties(contract.id, obj['name'], db_session, limit=0))['items']
    form = {
        'name': obj['name'], 'physicalName': obj['physicalName'], 'description': obj['description'],
        'businessName': obj['businessName'], 'physicalType': obj['physicalType'],
        'dataGranularityDescription': obj['dataGranularityDescription'],
        'properties': columns, 'relationships': obj['relationships'],
    }
    if edit:
        edit(form)
    manager.update_contract_with_relations(
        db_session, contract.id, DataContractUpdate.model_validate({'schema': [form]}), current_user='alice',
    )


# --- export ---------------------------------------------------------------

def test_the_contract_name_is_exported(db_session, imported):
    manager, contract = imported
    assert _export(manager, db_session, contract.id)['name'] == contract.name


def test_quality_checks_keep_their_name_and_v3_1_metric(db_session, imported):
    manager, contract = imported

    doc = _export(manager, db_session, contract.id)

    rows, future = _object(doc)['quality']
    assert rows == OBJECT['quality'][0]
    # A SQL check's name used to become its `rule`
    assert future == OBJECT['quality'][1]
    assert _columns(doc)['order_id']['quality'] == OBJECT['properties'][0]['quality']


def test_a_v3_0_contract_exports_rule(db_session: Session):
    manager = _manager()
    odcs = _odcs('v3.0.2')
    contract = manager.create_from_upload(db_session, odcs, current_user='alice')
    db_session.commit()

    (rows, _) = _object(_export(manager, db_session, contract.id))['quality']

    assert rows['rule'] == 'rowCount' and 'metric' not in rows


def test_object_tags_export_as_a_list(db_session, imported):
    manager, contract = imported
    assert _object(_export(manager, db_session, contract.id))['tags'] == ['finance', 'gold']


def _transform_contract(db_session, manager, sources):
    odcs = _odcs()
    odcs['schema'] = [{
        'name': 'orders', 'tags': ['x'],
        'properties': [
            {'name': 'order_id', 'logicalType': 'string', 'transformSourceObjects': sources},
        ],
    }]
    contract = manager.create_from_upload(db_session, odcs, current_user='alice')
    db_session.commit()
    return contract


def test_transform_source_objects_and_tags_export_as_lists(db_session: Session):
    manager = _manager()
    contract = _transform_contract(db_session, manager, ['a.b', 'c.d'])

    doc = _export(manager, db_session, contract.id)

    # The JSON text it is stored as used to overwrite the parsed list
    assert _columns(doc)['order_id']['transformSourceObjects'] == ['a.b', 'c.d']
    assert _object(doc)['tags'] == ['x']


def test_a_legacy_transform_source_objects_string_is_exported_as_is(db_session: Session):
    manager = _manager()
    contract = _transform_contract(db_session, manager, ['a.b'])
    column = db_session.get(DataContractDb, contract.id).schema_objects[0].properties[0]
    column.transform_source_objects = 'a.b, c.d'
    db_session.commit()

    doc = _export(manager, db_session, contract.id)

    assert _columns(doc)['order_id']['transformSourceObjects'] == 'a.b, c.d'


# --- schema editor --------------------------------------------------------

def test_the_contract_api_returns_what_the_editor_sends_back(db_session, imported):
    manager, contract = imported

    obj = manager._build_contract_api_model(db_session, contract).model_dump(by_alias=True)['schema'][0]

    assert obj['dataGranularityDescription'] == 'One row per order'
    assert obj['stableId'] == 'obj-orders'
    assert [(r['type'], r['from'], r['to']) for r in obj['relationships']] == [
        ('foreignKey', 'orders.customer_id', 'customers.id')]
    order_id = next(p for p in obj['properties'] if p['name'] == 'order_id')
    assert order_id['primary_key'] is True  # by alias


def test_a_schema_editor_save_keeps_every_field(db_session, imported):
    manager, contract = imported
    before = _without_order(_export(manager, db_session, contract.id))

    _editor_save(manager, db_session, contract)

    assert _without_order(_export(manager, db_session, contract.id)) == before


def test_a_schema_editor_edit_is_saved_and_the_rest_kept(db_session, imported):
    manager, contract = imported

    def edit(form):
        form['description'] = 'Every order'
        next(p for p in form['properties'] if p['name'] == 'customer_id')['required'] = True

    _editor_save(manager, db_session, contract, edit)

    doc = _export(manager, db_session, contract.id)
    assert _object(doc)['description'] == 'Every order'
    assert _columns(doc)['customer_id']['required'] is True
    assert _columns(doc)['customer_id']['id'] == 'prop-customer-id'
    assert _columns(doc)['customer_id']['relationships'] == OBJECT['properties'][1]['relationships']
    assert _object(doc)['quality'] == OBJECT['quality']


def test_definitions_the_editor_doesnt_show_are_kept_beside_its_concepts(db_session, imported):
    # The editor only shows and sends semantic concepts
    manager, contract = imported
    concept = {'type': SEMANTIC_ASSIGNMENT, 'url': 'http://example.com/ontology#Order'}

    _editor_save(manager, db_session, contract,
                 lambda form: form.update(authoritativeDefinitions=[concept]))

    definitions = _object(_export(manager, db_session, contract.id))['authoritativeDefinitions']
    business = OBJECT['authoritativeDefinitions'][0]
    assert {(d['type'], d['url']) for d in definitions} == {
        (business['type'], business['url']), (concept['type'], concept['url'])}


def test_a_relationship_sent_through_the_api_keeps_its_from(db_session, imported):
    manager, contract = imported
    rel = {'type': 'foreignKey', 'from': 'orders.order_id', 'to': 'invoices.order_id'}

    _editor_save(manager, db_session, contract, lambda form: form.update(relationships=[rel]))

    assert _object(_export(manager, db_session, contract.id))['relationships'] == [rel]


def test_a_new_column_from_the_editor_is_added(db_session, imported):
    manager, contract = imported

    _editor_save(manager, db_session, contract, lambda form: form['properties'].append(
        {'name': 'amount', 'logicalType': 'number'}))

    columns = _columns(_export(manager, db_session, contract.id))
    assert columns['amount']['logicalType'] == 'number'
    assert columns['order_id']['quality'] == OBJECT['properties'][0]['quality']


# --- new versions ---------------------------------------------------------

def test_a_new_version_copies_the_whole_schema(db_session, imported):
    manager, contract = imported
    before = _without_order(_export(manager, db_session, contract.id))

    new = manager.clone_contract_for_new_version(db_session, contract.id, '2.0.0', current_user='alice')

    assert _without_order(_export(manager, db_session, new.id)) == before


def test_a_new_version_keeps_nested_columns(db_session: Session):
    from src.db_models.data_contracts import SchemaObjectDb
    manager = _manager()
    cid = str(uuid.uuid4())
    db_session.add(DataContractDb(id=cid, name=f'events-{cid[:6]}', version='1.0.0', status='draft'))
    db_session.add(SchemaObjectDb(id='o1', contract_id=cid, name='events'))
    # The child is stored before its parent
    db_session.add(SchemaPropertyDb(id='p-kind', object_id='o1', name='kind', logical_type='string',
                                    parent_property_id='p-payload'))
    db_session.add(SchemaPropertyDb(id='p-payload', object_id='o1', name='payload', logical_type='object'))
    db_session.commit()

    new = manager.clone_contract_for_new_version(db_session, cid, '2.0.0', current_user='alice')

    copied = {p.name: p for o in new.schema_objects for p in o.properties}
    assert copied['kind'].parent_property_id == copied['payload'].id != 'p-payload'
