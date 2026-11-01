"""``require_all`` on an approval step (#1119), through the API.

Each resolved approver decides once: a user for themselves, any one member for
a group. The execution stays paused until all have approved; any rejection
fails the step. Decisions are stored with the step. ``require_all: false``
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


def _paused_execution(client, as_user, approvers, require_all=True):
    as_user(ADMIN)
    response = client.post('/api/workflows', json={
        'name': f'Require all {uuid.uuid4().hex[:8]}',
        'trigger': {'type': 'manual', 'entity_types': ['data_product']},
        'is_active': True,
        'steps': [
            {
                'step_id': 'approve', 'name': 'Approve', 'step_type': 'approval',
                'config': {'approvers': approvers, 'require_all': require_all},
                'on_pass': 'ok', 'on_fail': 'no',
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
    execution = response.json()
    assert execution['status'] == 'paused', execution
    return execution['id']


def _decide(client, as_user, identity, execution_id, approved=True, reason=None):
    as_user(identity)
    body = {'execution_id': execution_id, 'approved': approved}
    if reason:
        body['reason'] = reason
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
        decision = _approval_records(db_session, execution_id)[-1]
        assert decision['approval_result'] == 'approved'
        assert decision['responded_by'] == 'ben@example.com'
        assert [(d['approver'], d['decision'], d['decided_by']) for d in decision['decisions']] == [
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
        assert [(d['approver'], d['decided_by']) for d in decisions] == [
            ('team-x', 'carl@example.com'), ('ana@example.com', 'ana@example.com'),
        ]

    def test_another_member_of_a_decided_group_does_not_count(
        self, client, as_user, db_session,
    ):
        execution_id = _paused_execution(client, as_user, 'ana@example.com,team-x')
        assert _decide(client, as_user, CARL, execution_id).json()['status'] == 'paused'

        response = _decide(client, as_user, DORA, execution_id)

        assert response.status_code == 409

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
