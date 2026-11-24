"""An access request decided through its approval workflow (#1615), through the API.

An access request fires ``on_request_access``; its approval step is decided with
``POST /api/workflows/handle-approval``. Before, the decision resumed the workflow and left
the request pending with no grant: My Requests showed it pending forever, and the
approver's duration and permission level were dropped.

Rules: the requester never decides their own request; an approver's terms may only narrow
it (level, duration, the entity type's allowed durations); a request decided meanwhile
gets 409 before the workflow changes; the admin resume can't decide an access request.

A refused request rolls back the test's transaction (``get_db`` rolls back on any
exception), so a test ends with its only refusal.
"""
import json
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy.dialects import postgresql

ADMIN = ('test@example.com', ['test_admins'])
ANA = ('ana@example.com', ['data-consumers'])  # an approver
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


def _workflow(client, as_user, approvers):
    as_user(ADMIN)
    response = client.post('/api/workflows', json={
        'name': f'Access {uuid.uuid4().hex[:8]}',
        'trigger': {'type': 'on_request_access', 'entity_types': ['access_grant']},
        'is_active': True,
        'steps': [
            {
                'step_id': 'approve', 'name': 'Approve', 'step_type': 'approval',
                'config': {'approvers': approvers}, 'on_pass': 'ok', 'on_fail': 'no',
            },
            {'step_id': 'ok', 'name': 'Granted', 'step_type': 'pass'},
            {'step_id': 'no', 'name': 'Denied', 'step_type': 'fail'},
        ],
    })
    assert response.status_code == 200, response.text
    return response.json()['id']


@pytest.fixture
def access_workflow(client, as_user):
    """An access workflow approved by Ana, so the test decides as her."""
    return _workflow(client, as_user, ANA[0])


