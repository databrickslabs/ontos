"""The requester of a status change request hears each decision (#1321), through the workflow.

The shipped "Status Change Request" workflow runs for a product request; the
approver decides through ``/api/workflows/handle-approval`` (approve, deny or
request clarification). The requester gets exactly one decision notification
naming the product, the target status, the decision, the approver and the
approver's message; the product keeps or takes its status accordingly.
"""
import uuid

import pytest

from src.controller.workflows_manager import WorkflowsManager
from src.db_models.data_products import DataProductDb

REQUESTER = ('requester@example.com', ['data-producers'])
ADMIN = ('test@example.com', ['test_admins'])
DECISION_TITLES = {
    'Status Change Approved',
    'Status Change Denied',
    'Status Change - Clarification Needed',
}


@pytest.fixture
def as_user(mock_test_user):
    def _switch(identity):
        email, groups = identity
        mock_test_user.email = email
        mock_test_user.username = email
        mock_test_user.user = email
        mock_test_user.groups = list(groups)
    yield _switch
    _switch(ADMIN)


@pytest.fixture
def default_workflow(db_session):
    WorkflowsManager(db_session).load_from_yaml()


@pytest.fixture
def product(db_session):
    row = DataProductDb(
        id=str(uuid.uuid4()), name='Decision Product', version='1.0.0',
        status='draft', version_family_id=str(uuid.uuid4()),
    )
    db_session.add(row)
    db_session.flush()
    return row


def _request(client, as_user, product_id):
    as_user(REQUESTER)
    response = client.post(
        f'/api/data-products/{product_id}/request-status-change',
        json={'target_status': 'proposed', 'justification': 'Ready for review'},
    )
    assert response.status_code == 200, response.text
    return response.json()['execution_id']


def _decide(client, as_user, execution_id, *, approved=False, message=None, clarify=False):
    as_user(ADMIN)
    body = {'execution_id': execution_id, 'approved': approved}
    if message is not None:
        body['message'] = message
    if clarify:
        body['clarify'] = True
    return client.post('/api/workflows/handle-approval', json=body)


def _decision_notices(client, as_user):
    as_user(REQUESTER)
    rows = client.get('/api/notifications').json()
    return [n for n in rows if n.get('title') in DECISION_TITLES]


def _status(db_session, product):
    db_session.refresh(product)
    return product.status


def test_approve_notifies_the_requester_once_with_the_decision(
    client, as_user, db_session, product, default_workflow,
):
    execution_id = _request(client, as_user, product.id)

    response = _decide(client, as_user, execution_id, approved=True, message='Looks good')

    assert response.status_code == 200, response.text
    notices = _decision_notices(client, as_user)
    assert [n['title'] for n in notices] == ['Status Change Approved']
    assert notices[0]['recipient'] == REQUESTER[0]
    assert notices[0]['description'] == (
        "Your request to change the status of 'Decision Product' to 'proposed' "
        "has been approved by 'test@example.com'.\n\nApprover message: Looks good"
    )
    assert notices[0]['data']['i18n']['params'] == {
        'name': 'Decision Product', 'toStatus': 'proposed',
        'approver': 'test@example.com', 'message': 'Looks good',
    }
    assert _status(db_session, product) == 'proposed'


def test_deny_notifies_the_requester_once_and_keeps_the_status(
    client, as_user, db_session, product, default_workflow,
):
    execution_id = _request(client, as_user, product.id)

    response = _decide(client, as_user, execution_id, message='Not yet')

    assert response.status_code == 200, response.text
    notices = _decision_notices(client, as_user)
    assert [n['title'] for n in notices] == ['Status Change Denied']
    assert notices[0]['recipient'] == REQUESTER[0]
    assert "has been denied by 'test@example.com'." in notices[0]['description']
    assert notices[0]['description'].endswith('Approver message: Not yet')
    assert _status(db_session, product) == 'draft'


def test_clarify_notifies_the_requester_once_and_keeps_the_status(
    client, as_user, db_session, product, default_workflow,
):
    execution_id = _request(client, as_user, product.id)

    response = _decide(
        client, as_user, execution_id, message='Which region is it for?', clarify=True,
    )

    assert response.status_code == 200, response.text
    notices = _decision_notices(client, as_user)
    assert [n['title'] for n in notices] == ['Status Change - Clarification Needed']
    assert notices[0]['recipient'] == REQUESTER[0]
    assert notices[0]['description'].endswith('Approver message: Which region is it for?')
    assert _status(db_session, product) == 'draft'


def test_clarify_needs_the_message_for_the_requester(
    client, as_user, product, default_workflow,
):
    execution_id = _request(client, as_user, product.id)

    response = _decide(client, as_user, execution_id, clarify=True)

    assert response.status_code == 400
    assert response.json()['detail']['code'] == 'clarification_message_required'
    assert _decision_notices(client, as_user) == []
