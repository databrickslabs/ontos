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


DENIED_NOTICE = 'Your access request was denied (workflow on_fail).'


def _workflow(client, as_user, approvers, require_all=False, active=True):
    as_user(ADMIN)
    response = client.post('/api/workflows', json={
        'name': f'Access {uuid.uuid4().hex[:8]}',
        'trigger': {'type': 'on_request_access', 'entity_types': ['access_grant']},
        'is_active': active,
        'steps': [
            {
                'step_id': 'approve', 'name': 'Approve', 'step_type': 'approval',
                'config': {'approvers': approvers, 'require_all': require_all},
                'on_pass': 'ok', 'on_fail': 'tell',
            },
            {'step_id': 'ok', 'name': 'Granted', 'step_type': 'pass'},
            {
                'step_id': 'tell', 'name': 'Tell', 'step_type': 'notification',
                'config': {'recipients': 'requester', 'template': 'request_rejected',
                           'custom_message': DENIED_NOTICE},
                'on_pass': 'no',
            },
            {'step_id': 'no', 'name': 'Denied', 'step_type': 'fail'},
        ],
    })
    assert response.status_code == 200, response.text
    return response.json()['id']


@pytest.fixture
def access_workflow(client, as_user):
    """An access workflow approved by Ana, so the test decides as her."""
    return _workflow(client, as_user, ANA[0])


def _request_access(client, as_user, permission='READ', days=30, entity_type='data_product',
                    identity=RITA):
    as_user(identity)
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


def _my_request(db_session, request_id, requester=RITA):
    """The request as My Requests lists it (``get_my_requests``)."""
    from src.controller.access_grants_manager import AccessGrantsManager

    db_session.expire_all()
    rows = AccessGrantsManager().get_my_requests(db_session, requester[0]).requests
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
        from src.db_models.access_grants import AccessGrantRequestDb

        request_id = _request_access(client, as_user)
        execution_id = _execution_of(db_session, access_workflow, request_id)
        # Decided by a concurrent decision that committed just before this one (the
        # Access Grants page also closes the workflow, see TestDecidedOutsideItsWorkflow)
        db_session.get(AccessGrantRequestDb, uuid.UUID(request_id)).status = 'denied'
        db_session.flush()

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


BEN = ('ben@example.com', ['data-consumers'])  # a second approver


def _open_approvals(db_session, execution_id):
    from src.db_models.notifications import NotificationDb

    db_session.expire_all()
    return [
        n for n in db_session.query(NotificationDb).filter_by(action_type='workflow_approval')
        if json.loads(n.action_payload)['execution_id'] == execution_id
        and not json.loads(n.action_payload).get('handled')
    ]


def _denied_notices(db_session):
    from src.db_models.notifications import NotificationDb

    db_session.expire_all()
    return db_session.query(NotificationDb).filter_by(
        recipient=RITA[0], description=DENIED_NOTICE).all()


class TestRequireAllTerms:
    """Every approver's checked terms count: the narrowest of them is granted."""

    @pytest.mark.parametrize('first, second', [
        ((ANA, {'granted_duration_days': 7, 'permission_level': 'READ'}), (BEN, {})),
        ((BEN, {}), (ANA, {'granted_duration_days': 7, 'permission_level': 'READ'})),
    ])
    def test_the_narrowest_terms_are_granted(
        self, client, as_user, db_session, first, second,
    ):
        workflow_id = _workflow(client, as_user, f'{ANA[0]},{BEN[0]}', require_all=True)
        request_id = _request_access(client, as_user, permission='WRITE', days=30)
        execution_id = _execution_of(db_session, workflow_id, request_id)

        (who, terms), (then, more) = first, second
        pending = _decide(client, as_user, execution_id, True, identity=who, **terms)
        assert pending.status_code == 200, pending.text
        assert pending.json()['status'] == 'paused'
        assert _grants(db_session, request_id) == []
        response = _decide(client, as_user, execution_id, True, identity=then, **more)

        assert response.status_code == 200, response.text
        [grant] = _grants(db_session, request_id)
        assert grant.permission_level == 'READ'
        assert _days(grant) in (6, 7)


