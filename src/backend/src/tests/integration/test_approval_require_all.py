"""``require_all`` on an approval step (#1119), through the API.

Each resolved notification target decides once: a user for themselves, any one
member for a group; one person fills one target. The execution stays paused
until all have approved; any rejection fails the step. Decisions are stored with
the step. A decision on a step that has ended gets 409. ``require_all: false``
keeps "first decision resumes".

A refused request rolls back the test's transaction (``get_db`` rolls back on
any exception), so a test ends with its only refusal.
"""
import json
import uuid

import pytest

ADMIN = ('test@example.com', ['test_admins'])
ANA = ('ana@example.com', ['data-consumers'])
BEN = ('ben@example.com', ['data-consumers'])
CARL = ('carl@example.com', ['team-x'])
DORA = ('dora@example.com', ['team-x'])
EVE = ('eve@example.com', ['data-consumers'])


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


def _paused_execution(client, as_user, approvers, require_all=True, then=None):
    """``then``: approvers of a second approval step after this one."""
    as_user(ADMIN)
    second = [{
        'step_id': 'second', 'name': 'Second', 'step_type': 'approval',
        'config': {'approvers': then}, 'on_pass': 'ok', 'on_fail': 'no',
    }] if then else []
    response = client.post('/api/workflows', json={
        'name': f'Require all {uuid.uuid4().hex[:8]}',
        'trigger': {'type': 'manual', 'entity_types': ['data_product']},
        'is_active': True,
        'steps': [
            {
                'step_id': 'approve', 'name': 'Approve', 'step_type': 'approval',
                'config': {'approvers': approvers, 'require_all': require_all},
                'on_pass': 'second' if then else 'ok', 'on_fail': 'no',
            },
            *second,
            {'step_id': 'ok', 'name': 'Approved', 'step_type': 'pass'},
            {'step_id': 'no', 'name': 'Rejected', 'step_type': 'fail'},
        ],
    })
    assert response.status_code == 200, response.text
    response = client.post(
        f"/api/workflows/{response.json()['id']}/execute",
        params={'entity_type': 'data_product', 'entity_id': str(uuid.uuid4())},
    )
    assert response.status_code == 200, response.text
    execution = response.json()
    assert execution['status'] == 'paused', execution
    return execution['id']


def _decide(
    client, as_user, identity, execution_id, approved=True, reason=None, step_id=None,
):
    as_user(identity)
    body = {'execution_id': execution_id, 'approved': approved}
    if reason:
        body['reason'] = reason
    if step_id:
        body['step_id'] = step_id
    return client.post('/api/workflows/handle-approval', json=body)


def _status(db_session, execution_id):
    from src.db_models.process_workflows import WorkflowExecutionDb

    db_session.expire_all()
    return db_session.get(WorkflowExecutionDb, execution_id).status


def _approval_records(db_session, execution_id):
    from src.db_models.process_workflows import WorkflowStepExecutionDb

    db_session.expire_all()
    rows = db_session.query(WorkflowStepExecutionDb).filter_by(
        execution_id=execution_id, step_key='approve',
    ).order_by(WorkflowStepExecutionDb.started_at).all()
    return [json.loads(r.result_data or '{}') for r in rows]


def _unread_recipients(db_session, execution_id):
    from src.db_models.notifications import NotificationDb

    db_session.expire_all()
    return {
        n.recipient for n in db_session.query(NotificationDb).filter_by(
            action_type='workflow_approval', read=False,
        ).all()
        if json.loads(n.action_payload or '{}').get('execution_id') == execution_id
    }


