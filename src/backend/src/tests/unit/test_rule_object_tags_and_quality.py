"""Rules on products and contracts see all their tags and their quality items (#1151).

An assign-tag step puts only the tag it set in the payload's ``tags``; merged over the
stored entity that partial dict replaced every stored tag, so a later
``HAS_TAG('owner')`` was false on a product tagged ``owner``. And ``quality_check_count``
looked quality items up under ``DataProduct`` / ``DataContract`` while ``QualityManager``
stores them under ``data_product`` / ``data_contract``, so it was always 0.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid

import pytest

from src.common.workflow_executor import (
    AssignTagStepHandler,
    StepContext,
    ValidationStepHandler,
    _rule_object,
)
from src.controller.entity_dict_builder import build_data_contract_dict, build_data_product_dict
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb
from src.db_models.quality import QualityItemDb
from src.db_models.tags import EntityTagAssociationDb, TagDb, TagNamespaceDb


def _suffix():
    return uuid.uuid4().hex[:8]


def _product(db):
    product = DataProductDb(
        id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct',
        status='active', name=f'p-{_suffix()}', version='1.0.0',
    )
    db.add(product)
    db.flush()
    return product


def _contract(db):
    contract = DataContractDb(
        id=str(uuid.uuid4()), name=f'c-{_suffix()}', version='1.0.0', status='draft',
        created_by='user@example.com',
    )
    db.add(contract)
    db.flush()
    return contract


def _tag(db, name, entity_id=None, entity_type=None):
    namespace = TagNamespaceDb(name=f'governance-{_suffix()}')
    db.add(namespace)
    db.flush()
    tag = TagDb(name=name, namespace_id=namespace.id, status='active')
    db.add(tag)
    db.flush()
    if entity_id:
        db.add(EntityTagAssociationDb(tag_id=tag.id, entity_id=entity_id, entity_type=entity_type))
        db.flush()
    return tag, f'{namespace.name}/{name}'


def _context(entity_type, entity_id):
    return StepContext(
        entity={}, entity_type=entity_type, entity_id=entity_id, entity_name='E',
        user_email='u@example.com', trigger_context=None, execution_id='exec-1',
        workflow_id='wf-1', workflow_name='W', step_results={},
    )


@pytest.mark.parametrize('gdpr_exists', [False, True], ids=['context-only', 'persisted'])
def test_a_rule_after_an_assign_tag_step_still_sees_the_stored_tags(db_session, gdpr_exists):
    product = _product(db_session)
    _tag(db_session, 'owner', product.id, 'data_product')
    key = _tag(db_session, 'gdpr')[1] if gdpr_exists else 'gdpr'
    context = _context('data_product', product.id)

    assigned = AssignTagStepHandler(db_session, {'key': key, 'value': 'yes'}).execute(context)
    assert assigned.passed, assigned.error
    assert context.entity['tags'] == {key: 'yes'}

    result = ValidationStepHandler(db_session, {
        'rule': f"MATCH (obj:data_product) ASSERT HAS_TAG('owner') AND HAS_TAG('{key}')",
    }).execute(context)

    assert result.passed, result.error


def test_payload_tags_override_the_stored_value_of_the_same_tag(db_session):
    product = _product(db_session)
    _, fqn = _tag(db_session, 'tier', product.id, 'data_product')
    context = _context('data_product', product.id)
    context.entity['tags'] = {'tier': 'gold'}

    tags = _rule_object(db_session, context)['tags']

    assert tags == {'tier': 'gold', fqn: True}


def test_tag_count_counts_the_assignments_it_lists(db_session):
    product = _product(db_session)
    _tag(db_session, 'owner', product.id, 'data_product')
    _tag(db_session, 'pii', product.id, 'data_product')

    built = build_data_product_dict(db_session, product.id)

    assert built['tag_count'] == 2
    assert built['has_tags'] is True
    assert {'owner', 'pii'} <= set(built['tags'])


def _quality_item(db, entity_type, entity_id):
    db.add(QualityItemDb(
        entity_type=entity_type, entity_id=entity_id, dimension='completeness',
        source='manual', score_percent=95.0,
    ))
    db.flush()


@pytest.mark.parametrize('make, build, entity_type', [
    (_product, build_data_product_dict, 'data_product'),
    (_contract, build_data_contract_dict, 'data_contract'),
])
def test_quality_check_count_counts_the_items_quality_manager_stores(
    db_session, make, build, entity_type,
):
    entity = make(db_session)
    _quality_item(db_session, entity_type, entity.id)
    _quality_item(db_session, entity_type, entity.id)

    built = build(db_session, entity.id)

    assert built['quality_check_count'] == 2
    assert built['has_quality_checks'] is True


def test_quality_items_created_through_the_manager_are_counted(db_session):
    from src.controller.quality_manager import QualityManager
    from src.models.quality import QualityItemCreate

    contract = _contract(db_session)
    QualityManager().create(db_session, data=QualityItemCreate(
        entity_type='data_contract', entity_id=contract.id, dimension='accuracy',
        source='manual', score_percent=80.0,
    ), user_email='user@example.com')

    assert build_data_contract_dict(db_session, contract.id)['quality_check_count'] == 1