class TestDecidedOutsideItsWorkflow:
    """A decided request closes its other access workflows: cancelled, no on_fail."""

    def test_an_access_grants_decision_closes_the_workflow(
        self, client, as_user, db_session, access_workflow,
    ):
        from datetime import timedelta

        from src.controller.access_grants_manager import AccessGrantsManager
        from src.controller.approval_timeouts_manager import remind_overdue_approvals
        from src.models.access_grants import AccessGrantHandlePayload

        request_id = _request_access(client, as_user)
        execution_id = _execution_of(db_session, access_workflow, request_id)
        assert len(_open_approvals(db_session, execution_id)) == 1

        AccessGrantsManager().handle_request(db_session, 'admin@example.com',
                                             AccessGrantHandlePayload(
                                                 request_id=uuid.UUID(request_id),
                                                 approved=True, granted_duration_days=30))

        assert _status(db_session, execution_id) == 'cancelled'
        assert _open_approvals(db_session, execution_id) == []
        assert _denied_notices(db_session) == []
        from src.common.timestamps import utc_now
        assert remind_overdue_approvals(db_session, utc_now() + timedelta(days=30)) == 0

    def test_one_workflow_deciding_closes_the_other(
        self, client, as_user, db_session, access_workflow,
    ):
        from src.db_models.process_workflows import ProcessWorkflowDb

        # Two active access workflows for one event (the API refuses the overlap; demo
        # data or older databases can have it)
        other = _workflow(client, as_user, BEN[0], active=False)
        db_session.get(ProcessWorkflowDb, other).is_active = True
        db_session.flush()
        request_id = _request_access(client, as_user)
        execution_id = _execution_of(db_session, access_workflow, request_id)
        other_id = _execution_of(db_session, other, request_id)

        response = _decide(client, as_user, execution_id, False, message='No.')

        assert response.status_code == 200, response.text
        assert _my_request(db_session, request_id)['status'] == 'denied'
        assert _status(db_session, other_id) == 'cancelled'
        assert _open_approvals(db_session, other_id) == []
        # Only the deciding workflow's own on_fail told the requester
        assert len(_denied_notices(db_session)) == 1


def test_both_decision_paths_lock_the_request_row(db_session):
    """Two decisions can't both find it pending: ``SELECT ... FOR UPDATE`` on Postgres."""
    from src.controller.access_grants_manager import AccessGrantsManager

    query = AccessGrantsManager.locked_request_query(db_session, uuid.uuid4())
    sql = str(query.statement.compile(dialect=postgresql.dialect()))
    assert sql.rstrip().endswith('FOR UPDATE')


# Holds access-grants Read/Write (Data Producer): may use the Access Grants page, isn't an admin
RITA_PRODUCER = (RITA[0], ['data-producers'])
ANA_PRODUCER = (ANA[0], ['data-producers'])


def _handle(client, as_user, request_id, approved, identity, **terms):
    """A decision on the Access Grants page (``POST /api/access-grants/handle``)."""
    as_user(identity)
    return client.post('/api/access-grants/handle', json={
        'request_id': request_id, 'approved': approved, **terms,
    })


def _handled_audit(log_action_background):
    """The details of the Access Grants page's audit entry for a decision."""
    [details] = [c.kwargs['details'] for c in log_action_background.call_args_list
                 if c.kwargs.get('action') == 'HANDLE_REQUEST']
    return details


def _approval_audit(log_action):
    [details] = [c.kwargs['details'] for c in log_action.call_args_list
                 if c.kwargs.get('action') == 'HANDLE_APPROVAL']
    return details