class TestRequireAll:
    def test_waits_for_every_approver(self, client, as_user, db_session):
        execution_id = _paused_execution(client, as_user, 'ana@example.com,ben@example.com')

        first = _decide(client, as_user, ANA, execution_id)

        assert first.status_code == 200, first.text
        assert first.json()['status'] == 'paused'
        assert first.json()['pending_approvers'] == 1
        assert _status(db_session, execution_id) == 'paused'
        # Ana's notification is handled, Ben's is still open
        assert _unread_recipients(db_session, execution_id) == {'ben@example.com'}

        second = _decide(client, as_user, BEN, execution_id)

        assert second.status_code == 200, second.text
        assert second.json()['status'] == 'succeeded'
        assert _status(db_session, execution_id) == 'succeeded'
        records = _approval_records(db_session, execution_id)
        # The pause record keeps the targets resolved when the step paused
        assert [t['target'] for t in records[0]['resolved_targets']] == [
            'ana@example.com', 'ben@example.com',
        ]
        decision = records[-1]
        assert decision['approval_result'] == 'approved'
        assert decision['responded_by'] == 'ben@example.com'
        assert [(d['target'], d['decision'], d['decided_by']) for d in decision['decisions']] == [
            ('ana@example.com', 'approved', 'ana@example.com'),
            ('ben@example.com', 'approved', 'ben@example.com'),
        ]

    def test_any_rejection_fails_the_step(self, client, as_user, db_session):
        execution_id = _paused_execution(client, as_user, 'ana@example.com,ben@example.com')
        assert _decide(client, as_user, ANA, execution_id).json()['status'] == 'paused'

        response = _decide(client, as_user, BEN, execution_id, approved=False, reason='No')

        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'failed'
        decision = _approval_records(db_session, execution_id)[-1]
        assert decision['approval_result'] == 'rejected'
        assert [d['decision'] for d in decision['decisions']] == ['approved', 'rejected']
        assert decision['decisions'][1]['reason'] == 'No'

    def test_a_first_rejection_fails_it_at_once(self, client, as_user, db_session):
        execution_id = _paused_execution(client, as_user, 'ana@example.com,ben@example.com')

        response = _decide(client, as_user, ANA, execution_id, approved=False, reason='No')

        assert response.json()['status'] == 'failed'
        assert _status(db_session, execution_id) == 'failed'

    def test_a_second_decision_by_the_same_approver_does_not_count(
        self, client, as_user, db_session,
    ):
        execution_id = _paused_execution(client, as_user, 'ana@example.com,ben@example.com')
        assert _decide(client, as_user, ANA, execution_id).json()['status'] == 'paused'

        again = _decide(client, as_user, ANA, execution_id, approved=False, reason='Changed')

        assert again.status_code == 409
        assert again.json()['detail']['code'] == 'approval_already_decided'

    def test_one_member_decides_for_a_group(self, client, as_user, db_session):
        execution_id = _paused_execution(client, as_user, 'ana@example.com,team-x')

        assert _decide(client, as_user, CARL, execution_id).json()['pending_approvers'] == 1
        assert _unread_recipients(db_session, execution_id) == {'ana@example.com'}
        response = _decide(client, as_user, ANA, execution_id)

        assert response.json()['status'] == 'succeeded'
        decisions = _approval_records(db_session, execution_id)[-1]['decisions']
        assert [(d['target'], d['decided_by']) for d in decisions] == [
            ('team-x', 'carl@example.com'), ('ana@example.com', 'ana@example.com'),
        ]

    def test_another_member_of_a_decided_group_does_not_count(
        self, client, as_user, db_session,
    ):
        execution_id = _paused_execution(client, as_user, 'ana@example.com,team-x')
        assert _decide(client, as_user, CARL, execution_id).json()['status'] == 'paused'

        response = _decide(client, as_user, DORA, execution_id)

        assert response.status_code == 409
        assert response.json()['detail']['code'] == 'approval_no_longer_pending'

    def test_one_person_fills_one_target(self, client, as_user, db_session):
        """Carl is a user target and a member of the group target: his
        decision fills his own target, the group still needs another member."""
        execution_id = _paused_execution(client, as_user, 'carl@example.com,team-x')

        first = _decide(client, as_user, CARL, execution_id)

        assert first.json()['status'] == 'paused', first.text
        assert first.json()['pending_approvers'] == 1
        assert _unread_recipients(db_session, execution_id) == {'team-x'}
        response = _decide(client, as_user, DORA, execution_id)

        assert response.json()['status'] == 'succeeded'
        decisions = _approval_records(db_session, execution_id)[-1]['decisions']
        assert [(d['target'], d['decided_by']) for d in decisions] == [
            ('carl@example.com', 'carl@example.com'), ('team-x', 'dora@example.com'),
        ]

    def test_the_same_person_does_not_fill_a_second_target(self, client, as_user, db_session):
        execution_id = _paused_execution(client, as_user, 'carl@example.com,team-x')
        assert _decide(client, as_user, CARL, execution_id).json()['status'] == 'paused'

        again = _decide(client, as_user, CARL, execution_id)

        assert again.status_code == 409
        assert again.json()['detail']['code'] == 'approval_already_decided'

    def test_someone_who_is_not_an_approver_is_refused(self, client, as_user, db_session):
        execution_id = _paused_execution(client, as_user, 'ana@example.com,ben@example.com')

        assert _decide(client, as_user, EVE, execution_id).status_code == 403

    def test_an_admin_who_is_not_an_approver_is_refused(self, client, as_user, db_session):
        """With require_all only the resolved approvers decide; the refusal
        records nothing (checked in the unit tests: the refused request rolls
        the test's transaction back)."""
        execution_id = _paused_execution(client, as_user, 'ana@example.com,ben@example.com')
        assert _decide(client, as_user, ANA, execution_id).json()['status'] == 'paused'

        response = _decide(client, as_user, ADMIN, execution_id)

        assert response.status_code == 403
        assert response.json()['detail']['code'] == 'approval_not_an_approver'

    def test_an_admin_who_is_an_approver_decides(self, client, as_user, db_session):
        execution_id = _paused_execution(client, as_user, 'ana@example.com,test@example.com')
        assert _decide(client, as_user, ANA, execution_id).json()['status'] == 'paused'

        assert _decide(client, as_user, ADMIN, execution_id).json()['status'] == 'succeeded'


