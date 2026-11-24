"""Access request texts name the requested entity, with a name approvers can trust (#1615).

An access request runs its workflow on the proxy entity ``access_grant`` whose id is the
request's: the requester's "Request Submitted" notice showed ``access_grant: <uuid>``.
Approvers see the name Ontos stores for the entity, never the ``entity_name`` (or
``data_product_name``) sent with the request; the requester sees the name they sent.
"""
import uuid

from src.common.workflow_executor import (
    StepContext, _extract_approval_facets, _notification_subtitle, _recipient_entity_name,
    _server_entity_name,
)
from src.db_models.data_products import DataProductDb

SPOOFED = {'entity_name': 'Payroll (looks harmless)', 'data_product_name': 'Payroll too'}


def _context(entity_type, entity_id, entity_name=None, entity=None):
    return StepContext(
        entity=entity or {}, entity_type=entity_type, entity_id=entity_id,
        entity_name=entity_name, user_email='rita@example.com', trigger_context=None,
        execution_id='e-1', workflow_id='w-1', workflow_name='Access', step_results={},
    )


def _product(db, name='Orders'):
    product = DataProductDb(id=str(uuid.uuid4()), name=name, status='active')
    db.add(product)
    db.flush()
    return product.id


def _access(product_id, **sent):
    return _context('access_grant', 'req-1', sent.get('entity_name'), {
        'entity_type': 'data_product', 'entity_id': product_id, 'request_id': 'req-1', **sent,
    })


def test_subtitle_names_the_requested_entity():
    context = _access('p-1', entity_name='Orders')
    assert _notification_subtitle(context, 'Orders') == 'Data Product: Orders'


def test_subtitle_without_a_name_shows_the_entity_id_not_the_request_id():
    assert _notification_subtitle(_access('c-1', entity_name='Sent')) == 'Data Product: c-1'


def test_other_entities_keep_type_and_name():
    assert _notification_subtitle(_context('data_product', 'p-1', 'Orders')) == (
        'data_product: Orders'
    )
    assert _notification_subtitle(_context('data_product', 'p-1')) == 'data_product: p-1'
    assert _notification_subtitle(_context('data_product', '')) is None


def test_approvers_see_the_stored_name_not_the_one_sent(db_session):
    product_id = _product(db_session)
    facets = _extract_approval_facets(_access(product_id, **SPOOFED), db_session)

    assert facets['underlying_entity_name'] == 'Orders'
    assert _server_entity_name(db_session, 'data_product', product_id) == 'Orders'


def test_an_unknown_entity_has_no_name_for_approvers(db_session):
    facets = _extract_approval_facets(_access('no-such-product', **SPOOFED), db_session)

    assert 'underlying_entity_name' not in facets
    assert facets['underlying_entity_id'] == 'no-such-product'
    assert _server_entity_name(db_session, 'data_product', 'no-such-product') is None
    assert _server_entity_name(db_session, 'table', 'x') is None


def test_each_recipient_gets_their_name():
    context = _access('p-1', **SPOOFED)

    assert _recipient_entity_name(context, 'RITA@example.com', 'Orders') == SPOOFED['entity_name']
    assert _recipient_entity_name(context, 'Admin', 'Orders') == 'Orders'
    assert _recipient_entity_name(context, 'ana@example.com', None) is None