class TestAccessGrantsPageRule:
    """The Access Grants page decides by the workflow path's rule (#1687 review): someone
    who isn't an admin can't decide their own request nor grant more than was requested;
    an admin can, and the audit entry records the override."""

    def test_a_requester_cant_decide_their_own_request(self, client, as_user, db_session):
        request_id = _request_access(client, as_user)

        response, untouched = _refused_before_any_change(
            lambda: _handle(client, as_user, request_id, True, RITA_PRODUCER))

        assert response.status_code == 403, response.text
        assert response.json()['detail']['code'] == 'own_access_request_approval'
        assert untouched

    @pytest.mark.parametrize('terms, code', [
        ({'permission_level': 'MANAGE'}, 'access_terms_exceed_requested_permission'),
        ({'granted_duration_days': 60}, 'access_terms_exceed_requested_duration'),
    ])
    def test_terms_may_only_narrow_the_request(
        self, client, as_user, db_session, terms, code,
    ):
        request_id = _request_access(client, as_user, permission='READ', days=30)

        response, untouched = _refused_before_any_change(
            lambda: _handle(client, as_user, request_id, True, ANA_PRODUCER, **terms))

        assert response.status_code == 400, response.text
        assert response.json()['detail']['code'] == code
        assert untouched

    def test_an_admin_decides_their_own_request_audited(self, client, as_user, db_session):
        from src.controller.audit_manager import AuditManager

        request_id = _request_access(client, as_user, identity=ADMIN)

        with patch.object(AuditManager, 'log_action_background') as log_action_background:
            response = _handle(client, as_user, request_id, True, ADMIN)

        assert response.status_code == 200, response.text
        assert _my_request(db_session, request_id, ADMIN)['status'] == 'approved'
        details = _handled_audit(log_action_background)
        assert (details['override'], details['overridden']) == (True, ['self_approval'])

    def test_an_admin_grants_more_than_requested_audited(self, client, as_user, db_session):
        from src.controller.audit_manager import AuditManager

        request_id = _request_access(client, as_user, permission='READ', days=30)

        with patch.object(AuditManager, 'log_action_background') as log_action_background:
            response = _handle(client, as_user, request_id, True, ADMIN,
                               permission_level='MANAGE', granted_duration_days=60)

        assert response.status_code == 200, response.text
        [grant] = _grants(db_session, request_id)
        assert grant.permission_level == 'MANAGE'
        assert _days(grant) in (59, 60)
        details = _handled_audit(log_action_background)
        assert (details['override'], details['overridden']) == (True, ['terms'])

    def test_a_decision_within_the_rules_is_no_override(self, client, as_user, db_session):
        from src.controller.audit_manager import AuditManager

        request_id = _request_access(client, as_user, permission='WRITE', days=30)

        with patch.object(AuditManager, 'log_action_background') as log_action_background:
            response = _handle(client, as_user, request_id, True, ANA_PRODUCER,
                               permission_level='READ', granted_duration_days=14)

        assert response.status_code == 200, response.text
        assert 'override' not in _handled_audit(log_action_background)

    def test_an_admin_stays_within_the_allowed_durations(self, client, as_user, db_session):
        from src.db_models.access_grants import AccessGrantDurationConfigDb

        entity_type = f'type_{uuid.uuid4().hex[:6]}'
        db_session.add(AccessGrantDurationConfigDb(
            entity_type=entity_type, allowed_durations=[7, 30, 90],
        ))
        db_session.flush()
        request_id = _request_access(client, as_user, days=30, entity_type=entity_type)

        response, untouched = _refused_before_any_change(
            lambda: _handle(client, as_user, request_id, True, ADMIN, granted_duration_days=60))

        assert response.status_code == 400, response.text
        assert response.json()['detail']['code'] == 'access_terms_duration_not_allowed'
        assert untouched


class TestAdminOverrideOnTheWorkflowPath:
    def test_an_admin_decides_their_own_access_request_audited(
        self, client, as_user, db_session,
    ):
        from src.controller.audit_manager import AuditManager

        workflow_id = _workflow(client, as_user, f'{ADMIN[0]},{ANA[0]}')
        request_id = _request_access(client, as_user, identity=ADMIN)
        execution_id = _execution_of(db_session, workflow_id, request_id)

        with patch.object(AuditManager, 'log_action') as log_action:
            response = _decide(client, as_user, execution_id, True, identity=ADMIN)

        assert response.status_code == 200, response.text
        assert len(_grants(db_session, request_id)) == 1
        details = _approval_audit(log_action)
        assert (details['override'], details['overridden']) == (True, ['self_approval'])

    def test_an_admin_grants_more_than_requested_audited(
        self, client, as_user, db_session, access_workflow,
    ):
        from src.controller.audit_manager import AuditManager

        request_id = _request_access(client, as_user, permission='READ', days=30)
        execution_id = _execution_of(db_session, access_workflow, request_id)

        with patch.object(AuditManager, 'log_action') as log_action:
            response = _decide(client, as_user, execution_id, True, identity=ADMIN,
                               permission_level='MANAGE', granted_duration_days=90)

        assert response.status_code == 200, response.text
        [grant] = _grants(db_session, request_id)
        assert grant.permission_level == 'MANAGE'
        assert _days(grant) in (89, 90)
        details = _approval_audit(log_action)
        assert (details['override'], details['overridden']) == (True, ['terms'])
        assert details['access_grant']['permission_level'] == 'MANAGE'