def _role_with_users(db_session, users):
    """An app role with individually assigned users and no groups (#760)."""
    from src.db_models.settings import AppRoleDb

    role = AppRoleDb(
        id=str(uuid.uuid4()), name=f'Reviewers {uuid.uuid4().hex[:8]}',
        feature_permissions='{}', assigned_groups='[]', assigned_users=json.dumps(users),
        home_sections='[]', approval_privileges='{}', is_admin=False,
    )
    db_session.add(role)
    db_session.commit()
    return role


class TestReviewFollowUps:
    """The #1307 review: role members through assigned_users, and the
    outcome from every stored decision."""

    def test_a_user_assigned_to_the_role_decides_for_it(self, client, as_user, db_session):
        role = _role_with_users(db_session, ['eve@example.com'])
        execution_id = _paused_execution(client, as_user, f'{role.id},ana@example.com')

        # Eve sees the role's notification and decides for the role
        as_user(EVE)
        listed = client.get('/api/notifications')
        assert listed.status_code == 200, listed.text
        assert any(
            n.get('recipient_role_id') == role.id
            and (n.get('action_payload') or {}).get('execution_id') == execution_id
            for n in listed.json()
        )
        first = _decide(client, as_user, EVE, execution_id)
        assert first.status_code == 200, first.text
        assert first.json()['pending_approvers'] == 1
        second = _decide(client, as_user, ANA, execution_id)

        assert second.json()['status'] == 'succeeded'
        decisions = _approval_records(db_session, execution_id)[-1]['decisions']
        assert [(d['role_id'], d['decided_by']) for d in decisions] == [
            (role.id, 'eve@example.com'), (None, 'ana@example.com'),
        ]

    def test_a_stored_rejection_fails_the_step(self, client, as_user, db_session):
        """A rejection stored earlier whose resume didn't take effect: the
        last approval doesn't make the run follow on_pass."""
        from src.db_models.process_workflows import WorkflowStepExecutionDb

        execution_id = _paused_execution(client, as_user, 'ana@example.com,ben@example.com')
        db_session.expire_all()
        record = db_session.query(WorkflowStepExecutionDb).filter_by(
            execution_id=execution_id, step_key='approve',
        ).one()
        data = json.loads(record.result_data)
        data['decisions'] = [{
            'target': 'ana@example.com', 'role_id': None, 'decided_by': 'ana@example.com',
            'decision': 'rejected', 'at': '2026-11-04T10:00:00', 'reason': 'No',
        }]
        record.result_data = json.dumps(data)
        db_session.commit()

        response = _decide(client, as_user, BEN, execution_id)

        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'failed'
        decision = _approval_records(db_session, execution_id)[-1]
        assert decision['approval_result'] == 'rejected'
        assert decision['responded_by'] == 'ana@example.com'
        assert decision['reason'] == 'No'


