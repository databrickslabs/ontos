"""Workflow rules on data products and contracts see their tags (#1151 item 7b).

``HAS_TAG`` / ``TAG`` read ``obj['tags']``, but the object rules see for a
product or contract (``entity_dict_builder``) had only ``has_tags`` and a
count, so ``HAS_TAG`` was always false there: the shipped contract rule
``obj.has_owner = true OR HAS_TAG('owner')`` reduced to ``has_owner``.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from pathlib import Path

import pytest
import yaml

from src.common.compliance_dsl import evaluate_rule_on_object
from src.controller.entity_dict_builder import build_data_contract_dict, build_data_product_dict
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb
from src.db_models.tags import EntityTagAssociationDb, TagDb, TagNamespaceDb

DEFAULT_WORKFLOWS = Path(__file__).resolve().parents[2] / 'data' / 'default_workflows.yaml'


def _suffix():
    return uuid.uuid4().hex[:8]


@pytest.fixture
def namespace(db_session):
    ns = TagNamespaceDb(name=f'governance-{_suffix()}')
    db_session.add(ns)
    db_session.flush()
    return ns


def _tag(db, namespace, name):
    tag = TagDb(name=name, namespace_id=namespace.id, status='active')
    db.add(tag)
    db.flush()
    return tag


def _assign(db, tag, entity_id, entity_type, value=None):
    db.add(EntityTagAssociationDb(
        tag_id=tag.id, entity_id=entity_id, entity_type=entity_type, assigned_value=value,
    ))
    db.flush()


def _contract(db, owner_team_id=None):
    contract = DataContractDb(
        id=str(uuid.uuid4()), name=f'c-{_suffix()}', version='1.0.0', status='draft',
        created_by='user@example.com', owner_team_id=owner_team_id,
    )
    db.add(contract)
    db.flush()
    return contract


def _owner_rule():
    data = yaml.safe_load(DEFAULT_WORKFLOWS.read_text())
    workflow = next(w for w in data['workflows'] if w['name'] == 'Data Contract Schema Validation')
    step = next(s for s in workflow['steps'] if s['id'] == 'check-owner')
    assert "HAS_TAG('owner')" in step['config']['rule']
    return step['config']['rule']


def test_product_dict_has_its_tags_and_keeps_the_count(db_session, namespace):
    product = DataProductDb(
        id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct',
        status='active', name=f'p-{_suffix()}', version='1.0.0',
    )
    db_session.add(product)
    db_session.flush()
    _assign(db_session, _tag(db_session, namespace, 'pii'), product.id, 'data_product')
    _assign(db_session, _tag(db_session, namespace, 'tier'), product.id, 'data_product', 'gold')

    built = build_data_product_dict(db_session, product.id)

    assert built['tags'] == {
        'pii': True, f'{namespace.name}/pii': True,
        'tier': 'gold', f'{namespace.name}/tier': 'gold',
    }
    assert {'tag_count', 'has_tags'} <= set(built)


def test_contract_dict_has_its_tags(db_session, namespace):
    contract = _contract(db_session)
    _assign(db_session, _tag(db_session, namespace, 'owner'), contract.id, 'data_contract',
            'alice@example.com')

    built = build_data_contract_dict(db_session, contract.id)

    assert built['tags']['owner'] == 'alice@example.com'


def test_an_untagged_contract_has_no_tags(db_session):
    assert build_data_contract_dict(db_session, _contract(db_session).id)['tags'] == {}


def test_the_shipped_owner_rule_passes_with_an_owner_tag_and_no_owner(db_session, namespace):
    contract = _contract(db_session)
    _assign(db_session, _tag(db_session, namespace, 'owner'), contract.id, 'data_contract',
            'alice@example.com')

    passed, _ = evaluate_rule_on_object(
        _owner_rule(), build_data_contract_dict(db_session, contract.id),
    )

    assert passed


def test_the_shipped_owner_rule_fails_with_neither(db_session):
    contract = _contract(db_session)

    passed, _ = evaluate_rule_on_object(
        _owner_rule(), build_data_contract_dict(db_session, contract.id),
    )

    assert not passed