# An Ontos admin holding the role only by user assignment: no group (role approval, #1713)
BOSS = ('boss@example.com', ['no-admin-group'])


@pytest.fixture
def admin_assigned_by_user(db_session):
    from src.db_models.settings import AppRoleDb

    db_session.add(AppRoleDb(
        id=str(uuid.uuid4()), name=f'Assigned Admin {uuid.uuid4().hex[:8]}',
        description='admin by user', feature_permissions=json.dumps({'access-grants': 'Admin'}),
        assigned_groups='[]', assigned_users=json.dumps(['Boss@Example.com ']),
        home_sections='[]', approval_privileges='{}', is_admin=True,
    ))
    db_session.flush()


class TestAdminAssignedByUser:
    def test_decides_their_own_request_on_the_access_grants_page(
        self, client, as_user, db_session, admin_assigned_by_user,
    ):
        from src.controller.audit_manager import AuditManager

        request_id = _request_access(client, as_user, identity=BOSS)

        with patch.object(AuditManager, 'log_action_background') as log_action_background:
            response = _handle(client, as_user, request_id, True, BOSS)

        assert response.status_code == 200, response.text
        details = _handled_audit(log_action_background)
        assert (details['override'], details['overridden']) == (True, ['self_approval'])

    def test_approves_their_own_request_through_the_workflow(
        self, client, as_user, db_session, admin_assigned_by_user,
    ):
        from src.controller.audit_manager import AuditManager

        workflow_id = _workflow(client, as_user, f'{BOSS[0]},{ANA[0]}')
        request_id = _request_access(client, as_user, identity=BOSS)
        execution_id = _execution_of(db_session, workflow_id, request_id)

        with patch.object(AuditManager, 'log_action') as log_action:
            response = _decide(client, as_user, execution_id, True, identity=BOSS)

        assert response.status_code == 200, response.text
        assert len(_grants(db_session, request_id)) == 1
        details = _approval_audit(log_action)
        assert (details['override'], details['overridden']) == (True, ['self_approval'])


def _failing_record():
    """The decision can't be recorded on the request (after the workflow step committed)."""
    from src.controller.access_grants_manager import AccessGrantsManager

    return patch.object(AccessGrantsManager, 'apply_workflow_decision',
                        side_effect=RuntimeError('database went away'))


def _reconcile(db_session):
    from src.controller.access_grants_manager import AccessGrantsManager

    db_session.expire_all()
    return AccessGrantsManager().reconcile_workflow_decisions(db_session)