def _decide_by_username(client, as_user, mock_test_user, identity, username, execution_id):
    as_user(identity)
    mock_test_user.username = username
    return client.post(
        '/api/workflows/handle-approval', json={'execution_id': execution_id, 'approved': True},
    )


class TestExplicitPrincipals:
    """The #1309 review: ``group:`` / ``user:`` targets (#1151) under require_all."""

    def test_group_and_user_targets_decide(self, client, as_user, mock_test_user, db_session):
        execution_id = _paused_execution(client, as_user, 'group:team-x,user:ben')

        first = _decide(client, as_user, CARL, execution_id)

        assert first.status_code == 200, first.text
        assert first.json()['pending_approvers'] == 1
        assert _unread_recipients(db_session, execution_id) == {'user:ben'}

        second = _decide_by_username(client, as_user, mock_test_user, BEN, 'ben', execution_id)

        assert second.status_code == 200, second.text
        assert second.json()['status'] == 'succeeded'
        decisions = _approval_records(db_session, execution_id)[-1]['decisions']
        assert [(d['target'], d['decided_by']) for d in decisions] == [
            ('group:team-x', 'carl@example.com'), ('user:ben', 'ben@example.com'),
        ]

    def test_group_names_ignore_case(self, client, as_user, db_session):
        execution_id = _paused_execution(client, as_user, 'group:Team-X')

        response = _decide(client, as_user, DORA, execution_id)

        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'succeeded'

    def test_one_person_listed_twice_decides_once(
        self, client, as_user, mock_test_user, db_session,
    ):
        """``user:ana`` and ``Ana@Example.com``: one decision fills both."""
        execution_id = _paused_execution(
            client, as_user, 'user:ana,Ana@Example.com,ana@example.com,ben@example.com',
        )
        records = _approval_records(db_session, execution_id)
        assert [t['target'] for t in records[0]['resolved_targets']] == [
            'user:ana', 'Ana@Example.com', 'ben@example.com',
        ]

        first = _decide_by_username(client, as_user, mock_test_user, ANA, 'ana', execution_id)

        assert first.status_code == 200, first.text
        assert first.json()['pending_approvers'] == 1
        assert _unread_recipients(db_session, execution_id) == {'ben@example.com'}
        assert _decide(client, as_user, BEN, execution_id).json()['status'] == 'succeeded'