def _request_access(client, as_user, permission='READ', days=30, entity_type='data_product'):
    as_user(RITA)
    response = client.post('/api/access-grants/request', json={
        'entity_type': entity_type,
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


def _status(db_session, execution_id):
    from src.db_models.process_workflows import WorkflowExecutionDb

    db_session.expire_all()
    return db_session.get(WorkflowExecutionDb, execution_id).status


def _decide(client, as_user, execution_id, approved, identity=ANA, **terms):
    as_user(identity)
    return client.post('/api/workflows/handle-approval', json={
        'execution_id': execution_id, 'approved': approved, **terms,
    })


def _refused_before_any_change(call):
    """Run ``call``; whether the workflow and the request were left untouched.

    A refusal rolls back the test's rows, so this watches the writes instead: no resume
    of the workflow, no grant created.
    """
    from src.common.workflow_executor import WorkflowExecutor
    from src.repositories.access_grants_repository import AccessGrantRepository

    with patch.object(WorkflowExecutor, 'resume_workflow') as resume, \
            patch.object(AccessGrantRepository, 'create') as create_grant:
        response = call()
    return response, not resume.called and not create_grant.called


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


def _days(grant):
    return (grant.expires_at - grant.granted_at).days


class TestAccessRequestWorkflowDecision:
    def test_approval_grants_with_narrower_terms_and_audits_them(
        self, client, as_user, db_session, access_workflow,
    ):
        from src.controller.audit_manager import AuditManager

        request_id = _request_access(client, as_user, permission='MANAGE', days=30)
        execution_id = _execution_of(db_session, access_workflow, request_id)

        with patch.object(AuditManager, 'log_action') as log_action:
            response = _decide(
                client, as_user, execution_id, True,
                granted_duration_days=14, permission_level='WRITE', message='For Q3 only.',
            )

        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'succeeded'
        row = _my_request(db_session, request_id)
        assert (row['status'], row['handled_by'], row['entity_name']) == (
            'approved', ANA[0], 'Orders')
        assert row['handled_at'] is not None
        [grant] = _grants(db_session, request_id)
        assert (grant.grantee_email, grant.permission_level, grant.granted_by) == (
            RITA[0], 'WRITE', ANA[0])
        assert _days(grant) in (13, 14)
        [details] = [c.kwargs['details'] for c in log_action.call_args_list
                     if c.kwargs.get('action') == 'HANDLE_APPROVAL']
        assert details['access_grant'] == {
            'access_request': request_id, 'decision': 'approved',
            'granted_duration_days': 14, 'permission_level': 'WRITE',
        }

    def test_approval_without_terms_grants_what_was_requested(
        self, client, as_user, db_session, access_workflow,
    ):
        request_id = _request_access(client, as_user, permission='MANAGE', days=7)
        execution_id = _execution_of(db_session, access_workflow, request_id)

        response = _decide(client, as_user, execution_id, True)

        assert response.status_code == 200, response.text
        [grant] = _grants(db_session, request_id)
        assert grant.permission_level == 'MANAGE'
        assert _days(grant) in (6, 7)

    def test_rejection_denies_the_request_whatever_its_terms(
        self, client, as_user, db_session, access_workflow,
    ):
        request_id = _request_access(client, as_user)
        execution_id = _execution_of(db_session, access_workflow, request_id)

        response = _decide(
            client, as_user, execution_id, False, message='Not needed.',
            granted_duration_days=999, permission_level='MANAGE',
        )

        assert response.status_code == 200, response.text
        row = _my_request(db_session, request_id)
        assert row['status'] == 'denied'
        assert row['handled_at'] is not None
        assert _grants(db_session, request_id) == []

    @pytest.mark.parametrize('terms, code, params', [
        ({'permission_level': 'MANAGE'}, 'access_terms_exceed_requested_permission',
         {'requested': 'READ'}),
        ({'granted_duration_days': 31}, 'access_terms_exceed_requested_duration',
         {'requested': 30}),
        ({'granted_duration_days': 0}, 'access_terms_invalid_duration',
         {'min': 1, 'max': 30}),
        ({'permission_level': 'OWN'}, 'access_terms_invalid_permission',
         {'allowed': ['READ', 'WRITE', 'MANAGE']}),
    ])
    def test_terms_may_only_narrow_the_request(
        self, client, as_user, db_session, access_workflow, terms, code, params,
    ):
        request_id = _request_access(client, as_user, permission='READ', days=30)
        execution_id = _execution_of(db_session, access_workflow, request_id)

        response, untouched = _refused_before_any_change(
            lambda: _decide(client, as_user, execution_id, True, **terms))

        assert response.status_code == 400, response.text
        assert response.json()['detail'] == {
            'code': code, 'message': response.json()['detail']['message'], 'params': params,
        }
        assert untouched

    def test_terms_follow_the_allowed_durations(
        self, client, as_user, db_session, access_workflow,
    ):
        from src.db_models.access_grants import AccessGrantDurationConfigDb

        entity_type = f'type_{uuid.uuid4().hex[:6]}'
        db_session.add(AccessGrantDurationConfigDb(
            entity_type=entity_type, allowed_durations=[7, 30],
        ))
        db_session.flush()
        request_id = _request_access(client, as_user, days=30, entity_type=entity_type)
        execution_id = _execution_of(db_session, access_workflow, request_id)

        response, untouched = _refused_before_any_change(
            lambda: _decide(client, as_user, execution_id, True, granted_duration_days=14))

        assert response.status_code == 400, response.text
        assert untouched
        detail = response.json()['detail']
        assert (detail['code'], detail['params']) == (
            'access_terms_duration_not_allowed', {'days': 14, 'allowed': [7, 30]})

    def test_the_requester_cant_decide_their_own_request(
        self, client, as_user, db_session,
    ):
        workflow_id = _workflow(client, as_user, f'{RITA[0]},{ANA[0]}')
        request_id = _request_access(client, as_user)
        execution_id = _execution_of(db_session, workflow_id, request_id)

        response, untouched = _refused_before_any_change(
            lambda: _decide(client, as_user, execution_id, True, identity=RITA))

        assert response.status_code == 403, response.text
        assert response.json()['detail']['code'] == 'own_access_request_approval'
        assert untouched

    def test_another_approver_of_the_same_step_decides_it(
        self, client, as_user, db_session,
    ):
        workflow_id = _workflow(client, as_user, f'{RITA[0]},{ANA[0]}')
        request_id = _request_access(client, as_user)
        execution_id = _execution_of(db_session, workflow_id, request_id)

        response = _decide(client, as_user, execution_id, True, identity=ANA)

        assert response.status_code == 200, response.text
        assert len(_grants(db_session, request_id)) == 1

    def test_a_request_decided_meanwhile_gets_409_and_the_workflow_waits(
        self, client, as_user, db_session, access_workflow,
    ):
        from src.controller.access_grants_manager import AccessGrantsManager
        from src.models.access_grants import AccessGrantHandlePayload

        request_id = _request_access(client, as_user)
        execution_id = _execution_of(db_session, access_workflow, request_id)
        # Decided on the Access Grants page first
        AccessGrantsManager().handle_request(db_session, 'admin@example.com',
                                             AccessGrantHandlePayload(
                                                 request_id=uuid.UUID(request_id),
                                                 approved=False, message='No.'))

        response, untouched = _refused_before_any_change(
            lambda: _decide(client, as_user, execution_id, True))

        assert response.status_code == 409, response.text
        detail = response.json()['detail']
        assert (detail['code'], detail['params']) == (
            'access_request_already_decided', {'status': 'denied'})
        assert untouched

    def test_the_admin_resume_cant_decide_an_access_request(
        self, client, as_user, db_session, access_workflow,
    ):
        request_id = _request_access(client, as_user)
        execution_id = _execution_of(db_session, access_workflow, request_id)

        as_user(ADMIN)
        response, untouched = _refused_before_any_change(lambda: client.post(
            f'/api/workflows/executions/{execution_id}/resume', json={'approved': True},
        ))

        assert response.status_code == 403, response.text
        assert response.json()['detail']['code'] == 'access_request_resume_refused'
        assert untouched


def test_both_decision_paths_lock_the_request_row(db_session):
    """Two decisions can't both find it pending: ``SELECT ... FOR UPDATE`` on Postgres."""
    from src.controller.access_grants_manager import AccessGrantsManager

    query = AccessGrantsManager.locked_request_query(db_session, uuid.uuid4())
    sql = str(query.statement.compile(dialect=postgresql.dialect()))
    assert sql.rstrip().endswith('FOR UPDATE')
