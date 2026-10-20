"""Deprecation lifecycle fields on data products and data contracts.

Moving to ``deprecated`` needs a reason, a sunset date that isn't in the past
(UTC) and, if given, a replacement that exists, isn't deprecated or retired,
isn't the entity itself and doesn't lead back to it. Reactivation clears the
sunset date and deprecation time. Imports keep what an export can hold, refuse
a replacement that is the entity itself or leads back to it, and link a
replacement imported in the same batch; one that isn't in the target is left
unlinked with a note.
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
    ImportLinks,
    LifecycleFieldError,
    apply_lifecycle_fields,
    check_lifecycle_fields,
    imported_lifecycle_columns,
    lifecycle_custom_properties,
    pop_lifecycle_custom_properties,
    requested_deprecation,
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


def test_the_checks_send_a_code_and_parameters_for_the_ui(db_session):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from starlette.exceptions import HTTPException as StarletteHTTPException

    from src.common.api_errors import coded_http_exception_handler

    product, old, newest = _product(db_session), _product(db_session), _product(db_session)
    _deprecated_toward(old, newest)
    db_session.flush()
    app = FastAPI()
    app.add_exception_handler(StarletteHTTPException, coded_http_exception_handler)

    @app.post('/change-status')
    def change_status():
        # As the change-status routes answer a ValueError
        try:
            DataProductsManager(db=db_session).transition_status(
                product.id, 'deprecated', 'alice@example.com',
                deprecation=DeprecationDetails(reason='old', replacement_id=old.id),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    response = TestClient(app).post('/change-status')

    assert response.status_code == 400
    assert response.json() == {'detail': {
        'code': 'replacement_deprecated_replaced',
        'message': f'Replacement {old.id} is deprecated; it is replaced by {newest.id}',
        'params': {'replacementId': old.id, 'replacedBy': newest.id},
    }}


@pytest.mark.parametrize('details, code, params', [
    (None, 'deprecation_reason_required', {}),
    (DeprecationDetails(reason='old', sunset_date=date(2020, 1, 1)),
     'sunset_date_in_past', {'sunsetDate': '2020-01-01'}),
    (DeprecationDetails(reason='old', replacement_id='missing'),
     'replacement_not_found', {'replacementId': 'missing'}),
])
def test_each_check_has_its_code(db_session, details, code, params):
    product = _product(db_session)

    with pytest.raises(ValueError) as e:
        check_lifecycle_fields(db_session, 'data_product', product.id, 'deprecated', details)

    assert (e.value.code, e.value.params) == (code, params)


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

    for replacement_id, message, code in (
        (product.id, 'own replacement', 'replacement_is_self'),
        ('missing', 'not found', 'replacement_not_found'),
        (back.id, 'leads back', 'replacement_leads_back'),
    ):
        with pytest.raises(ValueError, match=f'Invalid ontosReplacedBy: .*{message}') as raised:
            imported_lifecycle_columns(db_session, 'data_product', product.id,
                                       {'ontosReplacedBy': replacement_id})
        assert raised.value.code == code


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

    with pytest.raises(ValueError, match="Invalid ontosReplacedBy: An entity can't be its own"):
        DataProductsManager(db=db_session).create_product(
            _odps(product_id, ontosDeprecationReason='Old', ontosReplacedBy=product_id),
            db=db_session, import_links=ImportLinks('data_product'),
        )

    assert db_session.get(DataProductDb, product_id) is None


def test_a_product_created_outside_an_import_ignores_the_lifecycle_properties(db_session):
    replacement, product_id = _product(db_session), str(uuid.uuid4())

    DataProductsManager(db=db_session).create_product(
        _odps(product_id, ontosDeprecationReason='Old', ontosReplacedBy=replacement.id,
              ontosSunsetDate='2020-01-31'),
        db=db_session,
    )

    created = db_session.get(DataProductDb, product_id)
    assert (created.deprecation_reason, created.sunset_date, created.replacement_product_id) == (
        None, None, None)


def test_an_odps_import_records_its_lifecycle_fields_in_the_change_log(db_session):
    replacement, product_id = _product(db_session), str(uuid.uuid4())

    DataProductsManager(db=db_session).create_product(
        _odps(product_id, ontosDeprecationReason='Old', ontosReplacedBy=replacement.id,
              ontosSunsetDate='2027-01-31'),
        db=db_session, import_links=ImportLinks('data_product'),
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


def _product_files(*docs):
    import json as _json
    return [(f'{i}.json', _json.dumps(doc).encode()) for i, doc in enumerate(docs)]


def test_a_batch_import_names_the_invalid_lifecycle_property(db_session):
    files = _product_files(_odps(str(uuid.uuid4()), ontosSunsetDate='soon'))

    result = DataProductsManager(db=db_session).create_products_from_files(files)

    assert result.failed == 1
    failed = result.items[0]
    assert failed.message == "Invalid ontosSunsetDate 'soon': expected an ISO date"
    assert (failed.code, failed.params) == (
        'imported_date_invalid', {'property': 'ontosSunsetDate', 'value': 'soon'})


def test_a_batch_import_refuses_a_product_replacing_itself(db_session):
    # The file names the product by its exported id; without adoption it gets a new one
    source_id = str(uuid.uuid4())
    files = _product_files(_odps(source_id, ontosReplacedBy=source_id))

    result = DataProductsManager(db=db_session).create_products_from_files(
        files, adopt_ids=False)

    assert (result.created, result.failed) == (0, 1)
    assert result.items[0].code == 'replacement_is_self'


def test_an_item_keeps_both_its_status_note_and_its_replacement_note(db_session):
    """The status PR's note (status mapped to draft) and a dropped replacement both stay."""
    doc = _odps(str(uuid.uuid4()), ontosReplacedBy='no-such-product')
    doc['status'] = 'production'

    result = DataProductsManager(db=db_session).create_products_from_files(_product_files(doc))

    assert (result.created, result.failed) == (1, 0)
    item = result.items[0]
    assert (item.code, item.params) == (
        'imported_status_mapped', {'status': 'production', 'mappedTo': 'draft'})
    assert [n['code'] for n in item.notes] == ['imported_replacement_dropped']
    assert item.notes[0]['params'] == {'replacementId': 'no-such-product'}
    assert 'production' in item.message and 'no-such-product' in item.message