class TestFailedDecisionRecord:
    """A decision the route couldn't record on the request (#1687 review): the approver is
    told, and the reconciliation applies the decision the workflow step kept."""

    def test_the_approver_is_told_and_the_grant_follows(
        self, client, as_user, db_session, access_workflow,
    ):
        request_id = _request_access(client, as_user, permission='WRITE', days=30)
        execution_id = _execution_of(db_session, access_workflow, request_id)

        with _failing_record():
            response = _decide(client, as_user, execution_id, True,
                               granted_duration_days=14, permission_level='READ')

        assert response.status_code == 200, response.text
        warning = response.json()['warning']
        assert (warning['code'], warning['params']) == (
            'access_decision_failed', {'access_request': request_id})
        assert _my_request(db_session, request_id)['status'] == 'pending'
        assert _grants(db_session, request_id) == []

        assert _reconcile(db_session) == 1

        row = _my_request(db_session, request_id)
        assert (row['status'], row['handled_by']) == ('approved', ANA[0])
        [grant] = _grants(db_session, request_id)
        assert (grant.permission_level, grant.granted_by) == ('READ', ANA[0])
        assert _days(grant) in (13, 14)
        # Idempotent: nothing left to reconcile
        assert _reconcile(db_session) == 0
        assert len(_grants(db_session, request_id)) == 1

    def test_a_rejection_is_reconciled_to_denied(
        self, client, as_user, db_session, access_workflow,
    ):
        request_id = _request_access(client, as_user)
        execution_id = _execution_of(db_session, access_workflow, request_id)

        with _failing_record():
            response = _decide(client, as_user, execution_id, False, message='Not needed.')

        assert response.status_code == 200, response.text
        assert response.json()['warning']['code'] == 'access_decision_failed'
        assert _my_request(db_session, request_id)['status'] == 'pending'

        assert _reconcile(db_session) == 1

        row = _my_request(db_session, request_id)
        assert (row['status'], row['admin_message']) == ('denied', 'Not needed.')
        assert _grants(db_session, request_id) == []
        assert _reconcile(db_session) == 0

    def test_require_all_reconciles_to_the_narrowest_terms(
        self, client, as_user, db_session,
    ):
        workflow_id = _workflow(client, as_user, f'{ANA[0]},{BEN[0]}', require_all=True)
        request_id = _request_access(client, as_user, permission='WRITE', days=30)
        execution_id = _execution_of(db_session, workflow_id, request_id)
        first = _decide(client, as_user, execution_id, True, identity=ANA,
                        granted_duration_days=7, permission_level='READ')
        assert first.json()['status'] == 'paused', first.text

        with _failing_record():
            response = _decide(client, as_user, execution_id, True, identity=BEN)

        assert response.json()['warning']['code'] == 'access_decision_failed', response.text
        assert _reconcile(db_session) == 1
        [grant] = _grants(db_session, request_id)
        assert grant.permission_level == 'READ'
        assert _days(grant) in (6, 7)

    def test_a_request_decided_meanwhile_is_left_alone(
        self, client, as_user, db_session, access_workflow,
    ):
        from src.db_models.access_grants import AccessGrantRequestDb

        request_id = _request_access(client, as_user)
        execution_id = _execution_of(db_session, access_workflow, request_id)
        with _failing_record():
            _decide(client, as_user, execution_id, True)
        db_session.get(AccessGrantRequestDb, uuid.UUID(request_id)).status = 'cancelled'
        db_session.flush()

        assert _reconcile(db_session) == 0
        assert _grants(db_session, request_id) == []


def _two_step_workflow(client, as_user, second=None):
    """An access workflow of two approval steps in a row: Ana's, then Ben's (or ``second``)."""
    as_user(ADMIN)
    response = client.post('/api/workflows', json={
        'name': f'Two steps {uuid.uuid4().hex[:8]}',
        'trigger': {'type': 'on_request_access', 'entity_types': ['access_grant']},
        'is_active': True,
        'steps': [
            {'step_id': 'first', 'name': 'First', 'step_type': 'approval',
             'config': {'approvers': ANA[0]}, 'on_pass': 'second', 'on_fail': 'no'},
            {'step_id': 'second', 'name': 'Second', 'step_type': 'approval',
             'config': {'approvers': second or BEN[0]}, 'on_pass': 'ok', 'on_fail': 'no'},
            {'step_id': 'ok', 'name': 'Granted', 'step_type': 'pass'},
            {'step_id': 'no', 'name': 'Denied', 'step_type': 'fail'},
        ],
    })
    assert response.status_code == 200, response.text
    return response.json()['id']


