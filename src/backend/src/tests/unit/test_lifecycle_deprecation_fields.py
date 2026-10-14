"""Deprecation lifecycle fields on data products and data contracts.

Moving to ``deprecated`` needs a reason, a sunset date that isn't in the past
and, if given, a replacement that exists, isn't retired and isn't the entity
itself. Reactivation clears the sunset date and deprecation time.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.controller.change_log_manager import change_log_manager
from src.controller.data_contracts_manager import DataContractsManager
from src.controller.data_products_manager import DataProductsManager
from src.controller.lifecycle_fields import (
    DeprecationDetails,
    apply_lifecycle_fields,
    check_lifecycle_fields,
    requested_status_change_justification,
)
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb

_TOMORROW = date.today() + timedelta(days=1)


def _product(db, status='active'):
    product = DataProductDb(
        id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct',
        status=status, name='p', version='1.0.0',
    )
    db.add(product)
    db.flush()
    return product


def _contract(db, status='active'):
    contract = DataContractDb(
        id=str(uuid.uuid4()), name='c', version='1.0.0', status=status,
        version_family_id=str(uuid.uuid4()),
    )
    db.add(contract)
    db.flush()
    return contract


@pytest.mark.parametrize('details, message', [
    (None, 'reason is required'),
    (DeprecationDetails(reason='  '), 'reason is required'),
    (DeprecationDetails(reason='old', sunset_date=date(2020, 1, 1)), 'in the past'),
    (DeprecationDetails(reason='old', replacement_id='missing'), 'not found'),
])
def test_invalid_deprecations_are_rejected(db_session, details, message):
    product = _product(db_session)

    with pytest.raises(ValueError, match=message):
        check_lifecycle_fields(db_session, 'data_product', product.id, 'deprecated', details)


def test_an_entity_cant_replace_itself(db_session):
    product = _product(db_session)

    with pytest.raises(ValueError, match='own replacement'):
        check_lifecycle_fields(db_session, 'data_product', product.id, 'deprecated',
                               DeprecationDetails(reason='old', replacement_id=product.id))


def test_a_retired_replacement_is_rejected(db_session):
    product, retired = _product(db_session), _product(db_session, status='retired')

    with pytest.raises(ValueError, match='is retired'):
        check_lifecycle_fields(db_session, 'data_product', product.id, 'deprecated',
                               DeprecationDetails(reason='old', replacement_id=retired.id))


def test_other_transitions_need_no_details(db_session):
    product = _product(db_session)

    check_lifecycle_fields(db_session, 'data_product', product.id, 'retired', None)

    assert apply_lifecycle_fields(product, 'data_product', 'deprecated', 'retired', None) == {}


def test_reactivation_clears_the_sunset_date_and_deprecation_time(db_session):
    product = _product(db_session)
    apply_lifecycle_fields(product, 'data_product', 'active', 'deprecated',
                           DeprecationDetails(reason='old', sunset_date=_TOMORROW))

    changes = apply_lifecycle_fields(product, 'data_product', 'deprecated', 'active', None)

    assert changes['previous_sunset_date'] == _TOMORROW.isoformat()
    assert (product.sunset_date, product.deprecated_at) == (None, None)
    assert product.deprecation_reason == 'old'


def test_product_deprecation_stores_the_fields(db_session):
    product, replacement = _product(db_session), _product(db_session)
    manager = DataProductsManager(db=db_session)

    manager.transition_status(product.id, 'deprecated', 'alice@example.com', deprecation=(
        DeprecationDetails(reason=' Replaced by v2 ', sunset_date=_TOMORROW,
                           replacement_id=replacement.id)
    ))

    db_session.refresh(product)
    assert product.status == 'deprecated'
    assert product.deprecation_reason == 'Replaced by v2'
    assert product.sunset_date == _TOMORROW
    assert product.replacement_product_id == replacement.id
    assert product.deprecated_at is not None


def test_product_deprecation_without_reason_changes_nothing(db_session):
    product = _product(db_session)

    with pytest.raises(ValueError, match='reason is required'):
        DataProductsManager(db=db_session).transition_status(product.id, 'deprecated')

    db_session.refresh(product)
    assert product.status == 'active'


def test_contract_deprecation_stores_the_fields(db_session):
    contract, replacement = _contract(db_session), _contract(db_session)

    DataContractsManager(data_dir=Path('/tmp')).transition_status(
        db_session, contract.id, 'deprecated', 'bob@example.com',
        deprecation=DeprecationDetails(reason='Superseded', replacement_id=replacement.id),
    )

    db_session.refresh(contract)
    assert contract.status == 'deprecated'
    assert contract.deprecation_reason == 'Superseded'
    assert contract.replacement_contract_id == replacement.id


def test_the_latest_status_change_request_gives_the_reason(db_session):
    product = _product(db_session)
    for days_ago, justification in ((2, 'first request'), (1, 'latest request')):
        entry = change_log_manager.log_change_with_details(
            db_session, entity_type='data_product', entity_id=product.id,
            action='status_change_requested', username='alice',
            details={'target_status': 'deprecated', 'justification': justification},
        )
        entry.timestamp = datetime.now(timezone.utc) - timedelta(days=days_ago)
    db_session.flush()

    assert requested_status_change_justification(
        db_session, 'data_product', product.id
    ) == 'latest request'


def test_no_request_gives_no_reason(db_session):
    assert requested_status_change_justification(db_session, 'data_product', 'none') is None