def test_a_replacement_missing_from_the_target_is_not_linked(db_session):
    files = _product_files(_odps(str(uuid.uuid4()), ontosDeprecationReason='Old',
                                 ontosReplacedBy='no-such-product'))

    result = DataProductsManager(db=db_session).create_products_from_files(files)

    assert (result.created, result.failed) == (1, 0)
    item = result.items[0]
    assert item.code == 'imported_replacement_dropped'
    assert item.params == {'replacementId': 'no-such-product'}
    assert 'no-such-product' in item.message
    created = db_session.get(DataProductDb, item.entity_id)
    assert (created.status, created.deprecation_reason, created.replacement_product_id) == (
        'deprecated', 'Old', None)


@pytest.mark.parametrize('replacement_first', [True, False])
@pytest.mark.parametrize('adopt_ids', [True, False])
def test_a_replacement_in_the_same_import_is_linked(db_session, replacement_first, adopt_ids):
    a_id, b_id = str(uuid.uuid4()), str(uuid.uuid4())
    a = _odps(a_id, ontosDeprecationReason='Replaced by B', ontosReplacedBy=b_id)
    b = {**_odps(b_id), 'name': 'B', 'status': 'active'}
    files = _product_files(*((b, a) if replacement_first else (a, b)))

    result = DataProductsManager(db=db_session).create_products_from_files(
        files, adopt_ids=adopt_ids)

    assert (result.created, result.failed) == (2, 0)
    assert all(i.message is None for i in result.items)
    by_source = {i.source_id: i.entity_id for i in result.items}
    created_a = db_session.get(DataProductDb, by_source[a_id])
    assert created_a.replacement_product_id == by_source[b_id]
    assert (by_source[b_id] == b_id) is adopt_ids


def test_a_link_made_after_the_batch_is_in_the_change_log(db_session):
    a_id, b_id = str(uuid.uuid4()), str(uuid.uuid4())
    files = _product_files(_odps(a_id, ontosReplacedBy=b_id), {**_odps(b_id), 'status': 'active'})

    result = DataProductsManager(db=db_session).create_products_from_files(
        files, user='alice@example.com', adopt_ids=False)

    by_source = {i.source_id: i.entity_id for i in result.items}
    entries = change_log_manager.list_changes_for_entity(
        db_session, entity_type='data_product', entity_id=by_source[a_id])
    linked = next(e for e in entries if e.action == 'UPDATE')
    import json
    assert json.loads(linked.details_json)['replacement_product_id'] == by_source[b_id]
    assert linked.username == 'alice@example.com'