class TestLateApprover:
    """A decision on a step that has ended: 409, not 404."""

    def test_after_everyone_approved(self, client, as_user, db_session):
        execution_id = _paused_execution(client, as_user, 'ana@example.com,ben@example.com')
        assert _decide(client, as_user, ANA, execution_id).json()['status'] == 'paused'
        assert _decide(client, as_user, BEN, execution_id).json()['status'] == 'succeeded'

        late = _decide(client, as_user, ANA, execution_id)

        assert late.status_code == 409
        assert late.json()['detail']['code'] == 'approval_no_longer_pending'

    def test_after_a_rejection(self, client, as_user, db_session):
        execution_id = _paused_execution(client, as_user, 'ana@example.com,team-x')
        assert _decide(client, as_user, ANA, execution_id, approved=False).json()[
            'status'] == 'failed'

        late = _decide(client, as_user, CARL, execution_id)

        assert late.status_code == 409
        assert late.json()['detail']['code'] == 'approval_no_longer_pending'

    def test_once_the_execution_waits_at_a_later_step(self, client, as_user, db_session):
        execution_id = _paused_execution(
            client, as_user, 'ana@example.com,ben@example.com', then='carl@example.com',
        )
        assert _decide(client, as_user, ANA, execution_id).json()['status'] == 'paused'
        assert _decide(client, as_user, BEN, execution_id).json()['status'] == 'paused'

        late = _decide(client, as_user, ANA, execution_id, step_id='approve')

        assert late.status_code == 409
        assert late.json()['detail']['code'] == 'approval_no_longer_pending'

    def test_the_next_step_is_decided_with_its_step_id(self, client, as_user, db_session):
        execution_id = _paused_execution(
            client, as_user, 'ana@example.com,ben@example.com', then='carl@example.com',
        )
        _decide(client, as_user, ANA, execution_id)
        _decide(client, as_user, BEN, execution_id)

        response = _decide(client, as_user, CARL, execution_id, step_id='second')

        assert response.json()['status'] == 'succeeded', response.text

    def test_someone_who_was_never_an_approver_still_gets_403(
        self, client, as_user, db_session,
    ):
        execution_id = _paused_execution(client, as_user, 'ana@example.com,ben@example.com')
        _decide(client, as_user, ANA, execution_id, approved=False)

        assert _decide(client, as_user, EVE, execution_id).status_code == 403


class TestWithoutRequireAll:
    def test_the_first_decision_still_resumes(self, client, as_user, db_session):
        execution_id = _paused_execution(
            client, as_user, 'ana@example.com,ben@example.com', require_all=False,
        )

        response = _decide(client, as_user, ANA, execution_id)

        assert response.json()['status'] == 'succeeded'
        record = _approval_records(db_session, execution_id)[-1]
        assert 'decisions' not in record
        assert _unread_recipients(db_session, execution_id) == set()

    def test_an_admin_who_is_not_an_approver_still_decides(self, client, as_user, db_session):
        execution_id = _paused_execution(
            client, as_user, 'ana@example.com,ben@example.com', require_all=False,
        )

        response = _decide(client, as_user, ADMIN, execution_id)

        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'succeeded'

    def test_a_late_approver_gets_409(self, client, as_user, db_session):
        execution_id = _paused_execution(
            client, as_user, 'ana@example.com,ben@example.com', require_all=False,
        )
        assert _decide(client, as_user, ANA, execution_id).json()['status'] == 'succeeded'

        late = _decide(client, as_user, BEN, execution_id)

        assert late.status_code == 409
        assert late.json()['detail']['code'] == 'approval_no_longer_pending'


REQUESTER = 'requester@example.com'


def _paused_with_notice(client, as_user, db_session, approvers, require_all=True):
    """Paused at an approval whose ``on_fail`` tells the requester, then fails."""
    from src.db_models.process_workflows import WorkflowExecutionDb

    as_user(ADMIN)
    response = client.post('/api/workflows', json={
        'name': f'Cancel {uuid.uuid4().hex[:8]}',
        'trigger': {'type': 'manual', 'entity_types': ['data_product']},
        'is_active': True,
        'steps': [
            {
                'step_id': 'approve', 'name': 'Approve', 'step_type': 'approval',
                'config': {'approvers': approvers, 'require_all': require_all},
                'on_pass': 'ok', 'on_fail': 'tell',
            },
            {
                'step_id': 'tell', 'name': 'Tell the requester', 'step_type': 'notification',
                'config': {
                    'recipients': 'requester', 'template': 'request_rejected',
                    'custom_message': 'Your request was not approved.',
                },
                'on_pass': 'no',
            },
            {'step_id': 'ok', 'name': 'Approved', 'step_type': 'pass'},
            {'step_id': 'no', 'name': 'Rejected', 'step_type': 'fail'},
        ],
    })
    assert response.status_code == 200, response.text
    response = client.post(
        f"/api/workflows/{response.json()['id']}/execute",
        params={'entity_type': 'data_product', 'entity_id': str(uuid.uuid4())},
    )
    assert response.status_code == 200, response.text
    execution_id = response.json()['id']
    assert response.json()['status'] == 'paused'
    # The admin started it; the requester is someone else
    execution = db_session.get(WorkflowExecutionDb, execution_id)
    context = json.loads(execution.trigger_context)
    execution.trigger_context = json.dumps({**context, 'user_email': REQUESTER})
    db_session.flush()
    return execution_id


