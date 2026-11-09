"""An ODCS v3.1.0 contract file round-trips through import and export (#295).

Schema-object and property authoritativeDefinitions, schema-object
customProperties and object-level quality rules were dropped on import, the
ODCS names of the quality operators (mustBeGreaterThan ...) and `metric` were
not read, and the export added sample values (e.g. a "privacy-statement"
authoritativeDefinition) that were never in the contract.
"""
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from src.controller.data_contracts_manager import DataContractsManager

OBJECT_AUTH_DEFS = [{'type': 'businessDefinition', 'url': 'https://example.com/orders', 'id': 'ad-orders'}]
OBJECT_CUSTOM_PROPS = [
    {'property': 'retentionDays', 'value': 30},
    {'property': 'owner', 'value': 'finance', 'id': 'cp-owner'},
]
PROPERTY_AUTH_DEFS = [{'type': 'businessDefinition', 'url': 'https://example.com/order-id'}]
OBJECT_QUALITY = [{
    'id': 'q-rowcount', 'type': 'library', 'metric': 'rowCount',
    'mustBeGreaterThan': 0, 'description': 'Orders must not be empty',
}]
PROPERTY_QUALITY = [{
    'id': 'q-amount', 'type': 'library', 'rule': 'valueRange',
    'mustBeBetween': [0, 1000], 'mustNotBe': 'n/a',
}]


def _manager():
    return DataContractsManager(data_dir=Path("/tmp"))


def _odcs():
    return {
        'apiVersion': 'v3.1.0',
        'kind': 'DataContract',
        'id': str(uuid.uuid4()),
        'name': f'roundtrip-{uuid.uuid4().hex[:6]}',
        'version': '1.0.0',
        'status': 'draft',
        'contractCreatedTs': '2026-10-01T10:00:00Z',
        'schema': [{
            'id': 'obj-orders',
            'name': 'orders',
            'authoritativeDefinitions': OBJECT_AUTH_DEFS,
            'customProperties': OBJECT_CUSTOM_PROPS,
            'quality': OBJECT_QUALITY,
            'properties': [
                {
                    'id': 'prop-order-id', 'name': 'order_id', 'logicalType': 'string',
                    'authoritativeDefinitions': PROPERTY_AUTH_DEFS,
                },
                {
                    'name': 'amount', 'logicalType': 'number', 'quality': PROPERTY_QUALITY,
                },
            ],
        }],
    }


def _object(doc):
    return next(o for o in doc['schema'] if o['name'] == 'orders')


def _column(doc, name):
    return next(p for p in _object(doc)['properties'] if p['name'] == name)


def _without_ids(rules):
    return [{k: v for k, v in rule.items() if k != 'id'} for rule in rules]


@pytest.fixture
def exported(db_session: Session):
    manager = _manager()
    contract = manager.create_from_upload(db_session, _odcs(), current_user='alice')
    db_session.commit()
    db_session.refresh(contract)
    return manager, contract, manager.build_odcs_from_db(contract, db_session)


def test_schema_object_authoritative_definitions_round_trip(exported):
    _, _, doc = exported
    assert _object(doc)['authoritativeDefinitions'] == [
        {'url': d['url'], 'type': d['type'], 'id': d['id']} for d in OBJECT_AUTH_DEFS
    ]


def test_schema_object_custom_properties_round_trip(exported):
    _, _, doc = exported
    assert _object(doc)['customProperties'] == OBJECT_CUSTOM_PROPS


def test_property_authoritative_definitions_round_trip(exported):
    _, _, doc = exported
    assert _column(doc, 'order_id')['authoritativeDefinitions'] == PROPERTY_AUTH_DEFS


def test_object_level_quality_keeps_its_id_metric_and_operator(exported):
    _, _, doc = exported
    (rule,) = _object(doc)['quality']
    assert rule['id'] == 'q-rowcount'
    assert rule['metric'] == 'rowCount'  # a v3.1.0 library rule: `metric` (#295)
    assert rule['mustBeGreaterThan'] == 0
    assert rule['description'] == 'Orders must not be empty'


def test_property_quality_operators_use_the_odcs_names(exported):
    _, _, doc = exported
    (rule,) = _column(doc, 'amount')['quality']
    assert rule['mustBeBetween'] == [0, 1000]
    assert rule['mustNotBe'] == 'n/a'
    assert 'mustBeBetweenMin' not in rule and 'mustBeGt' not in rule


def test_contract_created_ts_is_exported_in_utc(exported):
    _, _, doc = exported
    assert doc['contractCreatedTs'] == '2026-10-01T10:00:00Z'


