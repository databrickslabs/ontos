"""The workflow ``publish`` action applies the output-port contract rule of
``set_publication_scope`` and keeps the publication stamp on a scope change."""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.common.workflow_executor import EntityActionStepHandler, StepContext
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb, OutputPortDb


def _contract(db, status):
    contract = DataContractDb(
        id=str(uuid.uuid4()), name='orders-contract', version='1.0.0', status=status,
        version_family_id=str(uuid.uuid4()),
    )
    db.add(contract)
    db.flush()
    return contract


def _product(db, contract_id=None, scope='none', **published):
    product = DataProductDb(
        id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct', status='active',
        name='p', version='1.0.0', publication_scope=scope, **published,
    )
    db.add(product)
    db.flush()
    db.add(OutputPortDb(
        id=str(uuid.uuid4()), product_id=product.id, name='orders', version='1.0.0',
        contract_id=contract_id,
    ))
    db.flush()
    return product


def _publish(db, entity_type, entity_id, user='steward@example.com'):
    handler = EntityActionStepHandler(db, {'action': 'publish', 'scope_source': 'from_request'})
    context = StepContext(
        entity={'requested_scope': 'organization'}, entity_type=entity_type,
        entity_id=entity_id, entity_name='p', user_email=user, trigger_context=None,
        execution_id='x-1', workflow_id='w-1', workflow_name='Publication Request Review',
        step_results={},
    )
    with patch('src.common.workflow_triggers.get_trigger_registry', return_value=MagicMock()):
        return handler.execute(context)


def test_product_port_without_contract_is_not_published(db_session):
    product = _product(db_session)

    result = _publish(db_session, 'data_product', product.id)

    assert result.passed is False
    assert 'must have data contracts assigned' in result.error
    assert result.data == {
        'error_code': 'output_port_contracts_missing', 'error_params': {'ports': 'orders'},
    }
    db_session.refresh(product)
    assert product.publication_scope == 'none'
    assert product.published_at is None


def test_product_port_with_draft_contract_is_not_published(db_session):
    product = _product(db_session, contract_id=_contract(db_session, 'draft').id)

    result = _publish(db_session, 'data_product', product.id)

    assert result.passed is False
    assert result.data['error_code'] == 'output_port_contracts_unapproved'
    assert 'orders -> orders-contract (status: draft)' in result.data['error_params']['ports']
    db_session.refresh(product)
    assert product.publication_scope == 'none'


def test_product_with_approved_contract_is_published(db_session):
    product = _product(db_session, contract_id=_contract(db_session, 'approved').id)

    result = _publish(db_session, 'data_product', product.id)

    assert result.passed is True, result.error
    db_session.refresh(product)
    assert product.publication_scope == 'organization'
    assert product.published_by == 'steward@example.com'


def test_scope_change_keeps_who_published_and_when(db_session):
    stamp = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    product = _product(
        db_session, contract_id=_contract(db_session, 'active').id, scope='domain',
        published_at=stamp, published_by='alice@example.com',
    )

    result = _publish(db_session, 'data_product', product.id, user='bob@example.com')

    assert result.passed is True, result.error
    db_session.refresh(product)
    assert product.publication_scope == 'organization'
    assert product.published_by == 'alice@example.com'
    assert product.published_at.replace(tzinfo=None) == stamp.replace(tzinfo=None)


def test_contract_scope_change_keeps_who_published_and_when(db_session):
    stamp = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    contract = _contract(db_session, 'active')
    contract.publication_scope = 'domain'
    contract.published_at = stamp
    contract.published_by = 'alice@example.com'
    db_session.flush()

    result = _publish(db_session, 'data_contract', contract.id, user='bob@example.com')

    assert result.passed is True, result.error
    db_session.refresh(contract)
    assert contract.published_by == 'alice@example.com'