@pytest.mark.parametrize('a_first', [True, False])
def test_two_products_replacing_each_other_in_one_import_are_both_refused(db_session, a_first):
    a_id, b_id = str(uuid.uuid4()), str(uuid.uuid4())
    docs = [_odps(a_id, ontosReplacedBy=b_id), _odps(b_id, ontosReplacedBy=a_id)]
    files = _product_files(*(docs if a_first else docs[::-1]))

    result = DataProductsManager(db=db_session).create_products_from_files(
        files, adopt_ids=False)

    assert (result.created, result.failed) == (0, 2)
    by_source = {i.source_id: i for i in result.items}
    for source, other in ((a_id, b_id), (b_id, a_id)):
        assert by_source[source].code == 'replacement_leads_back'
        assert by_source[source].params['replacementId'] == other
        assert by_source[source].params['chain'] == f'{source} -> {other} -> {source}'
    assert db_session.query(DataProductDb).filter(DataProductDb.name == 'Imported').count() == 0


def test_a_longer_cycle_in_one_import_refuses_its_members_only(db_session):
    a_id, b_id, c_id, d_id = (str(uuid.uuid4()) for _ in range(4))
    files = _product_files(
        _odps(a_id, ontosReplacedBy=b_id), _odps(b_id, ontosReplacedBy=c_id),
        _odps(c_id, ontosReplacedBy=a_id), _odps(d_id, ontosReplacedBy=a_id),
    )

    result = DataProductsManager(db=db_session).create_products_from_files(
        files, adopt_ids=False)

    by_source = {i.source_id: i for i in result.items}
    assert {s for s in (a_id, b_id, c_id) if by_source[s].status == 'failed'} == {a_id, b_id, c_id}
    # D points into the cycle without being part of it: created, its link dropped
    assert by_source[d_id].status == 'created'
    assert by_source[d_id].code == 'imported_replacement_dropped'


def _odcs(contract_id, **custom):
    return {
        'id': contract_id, 'name': f'Imported {contract_id[:4]}', 'version': '1.0.0',
        'status': 'deprecated', 'apiVersion': 'v3.1.0', 'kind': 'DataContract',
        'customProperties': [{'property': k, 'value': v} for k, v in custom.items()],
    }


def _contract_files(*docs):
    import json as _json
    return [(f'{i}.json', _json.dumps(doc), 'application/json') for i, doc in enumerate(docs)]


def test_a_contract_batch_import_names_the_invalid_lifecycle_property(db_session):
    files = _contract_files(_odcs(str(uuid.uuid4()), ontosSunsetDate='soon'))

    result = DataContractsManager(data_dir=Path('/tmp')).create_contracts_from_files(
        db_session, files,
    )

    assert result.failed == 1
    assert result.items[0].message == "Invalid ontosSunsetDate 'soon': expected an ISO date"
    assert result.items[0].code == 'imported_date_invalid'


def test_an_odcs_upload_with_an_invalid_replacement_creates_nothing(db_session):
    from src.db_models.data_contracts import DataContractDb as Contract

    manager = DataContractsManager(data_dir=Path('/tmp'))
    with pytest.raises(ValueError, match='Invalid ontosReplacedBy'):
        manager.create_from_upload(db_session, {
            'id': 'imported-contract', 'name': 'Imported', 'version': '1.0.0',
            'status': 'deprecated', 'apiVersion': 'v3.1.0', 'kind': 'DataContract',
            'customProperties': [{'property': 'ontosReplacedBy', 'value': 'imported-contract'}],
        }, current_user='alice@example.com')

    assert db_session.query(Contract).filter(Contract.name == 'Imported').count() == 0


def test_a_contract_replacement_in_the_same_import_is_linked(db_session):
    a_id, b_id = str(uuid.uuid4()), str(uuid.uuid4())
    files = _contract_files(
        _odcs(a_id, ontosDeprecationReason='Replaced by B', ontosReplacedBy=b_id),
        {**_odcs(b_id), 'status': 'active'},
    )

    result = DataContractsManager(data_dir=Path('/tmp')).create_contracts_from_files(
        db_session, files, adopt_ids=False,
    )

    assert (result.created, result.failed) == (2, 0)
    by_source = {i.source_id: i.entity_id for i in result.items}
    created_a = db_session.get(DataContractDb, by_source[a_id])
    assert created_a.replacement_contract_id == by_source[b_id]