def _cancel(client, as_user, identity, execution_id):
    as_user(identity)
    return client.post(f'/api/workflows/executions/{execution_id}/cancel')


def _approval_notifications(db_session, execution_id):
    from src.db_models.notifications import NotificationDb

    db_session.expire_all()
    rows = db_session.query(NotificationDb).filter_by(action_type='workflow_approval').all()
    return {
        n.recipient: (n.read, json.loads(n.action_payload or '{}')) for n in rows
        if json.loads(n.action_payload or '{}').get('execution_id') == execution_id
    }


def _requester_notices(db_session):
    from src.db_models.notifications import NotificationDb

    db_session.expire_all()
    return db_session.query(NotificationDb).filter(
        NotificationDb.recipient == REQUESTER,
        NotificationDb.action_type.is_(None) | (NotificationDb.action_type != 'workflow_approval'),
    ).all()


def _cancel_audits(db_session, execution_id):
    from src.db_models.audit_log import AuditLogDb

    db_session.expire_all()
    rows = db_session.query(AuditLogDb).filter_by(
        feature='process-workflows', action='CANCEL_EXECUTION',
    ).all()
    details = [
        r.details if isinstance(r.details, dict) else json.loads(r.details or '{}')
        for r in rows
    ]
    return [d for d in details if d.get('execution_id') == execution_id]