def test_the_export_adds_no_sample_values(db_session: Session):
    manager = _manager()
    odcs = _odcs()
    odcs['schema'][0]['properties'] = [
        {'name': 'transaction_reference_date', 'logicalType': 'date'},
        {'name': 'rcvr_cntry_code', 'logicalType': 'string'},
        {'name': 'rcvr_id', 'logicalType': 'string'},
    ]
    contract = manager.create_from_upload(db_session, odcs, current_user='alice')
    db_session.commit()
    db_session.refresh(contract)

    doc = manager.build_odcs_from_db(contract, db_session)

    assert 'authoritativeDefinitions' not in doc.get('description', {})
    for name in ('transaction_reference_date', 'rcvr_cntry_code', 'rcvr_id'):
        column = _column(doc, name)
        assert 'customProperties' not in column
        assert 'authoritativeDefinitions' not in column
        assert 'quality' not in column
        assert column['tags'] == []
    assert _column(doc, 'transaction_reference_date')['physicalName'] == 'transaction_reference_date'


def test_a_new_version_keeps_object_and_property_definitions(db_session: Session, exported):
    manager, contract, _ = exported

    new = manager.clone_contract_for_new_version(db_session, contract.id, '2.0.0', current_user='alice')
    doc = manager.build_odcs_from_db(new, db_session)

    assert _object(doc)['authoritativeDefinitions'] == [
        {'url': d['url'], 'type': d['type'], 'id': d['id']} for d in OBJECT_AUTH_DEFS
    ]
    assert _object(doc)['customProperties'] == OBJECT_CUSTOM_PROPS
    assert _column(doc, 'order_id')['authoritativeDefinitions'] == PROPERTY_AUTH_DEFS


def test_operator_columns_keep_zero_and_read_the_wizard_names():
    from src.utils.odcs_quality_operators import operator_columns

    columns = operator_columns({'mustBeGt': 0, 'mustBeBetweenMin': '1', 'mustBeBetweenMax': '9'})

    assert columns['must_be_gt'] == '0'  # `x or y` used to drop a 0
    assert (columns['must_be_between_min'], columns['must_be_between_max']) == ('1', '9')


def test_operators_export_with_the_odcs_names_and_their_types():
    from types import SimpleNamespace

    from src.utils.odcs_quality_operators import odcs_operators

    check = SimpleNamespace(
        must_be=None, must_not_be=None, must_be_gt='0', must_be_ge=None, must_be_lt=None,
        must_be_le='5.5', must_be_between_min=None, must_be_between_max=None,
        must_not_between_min='a', must_not_between_max='b',
    )

    assert odcs_operators(check) == {
        'mustBeGreaterThan': 0, 'mustBeLessOrEqualTo': 5.5, 'mustNotBeBetween': ['a', 'b'],
    }


def test_semantic_links_export_as_authoritative_definitions_roundtrip(
    db_session: Session,
):
    """Property-level semanticAssignment authoritativeDefinitions are imported
    as semantic links and exported back with label rebuilt from IRI tail.
    No schema property dict has a semanticConcepts key in export.
    """
    from src.controller.semantic_links_manager import SemanticLinksManager

    manager = _manager()
    semantic_assignment_type = 'http://databricks.com/ontology/uc/semanticAssignment'

    # Create ODCS with semanticAssignment authoritativeDefinition on a property
    odcs = _odcs()
    property_url = 'http://example.com/concepts/order_status'
    odcs['schema'][0]['properties'][0]['authoritativeDefinitions'] = [
        {'url': property_url, 'type': semantic_assignment_type}
    ]

    # Import contract
    contract = manager.create_from_upload(db_session, odcs, current_user='alice')
    db_session.commit()
    db_session.refresh(contract)

    # Verify semantic link was created for the property with label rebuilt from IRI
    semantic_links_manager = SemanticLinksManager(db_session)
    property_entity_id = f"{contract.id}#orders#order_id"
    links = semantic_links_manager.list_for_entity(
        entity_id=property_entity_id,
        entity_type='data_contract_property'
    )
    assert len(links) > 0, f"No semantic links found for {property_entity_id}"
    link = links[0]
    assert link.iri == property_url
    assert link.label == 'order status', f"Expected 'order status', got '{link.label}'"

    # Export and verify
    doc = manager.build_odcs_from_db(contract, db_session)
    property_in_export = _column(doc, 'order_id')

    # Verify semanticAssignment authoritativeDefinition is preserved
    assert 'authoritativeDefinitions' in property_in_export
    auth_defs = property_in_export['authoritativeDefinitions']
    assert any(d['type'] == semantic_assignment_type and d['url'] == property_url
               for d in auth_defs)

    # Verify no semanticConcepts in any schema property
    for schema_obj in doc.get('schema', []):
        for prop_dict in schema_obj.get('properties', []):
            assert 'semanticConcepts' not in prop_dict