@pytest.mark.parametrize('a_first', [True, False])
def test_two_contracts_replacing_each_other_in_one_import_are_both_refused(db_session, a_first):
    a_id, b_id = str(uuid.uuid4()), str(uuid.uuid4())
    docs = [_odcs(a_id, ontosReplacedBy=b_id), _odcs(b_id, ontosReplacedBy=a_id)]
    files = _contract_files(*(docs if a_first else docs[::-1]))

    result = DataContractsManager(data_dir=Path('/tmp')).create_contracts_from_files(
        db_session, files, adopt_ids=False,
    )

    assert (result.created, result.failed) == (0, 2)
    by_source = {i.source_id: i for i in result.items}
    for source, other in ((a_id, b_id), (b_id, a_id)):
        assert by_source[source].code == 'replacement_leads_back'
        assert by_source[source].params['chain'] == f'{source} -> {other} -> {source}'


def test_a_contract_replacement_missing_from_the_target_is_not_linked(db_session):
    files = _contract_files(_odcs(str(uuid.uuid4()), ontosReplacedBy='no-such-contract'))

    result = DataContractsManager(data_dir=Path('/tmp')).create_contracts_from_files(
        db_session, files,
    )

    assert (result.created, result.failed) == (1, 0)
    assert result.items[0].code == 'imported_replacement_dropped'
    created = db_session.get(DataContractDb, result.items[0].entity_id)
    assert created.replacement_contract_id is None


def test_an_imported_contract_is_in_the_change_log_with_its_lifecycle_fields(db_session):
    import json

    files = _contract_files(_odcs(str(uuid.uuid4()), ontosDeprecationReason='Old',
                                  ontosSunsetDate='2020-01-31'))

    result = DataContractsManager(data_dir=Path('/tmp')).create_contracts_from_files(
        db_session, files, current_user='alice@example.com',
    )

    entry = next(c for c in change_log_manager.list_changes_for_entity(
        db_session, entity_type='data_contract', entity_id=result.items[0].entity_id)
        if c.action == 'CREATE')
    details = json.loads(entry.details_json)
    assert (details['deprecation_reason'], details['sunset_date']) == ('Old', '2020-01-31')
    assert entry.username == 'alice@example.com'


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


# --- Approved status change requests are audited as the direct routes are ---

def _request(db, entity_type, entity_id, target, justification, **extra):
    return change_log_manager.log_change_with_details(
        db, entity_type=entity_type, entity_id=entity_id,
        action='status_change_requested', username='alice',
        details={'target_status': target, 'justification': justification,
                 'requester_email': 'alice@example.com', **extra},
    )


@pytest.fixture
def audited(monkeypatch):
    entries = []
    from src.controller import audit_manager
    monkeypatch.setattr(audit_manager, 'log_system_action', lambda **kw: entries.append(kw))
    return entries


def test_an_approved_product_deprecation_request_is_audited_as_deprecate(db_session, audited):
    from unittest.mock import MagicMock
    product = _product(db_session)
    _request(db_session, 'data_product', product.id, 'deprecated', 'Superseded by v2',
             request_id='req-1')
    db_session.commit()

    DataProductsManager(db=db_session).handle_status_change_response(
        db=db_session, notifications_manager=MagicMock(), product_id=product.id,
        approver_email='steward@example.com', decision='approve',
        target_status='deprecated', current_user='steward',
    )

    assert [e['action'] for e in audited] == ['DEPRECATE']
    entry = audited[0]
    assert entry['feature'] == 'data-products'
    assert entry['username'] == 'steward'
    assert entry['details'] == {
        'product_id': product.id, 'from': 'active', 'to': 'deprecated',
        'request_id': 'req-1', 'approved_by': 'steward',
        'deprecation_reason': 'Superseded by v2', 'sunset_date': None, 'replacement_id': None,
    }