class TestAdminCancel:
    """Admins may cancel a paused approval, never decide it (#1119)."""

    def test_cancel_follows_on_fail_and_records_the_override(
        self, client, as_user, db_session,
    ):
        execution_id = _paused_with_notice(
            client, as_user, db_session, 'ana@example.com,ben@example.com',
        )
        assert _decide(client, as_user, ANA, execution_id).json()['status'] == 'paused'

        response = _cancel(client, as_user, ADMIN, execution_id)

        assert response.status_code == 200, response.text
        body = response.json()
        # The status is the one on_fail leads to (tell the requester, then fail)
        assert body['status'] == 'failed'
        assert body['code'] == 'cancelled_by_admin'
        assert _status(db_session, execution_id) == 'failed'
        # The on_fail path ran once: the requester is told
        assert len(_requester_notices(db_session)) == 1
        # The step ended as failed, with the reason and who cancelled; the
        # admin filled no approver's target
        decision = _approval_records(db_session, execution_id)[-1]
        assert decision['approval_result'] == 'cancelled'
        assert decision['decision'] == 'cancelled'
        assert decision['reason'] == 'cancelled_by_admin'
        assert decision['cancelled_by'] == 'test@example.com'
        assert decision['error_code'] == 'cancelled_by_admin'
        assert [(d['target'], d['decided_by']) for d in decision['decisions']] == [
            ('ana@example.com', 'ana@example.com'),
        ]
        # Ben's open notification is handled as cancelled; Ana's keeps her decision
        notifications = _approval_notifications(db_session, execution_id)
        assert notifications['ben@example.com'][0] is True
        assert notifications['ben@example.com'][1]['decision'] == 'cancelled'
        assert notifications['ben@example.com'][1]['handled_by'] == 'test@example.com'
        assert notifications['ana@example.com'][1]['decision'] == 'approved'
        # Audited as an override
        audits = _cancel_audits(db_session, execution_id)
        assert len(audits) == 1
        assert audits[0]['override'] is True
        assert audits[0]['reason'] == 'cancelled_by_admin'
        assert audits[0]['step_id'] == 'approve'

    def test_the_step_failed_record(self, client, as_user, db_session):
        from src.db_models.process_workflows import WorkflowStepExecutionDb

        execution_id = _paused_with_notice(
            client, as_user, db_session, 'ana@example.com,ben@example.com',
        )

        assert _cancel(client, as_user, ADMIN, execution_id).status_code == 200

        db_session.expire_all()
        rows = db_session.query(WorkflowStepExecutionDb).filter_by(
            execution_id=execution_id, step_key='approve',
        ).all()
        # The pause record, then the decision record: failed
        decided = [r for r in rows if 'approval_result' in (r.result_data or '')]
        assert [(r.status, r.passed) for r in decided] == [('failed', False)]
        steps = {r.step_key for r in db_session.query(WorkflowStepExecutionDb).filter_by(
            execution_id=execution_id,
        ).all()}
        assert steps == {'approve', 'tell', 'no'}

    def test_a_late_approver_gets_409(self, client, as_user, db_session):
        execution_id = _paused_with_notice(
            client, as_user, db_session, 'ana@example.com,ben@example.com',
        )
        assert _cancel(client, as_user, ADMIN, execution_id).status_code == 200

        late = _decide(client, as_user, BEN, execution_id)

        assert late.status_code == 409
        assert late.json()['detail']['code'] == 'approval_no_longer_pending'

    def test_without_require_all_cancel_also_follows_on_fail(
        self, client, as_user, db_session,
    ):
        execution_id = _paused_with_notice(
            client, as_user, db_session, 'ana@example.com,ben@example.com', require_all=False,
        )

        response = _cancel(client, as_user, ADMIN, execution_id)

        assert response.json()['status'] == 'failed', response.text
        assert len(_requester_notices(db_session)) == 1
        assert _unread_recipients(db_session, execution_id) == set()
        assert 'decisions' not in _approval_records(db_session, execution_id)[-1]

    def test_someone_who_is_not_an_admin_cannot_cancel(self, client, as_user, db_session):
        execution_id = _paused_with_notice(
            client, as_user, db_session, 'ana@example.com,ben@example.com',
        )

        assert _cancel(client, as_user, ANA, execution_id).status_code == 403

    def test_an_admin_cannot_force_a_decision(self, client, as_user, db_session):
        """The execution view's force approve / reject (``/resume``) decides
        for the approvers: refused with require_all."""
        execution_id = _paused_with_notice(
            client, as_user, db_session, 'ana@example.com,ben@example.com',
        )
        as_user(ADMIN)

        response = client.post(
            f'/api/workflows/executions/{execution_id}/resume', json={'approved': True},
        )

        assert response.status_code == 403
        assert response.json()['detail']['code'] == 'approval_not_an_approver'

    def test_without_require_all_an_admin_still_forces_a_decision(
        self, client, as_user, db_session,
    ):
        execution_id = _paused_with_notice(
            client, as_user, db_session, 'ana@example.com,ben@example.com', require_all=False,
        )
        as_user(ADMIN)

        response = client.post(
            f'/api/workflows/executions/{execution_id}/resume', json={'approved': True},
        )

        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'succeeded'


class TestCancelNotAtAnApproval:
    """A running execution, or one paused elsewhere, is cancelled as before."""

    @pytest.mark.parametrize('status, step', [('running', None), ('paused', 'ok')])
    def test_status_cancelled(self, client, as_user, db_session, status, step):
        from src.db_models.process_workflows import WorkflowExecutionDb

        paused_id = _paused_with_notice(
            client, as_user, db_session, 'ana@example.com,ben@example.com',
        )
        execution = db_session.get(WorkflowExecutionDb, paused_id)
        execution.status, execution.current_step_id = status, step
        db_session.flush()

        response = _cancel(client, as_user, ADMIN, paused_id)

        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'cancelled'
        assert 'code' not in response.json()
        assert _status(db_session, paused_id) == 'cancelled'
        assert _requester_notices(db_session) == []
        audits = _cancel_audits(db_session, paused_id)
        assert len(audits) == 1 and 'override' not in audits[0]