class TestSequentialApprovalSteps:
    """Each approval step's narrowing holds in the steps after it (#1687 review)."""

    def test_an_earlier_steps_narrowing_is_granted(self, client, as_user, db_session):
        workflow_id = _two_step_workflow(client, as_user)
        request_id = _request_access(client, as_user, permission='WRITE', days=30)
        execution_id = _execution_of(db_session, workflow_id, request_id)

        first = _decide(client, as_user, execution_id, True, identity=ANA,
                        granted_duration_days=7, permission_level='READ')
        assert first.status_code == 200, first.text
        assert first.json()['status'] == 'paused'
        assert _grants(db_session, request_id) == []

        # The second step approves with the requested terms
        second = _decide(client, as_user, execution_id, True, identity=BEN)

        assert second.status_code == 200, second.text
        [grant] = _grants(db_session, request_id)
        assert grant.permission_level == 'READ'
        assert _days(grant) in (6, 7)

    def test_the_reconciliation_keeps_the_earlier_narrowing(
        self, client, as_user, db_session,
    ):
        workflow_id = _two_step_workflow(client, as_user)
        request_id = _request_access(client, as_user, permission='WRITE', days=30)
        execution_id = _execution_of(db_session, workflow_id, request_id)
        _decide(client, as_user, execution_id, True, identity=ANA,
                granted_duration_days=7, permission_level='READ')

        with _failing_record():
            response = _decide(client, as_user, execution_id, True, identity=BEN)

        assert response.json()['warning']['code'] == 'access_decision_failed', response.text
        assert _reconcile(db_session) == 1
        [grant] = _grants(db_session, request_id)
        assert grant.permission_level == 'READ'
        assert _days(grant) in (6, 7)



class TestEarlierStepNarrowedTheTerms:
    """Terms an earlier step cut: no override is audited for them, and the approver is told."""

    def _narrowed_by_ana(self, client, as_user, db_session, second):
        workflow_id = _two_step_workflow(client, as_user, second=second)
        request_id = _request_access(client, as_user, permission='WRITE', days=30)
        execution_id = _execution_of(db_session, workflow_id, request_id)
        first = _decide(client, as_user, execution_id, True, identity=ANA,
                        granted_duration_days=7, permission_level='READ')
        assert first.status_code == 200, first.text
        return request_id, execution_id

    def test_an_admins_wider_terms_cut_by_an_earlier_step_are_no_override(
        self, client, as_user, db_session,
    ):
        from src.controller.audit_manager import AuditManager

        request_id, execution_id = self._narrowed_by_ana(
            client, as_user, db_session, second=ADMIN[0])

        with patch.object(AuditManager, 'log_action') as log_action:
            response = _decide(client, as_user, execution_id, True, identity=ADMIN,
                               permission_level='MANAGE', granted_duration_days=60)

        assert response.status_code == 200, response.text
        [grant] = _grants(db_session, request_id)
        assert grant.permission_level == 'READ'
        assert _days(grant) in (6, 7)
        details = _approval_audit(log_action)
        assert 'override' not in details and 'overridden' not in details
        assert details['narrowed_by_earlier_step'] is True
        assert response.json()['warning'] == {
            'code': 'access_terms_narrowed_by_earlier_step',
            'message': 'An earlier approval step granted less than you chose.',
            'params': {'sent_days': 60, 'sent_level': 'MANAGE',
                       'granted_days': 7, 'granted_level': 'READ'},
        }

    def test_an_approver_is_told_when_an_earlier_step_cut_their_terms(
        self, client, as_user, db_session,
    ):
        from src.controller.audit_manager import AuditManager

        request_id, execution_id = self._narrowed_by_ana(
            client, as_user, db_session, second=BEN[0])

        with patch.object(AuditManager, 'log_action') as log_action:
            response = _decide(client, as_user, execution_id, True, identity=BEN,
                               permission_level='WRITE', granted_duration_days=30)

        assert response.status_code == 200, response.text
        warning = response.json()['warning']
        assert warning['code'] == 'access_terms_narrowed_by_earlier_step'
        assert warning['params'] == {'sent_days': 30, 'sent_level': 'WRITE',
                                     'granted_days': 7, 'granted_level': 'READ'}
        assert _approval_audit(log_action)['narrowed_by_earlier_step'] is True
        [grant] = _grants(db_session, request_id)
        assert grant.permission_level == 'READ'

    def test_no_warning_when_the_earlier_step_cut_nothing(self, client, as_user, db_session):
        request_id, execution_id = self._narrowed_by_ana(
            client, as_user, db_session, second=BEN[0])

        response = _decide(client, as_user, execution_id, True, identity=BEN,
                           permission_level='READ', granted_duration_days=7)

        assert response.status_code == 200, response.text
        assert 'warning' not in response.json()