def test_an_approved_contract_deprecation_request_is_audited_as_deprecate(db_session, audited):
    from unittest.mock import MagicMock
    contract = _contract(db_session)
    request = _request(db_session, 'data_contract', contract.id, 'deprecated', 'Use v2')
    db_session.commit()

    DataContractsManager(data_dir=Path('/tmp')).handle_status_change_response(
        db=db_session, notifications_manager=MagicMock(), contract_id=contract.id,
        approver_email='steward@example.com', decision='approve', target_status='deprecated',
        requester_email='alice@example.com', current_user='steward',
    )

    assert [e['action'] for e in audited] == ['DEPRECATE']
    details = audited[0]['details']
    assert audited[0]['feature'] == 'data-contracts'
    assert details['contract_id'] == contract.id
    assert details['request_id'] == str(request.id)
    assert details['deprecation_reason'] == 'Use v2'
    assert details['replacement_contract_id'] is None


def test_an_approved_request_to_another_status_writes_no_lifecycle_audit(db_session, audited):
    from unittest.mock import MagicMock
    product = _product(db_session, status='draft')
    _request(db_session, 'data_product', product.id, 'proposed', 'Ready')
    db_session.commit()

    DataProductsManager(db=db_session).handle_status_change_response(
        db=db_session, notifications_manager=MagicMock(), product_id=product.id,
        approver_email='steward@example.com', decision='approve',
        target_status='proposed', current_user='steward',
    )

    assert audited == []


# --- MCP update tools can deprecate ---

def _tool_context(db_session, **managers):
    from types import SimpleNamespace
    return SimpleNamespace(db=db_session, **managers)


@pytest.mark.asyncio
async def test_the_mcp_product_tool_deprecates_with_its_details(db_session):
    from src.tools.data_products import UpdateDataProductTool
    product, replacement = _product(db_session), _product(db_session)
    db_session.commit()
    ctx = _tool_context(db_session, data_products_manager=DataProductsManager(db=db_session))

    result = await UpdateDataProductTool().execute(
        ctx, product_id=product.id, status='deprecated', deprecation_reason='Moved to v2',
        sunset_date=_TOMORROW.isoformat(), replacement_id=replacement.id,
    )

    assert result.success, result.error
    db_session.refresh(product)
    assert (product.status, product.deprecation_reason, product.sunset_date,
            product.replacement_product_id) == ('deprecated', 'Moved to v2', _TOMORROW, replacement.id)


@pytest.mark.asyncio
async def test_the_mcp_product_tool_says_a_reason_is_needed(db_session):
    from src.tools.data_products import UpdateDataProductTool
    product = _product(db_session)
    db_session.commit()
    ctx = _tool_context(db_session, data_products_manager=DataProductsManager(db=db_session))

    result = await UpdateDataProductTool().execute(ctx, product_id=product.id, status='deprecated')

    assert not result.success
    assert 'reason' in result.error.lower()
    db_session.refresh(product)
    assert product.status == 'active'


@pytest.mark.asyncio
async def test_the_mcp_contract_tool_deprecates_with_its_details(db_session):
    from src.tools.data_contracts import UpdateDataContractTool
    contract = _contract(db_session)
    db_session.commit()
    ctx = _tool_context(
        db_session, data_contracts_manager=DataContractsManager(data_dir=Path('/tmp')))

    result = await UpdateDataContractTool().execute(
        ctx, contract_id=contract.id, status='deprecated', deprecation_reason='Use v2',
        sunset_date=_TOMORROW.isoformat(),
    )

    assert result.success, result.error
    db_session.refresh(contract)
    assert (contract.status, contract.deprecation_reason, contract.sunset_date) == (
        'deprecated', 'Use v2', _TOMORROW)


@pytest.mark.asyncio
async def test_the_mcp_tools_refuse_a_malformed_sunset_date(db_session):
    from src.tools.data_products import UpdateDataProductTool
    product = _product(db_session)
    db_session.commit()
    ctx = _tool_context(db_session, data_products_manager=DataProductsManager(db=db_session))

    result = await UpdateDataProductTool().execute(
        ctx, product_id=product.id, status='deprecated', deprecation_reason='x',
        sunset_date='next week',
    )

    assert not result.success
    assert 'YYYY-MM-DD' in result.error


# --- A status change request to deprecated can carry a sunset date and a replacement ---

def test_an_approved_request_applies_its_sunset_date_and_replacement(db_session, audited):
    from unittest.mock import MagicMock
    product, replacement = _product(db_session), _product(db_session)
    sunset = (utc_today() + timedelta(days=30)).isoformat()
    _request(db_session, 'data_product', product.id, 'deprecated', 'Superseded by v2',
             request_id='req-2', sunset_date=sunset, replacement_id=replacement.id)
    db_session.commit()

    DataProductsManager(db=db_session).handle_status_change_response(
        db=db_session, notifications_manager=MagicMock(), product_id=product.id,
        approver_email='steward@example.com', decision='approve',
        target_status='deprecated', current_user='steward',
    )

    db_session.refresh(product)
    assert product.status == 'deprecated'
    assert product.deprecation_reason == 'Superseded by v2'
    assert product.sunset_date.isoformat() == sunset
    assert product.replacement_product_id == replacement.id
    assert audited[0]['details']['sunset_date'] == sunset


