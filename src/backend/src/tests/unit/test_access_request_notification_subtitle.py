"""Notification steps of an access request name the requested entity (#1615).

An access request runs its workflow on the proxy entity ``access_grant`` whose id is the
request's: the requester's "Request Submitted" notice showed ``access_grant: <uuid>``.
"""
from src.common.workflow_executor import StepContext, _notification_subtitle


def _context(entity_type, entity_id, entity_name=None, entity=None):
    return StepContext(
        entity=entity or {}, entity_type=entity_type, entity_id=entity_id,
        entity_name=entity_name, user_email='rita@example.com', trigger_context=None,
        execution_id='e-1', workflow_id='w-1', workflow_name='Access', step_results={},
    )


def test_access_request_names_the_requested_entity():
    context = _context('access_grant', 'req-1', 'Orders', {
        'entity_type': 'data_product', 'entity_id': 'p-1', 'entity_name': 'Orders',
    })
    assert _notification_subtitle(context) == 'Data Product: Orders'


def test_access_request_without_a_name_shows_the_entity_id_not_the_request_id():
    context = _context('access_grant', 'req-1', None, {
        'entity_type': 'data_contract', 'entity_id': 'c-1',
        # Looked up for the approvers: not shown in the requester's notices
        'data_product_name': 'Looked up',
    })
    assert _notification_subtitle(context) == 'Data Contract: c-1'


def test_other_entities_keep_type_and_name():
    assert _notification_subtitle(_context('data_product', 'p-1', 'Orders')) == (
        'data_product: Orders'
    )
    assert _notification_subtitle(_context('data_product', 'p-1')) == 'data_product: p-1'
    assert _notification_subtitle(_context('data_product', '')) is None
