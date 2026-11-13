"""Who may read, change and cancel metric view change requests (#1124 phase 3).

Reads go through Unity Catalog as the user: a user it refuses gets 404. Create,
submit and cancel need ``assets`` Read/Write; cancel is for the requester or an
assets admin. Cancelling a request in review cancels its paused workflow and
closes the approvers' notifications.
"""
import json
import uuid

import pytest
from databricks.sdk.errors import PermissionDenied

from src.db_models.process_workflows import WorkflowExecutionDb
from src.tests.integration.test_metric_view_change_request_workflow import (  # noqa: F401
    OWNER, PROPOSED, TOKEN, _approvals, _as, _submitted, asset, user_ws, workflow,
)

READERS, WRITERS, ASSET_ADMINS = 'mv-readers', 'mv-writers', 'mv-asset-admins'


def _role(client, group, level):
    """A role giving ``group`` the ``assets`` feature at ``level`` (as the admin test user)."""
    role = client.post('/api/settings/roles', json={
        'name': f'{group} {uuid.uuid4().hex[:6]}', 'description': 'test',
        'assigned_groups': [group], 'feature_permissions': {'assets': level},
    })
    assert role.status_code == 201, role.text


def _url(asset, request_id=None, action=None):
    url = f'/api/assets/{asset.id}/metric-view/change-requests'
    if request_id:
        url += f'/{request_id}'
    return f'{url}/{action}' if action else url


# A refused request rolls the test transaction back: each test ends with at most one.

@pytest.mark.parametrize('read', ['list', 'detail'])
def test_a_user_unity_catalog_refuses_gets_404(client, asset, user_ws, workflow, read):
    request = _submitted(client, asset)
    user_ws.tables.get.side_effect = PermissionDenied('no SELECT on the metric view')

    response = client.get(_url(asset, request['id'] if read == 'detail' else None),
                          headers=TOKEN)

    assert response.status_code == 404, response.text
    assert response.json()['detail']['code'] == 'metric_view_not_found'


@pytest.mark.parametrize('action', ['create', 'submit', 'cancel'])
def test_a_read_only_user_cannot_change(client, asset, user_ws, workflow, action):
    request = _submitted(client, asset)
    _role(client, READERS, 'Read-only')
    _as('reader@example.com', [READERS])

    if action == 'create':
        response = client.post(_url(asset), headers=TOKEN, json={'definition': PROPOSED})
    else:
        response = client.post(_url(asset, request['id'], action), headers=TOKEN)

    assert response.status_code == 403, response.text
    # Refused by the route's Read/Write permission check, before the asset is read
    assert 'Required level: Read/Write' in response.json()['detail']


def test_a_writer_who_is_not_the_requester_cannot_cancel(client, asset, user_ws, workflow):
    request = _submitted(client, asset)
    _role(client, WRITERS, 'Read/Write')
    _as('writer@example.com', [WRITERS])

    response = client.post(_url(asset, request['id'], 'cancel'), headers=TOKEN)

    assert response.status_code == 403, response.text
    assert response.json()['detail']['code'] == 'metric_view_change_request_not_requester'


def test_an_assets_admin_cancels_another_users_request(client, asset, user_ws, workflow):
    request = _submitted(client, asset)
    _role(client, ASSET_ADMINS, 'Admin')
    _as('asset-admin@example.com', [ASSET_ADMINS])

    response = client.post(_url(asset, request['id'], 'cancel'), headers=TOKEN)

    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'cancelled'


def test_cancelling_in_review_cancels_the_workflow_and_closes_the_approvals(
    client, db_session, asset, user_ws, workflow
):
    request = _submitted(client, asset)
    execution_id = request['workflow_execution_id']
    assert [n.recipient for n in _approvals(db_session, execution_id)] == [OWNER]

    cancelled = client.post(_url(asset, request['id'], 'cancel'), headers=TOKEN)

    assert cancelled.status_code == 200, cancelled.text
    db_session.expire_all()
    execution = db_session.get(WorkflowExecutionDb, execution_id)
    assert execution.status == 'cancelled' and execution.finished_at is not None
    approvals = _approvals(db_session, execution_id)
    assert approvals and all(n.read for n in approvals)
    for notification in approvals:
        payload = json.loads(notification.action_payload)
        assert payload['handled'] is True and payload['decision'] == 'cancelled'
        assert payload['handled_by'] == 'test@example.com'