def test_an_approved_contract_request_applies_its_sunset_date_and_replacement(db_session, audited):
    from unittest.mock import MagicMock
    contract, replacement = _contract(db_session), _contract(db_session)
    sunset = (utc_today() + timedelta(days=10)).isoformat()
    _request(db_session, 'data_contract', contract.id, 'deprecated', 'Use v2',
             sunset_date=sunset, replacement_id=replacement.id)
    db_session.commit()

    DataContractsManager(data_dir=Path('/tmp')).handle_status_change_response(
        db=db_session, notifications_manager=MagicMock(), contract_id=contract.id,
        approver_email='steward@example.com', decision='approve', target_status='deprecated',
        requester_email='alice@example.com', current_user='steward',
    )

    db_session.refresh(contract)
    assert contract.deprecation_reason == 'Use v2'
    assert contract.sunset_date.isoformat() == sunset
    assert contract.replacement_contract_id == replacement.id


def test_a_request_with_a_past_sunset_date_is_refused_when_made(db_session):
    from unittest.mock import MagicMock
    product = _product(db_session)
    yesterday = (utc_today() - timedelta(days=1)).isoformat()

    with pytest.raises(LifecycleFieldError) as err:
        DataProductsManager(db=db_session).request_status_change(
            db=db_session, notifications_manager=MagicMock(), product_id=product.id,
            target_status='deprecated', justification='Superseded by v2',
            requester_email='alice@example.com', current_user='alice',
            sunset_date=yesterday,
        )
    assert err.value.code == 'sunset_date_in_past'


def test_a_request_with_a_retired_replacement_is_refused_when_made(db_session):
    from unittest.mock import MagicMock
    contract, replacement = _contract(db_session), _contract(db_session, status='retired')

    with pytest.raises(LifecycleFieldError) as err:
        DataContractsManager(data_dir=Path('/tmp')).request_status_change(
            db=db_session, notifications_manager=MagicMock(), contract_id=contract.id,
            target_status='deprecated', justification='Use v2',
            requester_email='alice@example.com', current_user='alice',
            replacement_id=replacement.id,
        )
    assert err.value.code == 'replacement_retired'


def test_the_requested_sunset_date_and_replacement_are_stored_with_the_request(db_session):
    from unittest.mock import MagicMock
    product, replacement = _product(db_session), _product(db_session)
    sunset = (utc_today() + timedelta(days=5)).isoformat()

    DataProductsManager(db=db_session).request_status_change(
        db=db_session, notifications_manager=MagicMock(), product_id=product.id,
        target_status='deprecated', justification='Superseded by v2',
        requester_email='alice@example.com', current_user='alice',
        sunset_date=sunset, replacement_id=replacement.id,
    )

    request_id, details = requested_deprecation(db_session, 'data_product', product.id, 'deprecated')
    assert request_id
    assert (details.reason, details.sunset_date.isoformat(), details.replacement_id) == (
        'Superseded by v2', sunset, replacement.id,
    )


def test_the_approver_gets_the_replacement_name_with_the_request(db_session):
    """The approval dialog lists the request's data; the name says which product it is."""
    from unittest.mock import MagicMock, patch
    product, replacement = _product(db_session), _product(db_session)
    replacement.name = 'Orders v2'
    db_session.flush()
    registry = MagicMock()
    registry.on_request_status_change.return_value = []

    with patch('src.common.workflow_triggers.get_trigger_registry', return_value=registry):
        DataProductsManager(db=db_session).request_status_change(
            db=db_session, notifications_manager=MagicMock(), product_id=product.id,
            target_status='deprecated', justification='Superseded by v2',
            requester_email='alice@example.com', current_user='alice',
            replacement_id=replacement.id,
        )

    entity_data = registry.on_request_status_change.call_args.kwargs['entity_data']
    assert (entity_data['replacement_id'], entity_data['replacement_name']) == (
        replacement.id, 'Orders v2',
    )
