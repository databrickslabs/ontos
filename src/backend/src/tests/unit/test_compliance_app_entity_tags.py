"""Compliance rules see the tags assigned to app entities.

AppEntityLoader yielded ``tags: {}`` for data products, contracts and
domains, so ``HAS_TAG`` / ``TAG`` were never true for them, although tags are
assigned in the UI and in every demo preset.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from unittest.mock import patch

import pytest

from src.common.compliance_entities import AppEntityLoader
from src.controller.compliance_manager import ComplianceManager
from src.db_models.compliance import CompliancePolicyDb, ComplianceResultDb
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_domains import DataDomain
from src.db_models.data_products import DataProductDb
from src.db_models.tags import EntityTagAssociationDb, TagDb, TagNamespaceDb


def _suffix():
    return uuid.uuid4().hex[:8]


@pytest.fixture
def tags(db_session):
    namespace = TagNamespaceDb(name=f'regulatory-{_suffix()}')
    db_session.add(namespace)
    db_session.flush()
    made = {}
    for name in ('bcbs-239', 'risk-tier'):
        tag = TagDb(name=f'{name}-{_suffix()}', namespace_id=namespace.id, status='active')
        db_session.add(tag)
        made[name] = tag
    db_session.flush()
    return namespace, made


def _assign(db, tag, entity_id, entity_type, value=None):
    db.add(EntityTagAssociationDb(
        tag_id=tag.id, entity_id=entity_id, entity_type=entity_type, assigned_value=value,
    ))
    db.flush()


def _product(db, name):
    product = DataProductDb(
        id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct',
        status='active', name=f'{name}-{_suffix()}', version='1.0.0',
    )
    db.add(product)
    db.flush()
    return product


def _loaded(db, entity_type, entity_id):
    return next(
        e for e in AppEntityLoader(db).load_entities([entity_type]) if str(e['id']) == entity_id
    )


def test_product_tags_are_keyed_by_name_and_fqn(db_session, tags):
    namespace, made = tags
    product = _product(db_session, 'risk')
    _assign(db_session, made['bcbs-239'], product.id, 'data_product')
    _assign(db_session, made['risk-tier'], product.id, 'data_product', value='tier-1')

    loaded = _loaded(db_session, 'data_product', product.id)

    bcbs, tier = made['bcbs-239'].name, made['risk-tier'].name
    assert loaded['tags'] == {
        bcbs: True, f'{namespace.name}/{bcbs}': True,
        tier: 'tier-1', f'{namespace.name}/{tier}': 'tier-1',
    }


def test_untagged_product_has_no_tags(db_session, tags):
    product = _product(db_session, 'plain')

    assert _loaded(db_session, 'data_product', product.id)['tags'] == {}


def test_contract_and_domain_tags_are_loaded(db_session, tags):
    _, made = tags
    contract = DataContractDb(
        id=str(uuid.uuid4()), name=f'c-{_suffix()}', version='1.0.0', status='active',
        created_by='user@example.com',
    )
    domain = DataDomain(id=str(uuid.uuid4()), name=f'd-{_suffix()}', created_by='user@example.com')
    db_session.add_all([contract, domain])
    db_session.flush()
    _assign(db_session, made['bcbs-239'], contract.id, 'data_contract')
    _assign(db_session, made['risk-tier'], domain.id, 'data_domain', value='tier-2')

    assert made['bcbs-239'].name in _loaded(db_session, 'data_contract', contract.id)['tags']
    assert _loaded(db_session, 'domain', domain.id)['tags'][made['risk-tier'].name] == 'tier-2'


def test_a_tag_lookup_failure_keeps_the_entities(db_session, tags):
    product = _product(db_session, 'kept')

    with patch(
        'src.repositories.tags_repository.entity_tag_repo.get_assigned_tags_for_entities',
        side_effect=RuntimeError('db down'),
    ):
        loaded = _loaded(db_session, 'data_product', product.id)

    assert loaded['tags'] == {}


def test_has_tag_rules_evaluate_app_entity_tags(db_session, tags):
    _, made = tags
    bcbs, tier = made['bcbs-239'].name, made['risk-tier'].name
    tiered = _product(db_session, 'tiered')
    untiered = _product(db_session, 'untiered')
    _product(db_session, 'out-of-scope')
    _assign(db_session, made['bcbs-239'], tiered.id, 'data_product')
    _assign(db_session, made['risk-tier'], tiered.id, 'data_product', value='tier-1')
    _assign(db_session, made['bcbs-239'], untiered.id, 'data_product')
    policy = CompliancePolicyDb(
        id=str(uuid.uuid4()), name=f'BCBS 239 {_suffix()}',
        rule=(
            f"MATCH (p:data_product) WHERE HAS_TAG('{bcbs}') "
            f"ASSERT TAG('{tier}') = 'tier-1' ON_FAIL FAIL 'Not tiered'"
        ),
        category='Governance', severity='high', is_active=True,
    )
    db_session.add(policy)
    db_session.flush()

    with patch('src.common.workspace_client.get_workspace_client', return_value=None):
        run = ComplianceManager().run_policy_inline(db_session, policy=policy)

    results = {
        r.object_id: r.passed
        for r in db_session.query(ComplianceResultDb).filter(ComplianceResultDb.run_id == run.id)
    }
    assert results == {tiered.id: True, untiered.id: False}
