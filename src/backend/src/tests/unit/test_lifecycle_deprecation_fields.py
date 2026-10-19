"""Deprecation lifecycle fields on data products and data contracts.

Moving to ``deprecated`` needs a reason, a sunset date that isn't in the past
(UTC) and, if given, a replacement that exists, isn't deprecated or retired,
isn't the entity itself and doesn't lead back to it. Reactivation clears the
sunset date and deprecation time. Imports check the replacement too.
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
    imported_lifecycle_columns,
    lifecycle_custom_properties,
    pop_lifecycle_custom_properties,
    requested_status_change_justification,
    set_lifecycle_columns,
    utc_today,
)
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb

_TOMORROW = utc_today() + timedelta(days=1)


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


def _deprecated_toward(entity, replacement, entity_type='data_product'):
    entity.status = 'deprecated'
    column = 'replacement_product_id' if entity_type == 'data_product' else 'replacement_contract_id'
    setattr(entity, column, replacement.id)


def test_a_deprecated_replacement_is_rejected_with_its_chain(db_session):
    product, old, newest = _product(db_session), _product(db_session), _product(db_session)
    _deprecated_toward(old, newest)
    db_session.flush()

    with pytest.raises(ValueError, match=f'{old.id} is deprecated; it is replaced by {newest.id}'):
        check_lifecycle_fields(db_session, 'data_product', product.id, 'deprecated',
                               DeprecationDetails(reason='old', replacement_id=old.id))


@pytest.mark.parametrize('length', [1, 3])
def test_a_replacement_that_leads_back_is_rejected(db_session, length):
    # product -> r1 (-> r2 -> r3) -> product
    product = _product(db_session)
    chain = [_product(db_session) for _ in range(length)]
    for entity, replacement in zip(chain, chain[1:] + [product]):
        _deprecated_toward(entity, replacement)
    db_session.flush()

    with pytest.raises(ValueError, match='leads back to this entity'):
        check_lifecycle_fields(db_session, 'data_product', product.id, 'deprecated',
                               DeprecationDetails(reason='old', replacement_id=chain[0].id))


def test_a_contract_replacement_that_leads_back_is_rejected(db_session):
    contract, replacement = _contract(db_session), _contract(db_session)
    _deprecated_toward(replacement, contract, 'data_contract')
    db_session.flush()

    with pytest.raises(ValueError, match='leads back to this entity'):
        check_lifecycle_fields(db_session, 'data_contract', contract.id, 'deprecated',
                               DeprecationDetails(reason='old', replacement_id=replacement.id))


def test_a_cycle_among_other_entities_does_not_loop(db_session):
    product, a, b = _product(db_session), _product(db_session), _product(db_session)
    _deprecated_toward(a, b)
    _deprecated_toward(b, a)
    db_session.flush()

    with pytest.raises(ValueError, match='is deprecated'):
        check_lifecycle_fields(db_session, 'data_product', product.id, 'deprecated',
                               DeprecationDetails(reason='old', replacement_id=a.id))


def test_the_sunset_date_is_checked_against_the_utc_date(db_session):
    product = _product(db_session)

    check_lifecycle_fields(db_session, 'data_product', product.id, 'deprecated',
                           DeprecationDetails(reason='old', sunset_date=utc_today()))
    with pytest.raises(ValueError, match='in the past'):
        check_lifecycle_fields(
            db_session, 'data_product', product.id, 'deprecated',
            DeprecationDetails(reason='old', sunset_date=utc_today() - timedelta(days=1)),
        )


def test_utc_today_is_the_utc_date():
    assert utc_today() == datetime.now(timezone.utc).date()


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


# --- ODPS / ODCS round-trip ------------------------------------------------


def test_export_lists_only_the_set_fields(db_session):
    product = _product(db_session, status='deprecated')
    product.deprecation_reason = 'Replaced by v2'
    product.sunset_date = date(2027, 1, 31)

    assert lifecycle_custom_properties(product, 'data_product') == {
        'ontosDeprecationReason': 'Replaced by v2',
        'ontosSunsetDate': '2027-01-31',
    }


@pytest.mark.parametrize('custom_props', [
    [{'property': 'owner', 'value': 'x'},
     {'property': 'ontosSunsetDate', 'value': '2027-01-31'},
     {'property': 'ontosReplacedBy', 'value': 'c2'}],
    {'owner': 'x', 'ontosSunsetDate': '2027-01-31', 'ontosReplacedBy': 'c2'},
])
def test_import_moves_the_lifecycle_properties_out_of_custom_properties(custom_props):
    found = pop_lifecycle_custom_properties(custom_props)

    assert found == {'ontosSunsetDate': '2027-01-31', 'ontosReplacedBy': 'c2'}
    remaining = custom_props if isinstance(custom_props, dict) else {
        c['property']: c['value'] for c in custom_props
    }
    assert remaining == {'owner': 'x'}


def test_imported_properties_set_the_columns(db_session):
    contract, replacement = _contract(db_session), _contract(db_session)

    set_lifecycle_columns(contract, imported_lifecycle_columns(
        db_session, 'data_contract', contract.id, {
            'ontosDeprecationReason': 'Superseded',
            'ontosSunsetDate': '2027-03-31',
            'ontosReplacedBy': replacement.id,
            'ontosDeprecatedAt': '2026-10-14T06:07:43Z',
        },
    ))

    assert contract.deprecation_reason == 'Superseded'
    assert contract.sunset_date == date(2027, 3, 31)
    assert contract.replacement_contract_id == replacement.id
    assert contract.deprecated_at == datetime(2026, 10, 14, 6, 7, 43, tzinfo=timezone.utc)


def test_an_invalid_imported_date_is_rejected(db_session):
    product = _product(db_session)

    with pytest.raises(ValueError, match="Invalid ontosSunsetDate 'soon'"):
        imported_lifecycle_columns(db_session, 'data_product', product.id, {
            'ontosSunsetDate': 'soon', 'ontosDeprecationReason': 'Replaced',
        })


def test_an_imported_replacement_is_checked(db_session):
    product, back = _product(db_session), _product(db_session)
    _deprecated_toward(back, product)
    db_session.flush()

    for replacement_id, message in (
        (product.id, 'own replacement'), ('missing', 'not found'), (back.id, 'leads back'),
    ):
        with pytest.raises(ValueError, match=f'Invalid ontosReplacedBy: .*{message}'):
            imported_lifecycle_columns(db_session, 'data_product', product.id,
                                       {'ontosReplacedBy': replacement_id})


def test_an_import_keeps_what_an_export_can_hold(db_session):
    # A deprecated toward B, then B deprecated toward C; the sunset date passed
    product, b, c = _product(db_session), _product(db_session), _product(db_session)
    _deprecated_toward(b, c)
    db_session.flush()

    columns = imported_lifecycle_columns(db_session, 'data_product', product.id, {
        'ontosReplacedBy': b.id, 'ontosSunsetDate': '2020-01-31',
    })

    assert columns == {'replacement_product_id': b.id, 'sunset_date': date(2020, 1, 31)}


def _odps(product_id, **custom):
    return {
        'id': product_id, 'name': 'Imported', 'version': '1.0.0', 'status': 'deprecated',
        'apiVersion': 'v1.0.0', 'kind': 'DataProduct',
        'customProperties': [{'property': k, 'value': v} for k, v in custom.items()],
    }


def test_an_odps_import_with_an_invalid_replacement_creates_nothing(db_session):
    product_id = str(uuid.uuid4())

    with pytest.raises(ValueError, match='Invalid ontosReplacedBy: Replacement missing not found'):
        DataProductsManager(db=db_session).create_product(
            _odps(product_id, ontosDeprecationReason='Old', ontosReplacedBy='missing'),
            db=db_session,
        )

    assert db_session.get(DataProductDb, product_id) is None


def test_an_odps_import_records_its_lifecycle_fields_in_the_change_log(db_session):
    replacement, product_id = _product(db_session), str(uuid.uuid4())

    DataProductsManager(db=db_session).create_product(
        _odps(product_id, ontosDeprecationReason='Old', ontosReplacedBy=replacement.id,
              ontosSunsetDate='2027-01-31'),
        db=db_session,
    )

    created = db_session.get(DataProductDb, product_id)
    assert created.replacement_product_id == replacement.id
    entry = next(c for c in change_log_manager.list_changes_for_entity(
        db_session, entity_type='data_product', entity_id=product_id) if c.action == 'CREATE')
    import json
    details = json.loads(entry.details_json)
    assert details['replacement_product_id'] == replacement.id
    assert details['sunset_date'] == '2027-01-31'
    assert details['deprecation_reason'] == 'Old'


def test_an_odcs_upload_with_an_invalid_replacement_creates_nothing(db_session):
    from src.db_models.data_contracts import DataContractDb as Contract

    manager = DataContractsManager(data_dir=Path('/tmp'))
    with pytest.raises(ValueError, match='Invalid ontosReplacedBy'):
        manager.create_from_upload(db_session, {
            'id': 'imported-contract', 'name': 'Imported', 'version': '1.0.0',
            'status': 'deprecated', 'apiVersion': 'v3.1.0', 'kind': 'DataContract',
            'customProperties': [{'property': 'ontosReplacedBy', 'value': 'missing'}],
        }, current_user='alice@example.com')

    assert db_session.query(Contract).filter(Contract.name == 'Imported').count() == 0


def test_an_active_entity_exports_no_lifecycle_fields(db_session):
    # Reactivation keeps the reason and replacement for the record.
    product = _product(db_session)
    product.deprecation_reason = 'Replaced by v2'
    product.replacement_product_id = 'p2'

    assert lifecycle_custom_properties(product, 'data_product') == {}


def test_the_reason_comes_from_the_latest_request_to_that_status(db_session):
    product = _product(db_session)
    for days_ago, target, justification in (
        (2, 'deprecated', 'Superseded by v2'), (1, 'draft', 'Back to editing'),
    ):
        entry = change_log_manager.log_change_with_details(
            db_session, entity_type='data_product', entity_id=product.id,
            action='status_change_requested', username='alice',
            details={'target_status': target, 'justification': justification},
        )
        entry.timestamp = datetime.now(timezone.utc) - timedelta(days=days_ago)
    db_session.flush()

    assert requested_status_change_justification(
        db_session, 'data_product', product.id, 'deprecated'
    ) == 'Superseded by v2'


def test_a_contract_update_does_not_write_lifecycle_columns(db_session):
    contract = _contract(db_session)
    props = [{'property': 'owner', 'value': 'x'},
             {'property': 'ontosSunsetDate', 'value': '2001-01-01'},
             {'property': 'ontosReplacedBy', 'value': contract.id}]

    DataContractsManager(data_dir=Path('/tmp'))._create_custom_properties(
        db_session, contract.id, props
    )
    db_session.flush()

    db_session.refresh(contract)
    assert (contract.sunset_date, contract.replacement_contract_id) == (None, None)
    stored = {cp.property for cp in contract.custom_properties}
    assert stored == {'owner'}


def test_contract_read_accepts_orm_dates():
    from src.models.data_contracts_api import DataContractRead

    row = DataContractDb(
        id='c1', name='c', version='1.0.0', status='deprecated', kind='DataContract',
        publication_scope='organization', sunset_date=date(2027, 1, 31),
        deprecated_at=datetime(2026, 10, 14, tzinfo=timezone.utc),
        published_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )

    read = DataContractRead.model_validate(row, from_attributes=True)

    assert read.sunset_date == '2027-01-31'
    assert read.deprecated_at.startswith('2026-10-14')
    assert read.published_at.startswith('2026-10-01')
