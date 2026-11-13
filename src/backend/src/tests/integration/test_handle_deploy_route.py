"""POST /data-contracts/{id}/handle-deploy records the decision and deploys nothing
(#1151 item 1). Only an approver of the deployment request decides it.

A refused request rolls back the test's transaction (``get_db`` rolls back on
any exception), so a test ends with its refusal."""
import json
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from src.db_models.notifications import NotificationDb


def _contract_id(client: TestClient, db_session=None, recipient='Admin', role_id=None) -> str:
    """A contract with a pending deployment request addressed to ``recipient``
    (the request route addresses the Admin role)."""
    response = client.post('/api/data-contracts', json={
        'name': 'Deploy Route Contract', 'version': '1.0.0', 'status': 'draft',
        'owner': 'test@example.com',
    })
    assert response.status_code == 200, response.text
    contract_id = response.json()['id']
    if db_session is not None:
        db_session.add(NotificationDb(
            id=str(uuid.uuid4()), type='action_required', title='Contract Deployment Request',
            recipient=recipient, recipient_role_id=role_id, created_at=datetime.utcnow(),
            action_type='handle_deploy_request', can_delete=False, read=False,
            action_payload=json.dumps({
                'contract_id': contract_id, 'requester_email': 'test@example.com',
            }),
        ))
        db_session.commit()
    return contract_id


@pytest.fixture
def as_user(mock_test_user):
    def _switch(email, groups):
        mock_test_user.email = email
        mock_test_user.username = email
        mock_test_user.user = email
        mock_test_user.groups = list(groups)
    yield _switch
    _switch('test@example.com', ['test_admins'])
    mock_test_user.username = 'test_user'
    mock_test_user.user = 'test_user'


def _decide(client, contract_id):
    return client.post(
        f'/api/data-contracts/{contract_id}/handle-deploy', json={'decision': 'approve'},
    )


# A Data Producer (data-contracts read/write), not an admin
EDITOR = ('pat@example.com', ['data-producers'])


class TestDeployApprover:
    def test_an_editor_who_is_no_approver_is_refused(self, client, db_session, as_user):
        contract_id = _contract_id(client, db_session)
        as_user(*EDITOR)

        response = _decide(client, contract_id)

        assert response.status_code == 403, response.text
        assert response.json()['detail']['code'] == 'deploy_request_not_an_approver'

    def test_an_admin_decides_the_request_to_the_admin_role(self, client, db_session):
        contract_id = _contract_id(client, db_session)

        assert _decide(client, contract_id).status_code == 200

    def test_without_a_request_nobody_decides(self, client):
        response = _decide(client, _contract_id(client))

        assert response.status_code == 403, response.text

    def test_a_request_is_decided_once(self, client, db_session):
        contract_id = _contract_id(client, db_session)
        assert _decide(client, contract_id).status_code == 200
        db_session.expire_all()
        payload = json.loads(db_session.query(NotificationDb).filter_by(
            action_type='handle_deploy_request',
        ).one().action_payload)
        assert (payload['handled'], payload['decision']) == (True, 'approve')

        again = client.post(
            f'/api/data-contracts/{contract_id}/handle-deploy', json={'decision': 'deny'},
        )

        assert again.status_code == 409, again.text
        assert again.json()['detail']['code'] == 'deploy_request_already_decided'

    def test_a_request_a_workflow_handles_is_decided_by_the_workflow(self, client, db_session):
        """Only a workflow approval notification: even an admin is refused here."""
        contract_id = _contract_id(client)
        db_session.add(NotificationDb(
            id=str(uuid.uuid4()), type='action_required', title='Approval Required',
            recipient='Admin', created_at=datetime.utcnow(), action_type='workflow_approval',
            can_delete=False, read=False, action_payload=json.dumps({
                'execution_id': str(uuid.uuid4()), 'entity_type': 'data_contract',
                'entity_id': contract_id, 'contract_id': contract_id,
            }),
        ))
        db_session.commit()

        response = _decide(client, contract_id)

        assert response.status_code == 403, response.text
        assert response.json()['detail']['code'] == 'deploy_request_not_an_approver'

    def test_a_member_of_a_recipient_group_decides(self, client, db_session, as_user):
        contract_id = _contract_id(client, db_session, recipient='group:release-managers')
        as_user('rita@example.com', ['data-producers', 'release-managers'])

        assert _decide(client, contract_id).status_code == 200

    def test_a_member_of_a_recipient_role_decides(self, client, db_session, as_user):
        from src.db_models.settings import AppRoleDb

        role = db_session.query(AppRoleDb).filter(AppRoleDb.name == 'Data Producer').one()
        contract_id = _contract_id(client, db_session, recipient=role.name, role_id=role.id)
        as_user(*EDITOR)

        assert _decide(client, contract_id).status_code == 200


def test_execute_deployment_is_accepted_and_answered_with_a_warning(
    client: TestClient, db_session,
):
    contract_id = _contract_id(client, db_session)

    response = client.post(
        f'/api/data-contracts/{contract_id}/handle-deploy',
        json={'decision': 'approve', 'execute_deployment': True},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body['message'] == "Deploy decision 'approve' recorded successfully"
    assert [w['code'] for w in body['warnings']] == ['deployment_not_available']
    assert 'job_id' not in body


def test_an_approval_without_the_flag_has_no_warning(client: TestClient, db_session):
    contract_id = _contract_id(client, db_session)

    response = client.post(
        f'/api/data-contracts/{contract_id}/handle-deploy', json={'decision': 'approve'},
    )

    assert response.status_code == 200, response.text
    assert 'warnings' not in response.json()


def test_the_openapi_description_says_the_flag_is_ignored(client: TestClient):
    schema = client.get('/openapi.json').json()
    field = schema['components']['schemas']['HandleDeployPayload']['properties'][
        'execute_deployment'
    ]
    assert field['description'].startswith('Ignored.')
