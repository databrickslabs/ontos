"""set-publication-scope goes through the publish checks and triggers (#947).

Products need every output port to have an approved / active contract, as
``publish_product`` does; publishing fires ``on_publish`` and unpublishing
fires ``on_unpublish``, for products and contracts.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.common.api_errors import CodedValueError
from src.controller.data_contracts_manager import DataContractsManager
from src.controller.data_products_manager import DataProductsManager
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb, OutputPortDb


def _contract(db, status='approved', scope='none'):
    contract = DataContractDb(
        id=str(uuid.uuid4()), name='c', version='1.0.0', status=status,
        version_family_id=str(uuid.uuid4()), publication_scope=scope,
    )
    db.add(contract)
    db.flush()
    return contract


def _product(db, contract_id=None, status='active', scope='none'):
    product = DataProductDb(
        id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct',
        status=status, name='p', version='1.0.0', publication_scope=scope,
    )
    db.add(product)
    db.flush()
    db.add(OutputPortDb(
        id=str(uuid.uuid4()), product_id=product.id, name='orders', version='1.0.0',
        contract_id=contract_id,
    ))
    db.flush()
    return product


@pytest.fixture
def registry():
    registry = MagicMock()
    with patch('src.common.workflow_triggers.get_trigger_registry', return_value=registry):
        yield registry


def test_product_port_without_contract_is_not_published(db_session, registry):
    product = _product(db_session)

    with pytest.raises(ValueError, match='must have data contracts assigned'):
        DataProductsManager(db=db_session).set_publication_scope(product.id, 'organization')

    db_session.refresh(product)
    assert product.publication_scope == 'none'
    registry.on_publish.assert_not_called()


def test_product_port_with_draft_contract_is_not_published(db_session, registry):
    product = _product(db_session, contract_id=_contract(db_session, status='draft').id)

    with pytest.raises(ValueError, match='unapproved contracts'):
        DataProductsManager(db=db_session).set_publication_scope(product.id, 'organization')


def test_inactive_product_is_not_published(db_session, registry):
    product = _product(db_session, contract_id=_contract(db_session).id, status='approved')

    with pytest.raises(ValueError, match='must be active'):
        DataProductsManager(db=db_session).set_publication_scope(product.id, 'organization')


def test_publishing_a_product_fires_on_publish_once(db_session, registry):
    product = _product(db_session, contract_id=_contract(db_session).id)
    manager = DataProductsManager(db=db_session)

    manager.set_publication_scope(product.id, 'organization', 'alice@example.com')
    manager.set_publication_scope(product.id, 'domain', 'alice@example.com')

    db_session.refresh(product)
    assert product.publication_scope == 'domain'
    assert product.published_by == 'alice@example.com'
    registry.on_publish.assert_called_once()
    assert registry.on_publish.call_args.kwargs['entity_data']['publication_scope'] == (
        'organization'
    )


def test_changing_the_scope_keeps_who_published_and_when(db_session, registry):
    product = _product(db_session, contract_id=_contract(db_session).id)
    manager = DataProductsManager(db=db_session)

    manager.set_publication_scope(product.id, 'organization', 'alice@example.com')
    db_session.refresh(product)
    published_at = product.published_at

    manager.set_publication_scope(product.id, 'domain', 'bob@example.com')

    db_session.refresh(product)
    assert product.publication_scope == 'domain'
    assert product.published_by == 'alice@example.com'
    assert product.published_at == published_at


def test_publishing_again_after_unpublishing_stamps_the_new_publication(db_session, registry):
    product = _product(db_session, contract_id=_contract(db_session).id)
    manager = DataProductsManager(db=db_session)

    manager.set_publication_scope(product.id, 'organization', 'alice@example.com')
    manager.set_publication_scope(product.id, 'none', 'alice@example.com')
    manager.set_publication_scope(product.id, 'domain', 'bob@example.com')

    db_session.refresh(product)
    assert product.published_by == 'bob@example.com'


def test_refused_publication_errors_carry_a_code(db_session, registry):
    no_contract = _product(db_session)
    draft = _product(db_session, contract_id=_contract(db_session, status='draft').id)
    manager = DataProductsManager(db=db_session)

    with pytest.raises(CodedValueError) as missing:
        manager.set_publication_scope(no_contract.id, 'organization')
    with pytest.raises(CodedValueError) as unapproved:
        manager.set_publication_scope(draft.id, 'organization')

    assert missing.value.code == 'output_port_contracts_missing'
    assert missing.value.params == {'ports': 'orders'}
    assert unapproved.value.code == 'output_port_contracts_unapproved'
    assert 'orders -> c (status: draft)' in unapproved.value.params['ports']


def test_unpublishing_a_product_fires_on_unpublish_only_when_it_was_published(
    db_session, registry
):
    published = _product(db_session, scope='organization')
    unpublished = _product(db_session)
    manager = DataProductsManager(db=db_session)

    manager.set_publication_scope(published.id, 'none')
    manager.set_publication_scope(unpublished.id, 'none')

    db_session.refresh(published)
    assert published.publication_scope == 'none'
    assert published.published_at is None
    registry.on_unpublish.assert_called_once()
    assert registry.on_unpublish.call_args.args[1] == published.id


def _contracts_manager():
    return DataContractsManager(data_dir=Path('/tmp'))


def test_changing_the_scope_of_a_contract_keeps_who_published_and_when(db_session, registry):
    contract = _contract(db_session)
    manager = _contracts_manager()

    manager.set_publication_scope(db_session, contract.id, 'organization', 'bob@example.com')
    db_session.refresh(contract)
    published_at = contract.published_at
    manager.set_publication_scope(db_session, contract.id, 'domain', 'carol@example.com')

    db_session.refresh(contract)
    assert contract.publication_scope == 'domain'
    assert contract.published_by == 'bob@example.com'
    assert contract.published_at == published_at


def test_draft_contract_is_not_published(db_session, registry):
    contract = _contract(db_session, status='draft')

    with pytest.raises(ValueError, match='active or approved'):
        _contracts_manager().set_publication_scope(db_session, contract.id, 'organization')

    registry.on_publish.assert_not_called()


def test_publishing_and_unpublishing_a_contract_fire_the_triggers(db_session, registry):
    contract = _contract(db_session)
    manager = _contracts_manager()

    manager.set_publication_scope(db_session, contract.id, 'organization', 'bob@example.com')
    manager.set_publication_scope(db_session, contract.id, 'none', 'bob@example.com')

    registry.on_publish.assert_called_once()
    registry.on_unpublish.assert_called_once()
    db_session.refresh(contract)
    assert contract.publication_scope == 'none'


def test_a_port_pointing_to_a_deleted_contract_is_not_published(db_session, registry):
    product = _product(db_session, contract_id='deleted-contract')

    with pytest.raises(ValueError, match='contract not found'):
        DataProductsManager(db=db_session).set_publication_scope(product.id, 'organization')


def test_the_request_session_is_used_when_given(db_session, registry):
    # The manager singleton's own session is shared across requests; routes
    # pass their request session.
    product = _product(db_session, contract_id=_contract(db_session).id)
    manager = DataProductsManager(db=MagicMock())

    manager.set_publication_scope(product.id, 'organization', 'alice@example.com', db=db_session)

    db_session.refresh(product)
    assert product.publication_scope == 'organization'


def test_a_trigger_error_keeps_the_publication_and_is_logged_as_an_error(
    db_session, registry, caplog
):
    registry.on_publish.side_effect = RuntimeError('workflow engine down')
    product = _product(db_session, contract_id=_contract(db_session).id)
    contract = _contract(db_session)

    with caplog.at_level('ERROR'):
        DataProductsManager(db=db_session).set_publication_scope(product.id, 'organization')
        _contracts_manager().set_publication_scope(db_session, contract.id, 'organization')

    db_session.refresh(product)
    db_session.refresh(contract)
    assert product.publication_scope == 'organization'
    assert contract.publication_scope == 'organization'
    errors = [r.getMessage() for r in caplog.records if r.levelname == 'ERROR']
    assert f'Publication trigger failed for data product {product.id}' in errors
    assert f'Publication trigger failed for data contract {contract.id}' in errors
