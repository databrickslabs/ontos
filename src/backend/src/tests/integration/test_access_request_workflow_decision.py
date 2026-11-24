"""An access request decided through its approval workflow (#1615), through the API.

An access request fires ``on_request_access``; its approval step is decided with
``POST /api/workflows/handle-approval``. Before, the decision resumed the workflow and left
the request pending with no grant: My Requests showed it pending forever, and the
approver's duration and permission level were dropped.

A refused request rolls back the test's transaction (``get_db`` rolls back on any
exception), so a test ends with its only refusal.
"""
import json
import uuid

import pytest

ADMIN = ('test@example.com', ['test_admins'])
ANA = ('ana@example.com', ['data-consumers'])  # the workflow's approver
RITA = ('rita@example.com', ['data-consumers'])  # the requester


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
    mock_test_user.username = 'test_user'
    mock_test_user.user = 'test_user'


@pytest.fixture
def access_workflow(client, as_user):
    """An access workflow approved by Ana, so the test decides as her."""
    as_user(ADMIN)
    response = client.post('/api/workflows', json={
        'name': f'Access {uuid.uuid4().hex[:8]}',
        'trigger': {'type': 'on_request_access', 'entity_types': ['access_grant']},
        'is_active': True,
        'steps': [
            {
                'step_id': 'approve', 'name': 'Approve', 'step_type': 'approval',
                'config': {'approvers': ANA[0]}, 'on_pass': 'ok', 'on_fail': 'no',
            },
            {'step_id': 'ok', 'name': 'Granted', 'step_type': 'pass'},
            {'step_id': 'no', 'name': 'Denied', 'step_type': 'fail'},
        ],
    })
    assert response.status_code == 200, response.text
    return response.json()['id']


def _request_access(client, as_user, permission='READ', days=30):
    as_user(RITA)
    response = client.post('/api/access-grants/request', json={
        'entity_type': 'data_product',
        'entity_id': str(uuid.uuid4()),
        'entity_name': 'Orders',
        'permission_level': permission,
        'requested_duration_days': days,
        'reason': 'Quarterly revenue analysis.',
    })
    assert response.status_code == 201, response.text
    return response.json()['id']


def _execution_of(db_session, workflow_id, request_id):
    from src.db_models.process_workflows import WorkflowExecutionDb

    db_session.expire_all()
    for row in db_session.query(WorkflowExecutionDb).filter_by(workflow_id=workflow_id).all():
        if (json.loads(row.trigger_context or '{}') or {}).get('entity_id') == request_id:
            return row.id
    raise AssertionError(f'no execution of {workflow_id} for request {request_id}')


def _decide(client, as_user, execution_id, approved, **terms):
    as_user(ANA)
    return client.post('/api/workflows/handle-approval', json={
        'execution_id': execution_id, 'approved': approved, **terms,
    })


def _my_request(db_session, request_id):
    """The request as My Requests lists it (``get_my_requests``)."""
    from src.controller.access_grants_manager import AccessGrantsManager

    db_session.expire_all()
    rows = AccessGrantsManager().get_my_requests(db_session, RITA[0]).requests
    [row] = [r for r in rows if str(r.id) == request_id]
    return row.model_dump(mode='json')


def _grants(db_session, request_id):
    from src.db_models.access_grants import AccessGrantDb

    db_session.expire_all()
    return db_session.query(AccessGrantDb).filter_by(request_id=uuid.UUID(request_id)).all()


class TestAccessRequestWorkflowDecision:
    def test_approval_grants_with_the_approvers_terms(
        self, client, as_user, db_session, access_workflow,
    ):
        request_id = _request_access(client, as_user)
        execution_id = _execution_of(db_session, access_workflow, request_id)

        response = _decide(
            client, as_user, execution_id, True,
            granted_duration_days=14, permission_level='WRITE', message='For Q3 only.',
        )

        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'succeeded'
        row = _my_request(db_session, request_id)
        assert row['status'] == 'approved'
        assert row['handled_at'] is not None
        assert row['handled_by'] == ANA[0]
        assert row['entity_name'] == 'Orders'
        [grant] = _grants(db_session, request_id)
        assert (grant.grantee_email, grant.permission_level) == (RITA[0], 'WRITE')
        assert grant.granted_by == ANA[0]
        days = (grant.expires_at - grant.granted_at).days
        assert days in (13, 14)

    def test_approval_without_terms_grants_what_was_requested(
        self, client, as_user, db_session, access_workflow,
    ):
        request_id = _request_access(client, as_user, permission='MANAGE', days=7)
        execution_id = _execution_of(db_session, access_workflow, request_id)

        response = _decide(client, as_user, execution_id, True)

        assert response.status_code == 200, response.text
        [grant] = _grants(db_session, request_id)
        assert grant.permission_level == 'MANAGE'
        assert (grant.expires_at - grant.granted_at).days in (6, 7)

    def test_rejection_denies_the_request(
        self, client, as_user, db_session, access_workflow,
    ):
        request_id = _request_access(client, as_user)
        execution_id = _execution_of(db_session, access_workflow, request_id)

        response = _decide(client, as_user, execution_id, False, message='Not needed.')

        assert response.status_code == 200, response.text
        row = _my_request(db_session, request_id)
        assert row['status'] == 'denied'
        assert row['handled_at'] is not None
        assert _grants(db_session, request_id) == []

    def test_terms_that_cant_be_granted_are_refused_before_the_decision(
        self, client, as_user, db_session, access_workflow,
    ):
        request_id = _request_access(client, as_user)
        execution_id = _execution_of(db_session, access_workflow, request_id)

        response = _decide(client, as_user, execution_id, True, granted_duration_days=999)

        assert response.status_code == 400, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'access_terms_invalid_duration'
        assert detail['params'] == {'min': 1, 'max': 365}
