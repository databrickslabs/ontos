"""Metric view change requests through the default review workflow (#1124 phase 3).

The asset routes create and submit the request (Unity Catalog read as the
user, mocked); the shipped "Metric View Change Request" workflow asks the
asset's owners; the decision goes through ``/api/workflows/handle-approval``.
"""
import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.service.catalog import TableType

from src.app import app
from src.common.authorization import get_user_details_from_sdk
from src.controller.metric_view_change_requests_manager import (
    MANUAL_TITLE_KEY, MetricViewChangeRequestsManager,
)
from src.controller.workflows_manager import WorkflowsManager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.business_owners import BusinessOwnerDb
from src.db_models.business_roles import BusinessRoleDb
from src.db_models.metric_view_baselines import MetricViewBaselineDb
from src.db_models.metric_view_change_requests import MetricViewChangeRequestDb
from src.db_models.notifications import NotificationDb
from src.models.users import UserInfo

VIEW = 'main.sales.orders_mv'
BASE = """\
version: 1.1
source: main.sales.orders
dimensions:
  - name: Region
    expr: region
measures:
  - name: Total Revenue
    expr: SUM(amount)
"""
PROPOSED = BASE.replace('SUM(amount)', 'SUM(net_amount)')
OWNER = 'owner@example.com'
TOKEN = {'x-forwarded-access-token': 'user-token'}
WORKFLOW = 'Metric View Change Request'


@pytest.fixture
def asset(db_session):
    asset_type = AssetTypeDb(name=f'Metric View-{uuid.uuid4().hex[:6]}', category='semantic')
    db_session.add(asset_type)
    db_session.flush()
    row = AssetDb(name='orders_mv', asset_type_id=asset_type.id, platform='databricks',
                  location=VIEW)
    db_session.add(row)
    role = db_session.query(BusinessRoleDb).filter_by(name='Data Owner').first()
    if role is None:
        role = BusinessRoleDb(id=uuid.uuid4(), name='Data Owner')
        db_session.add(role)
        db_session.flush()
    db_session.add(BusinessOwnerDb(
        id=uuid.uuid4(), object_type='asset', object_id=str(row.id),
        user_email=OWNER, role_id=role.id, is_active=True,
    ))
    db_session.flush()
    return row


@pytest.fixture
def user_ws(monkeypatch):
    from src.routes import assets_routes

    ws = MagicMock()
    ws.tables.get.return_value = SimpleNamespace(
        table_type=TableType.METRIC_VIEW, view_definition=BASE, pipeline_id=None,
        owner=OWNER,
    )
    monkeypatch.setattr(assets_routes, 'get_obo_workspace_client', lambda request: ws,
                        raising=False)
    return ws


@pytest.fixture
def workflow(db_session, monkeypatch):
    """The shipped default workflows, and Manual delivery."""
    manager = WorkflowsManager(db_session)
    manager.load_from_yaml()
    monkeypatch.setattr(MetricViewChangeRequestsManager, '_delivery_modes',
                        lambda self: ['manual'])
    matches = [w for w in manager.list_workflows() if w.name == WORKFLOW]
    assert len(matches) == 1
    return matches[0]


def _as(user_email, groups=()):
    async def _override():
        return UserInfo(username=user_email, email=user_email, user=user_email,
                        ip='127.0.0.1', groups=list(groups))
    app.dependency_overrides[get_user_details_from_sdk] = _override


def _submitted(client, asset):
    created = client.post(f'/api/assets/{asset.id}/metric-view/change-requests', headers=TOKEN,
                          json={'definition': PROPOSED, 'justification': 'Net of refunds'})
    assert created.status_code == 201, created.text
    request_id = created.json()['id']
    submitted = client.post(
        f'/api/assets/{asset.id}/metric-view/change-requests/{request_id}/submit',
        headers=TOKEN,
    )
    assert submitted.status_code == 200, submitted.text
    return submitted.json()


def _approvals(db_session, execution_id):
    rows = db_session.query(NotificationDb).filter(
        NotificationDb.action_type == 'workflow_approval').all()
    return [n for n in rows if json.loads(n.action_payload or '{}').get('execution_id')
            == execution_id]


def _decide(client, execution_id, approved):
    return client.post('/api/workflows/handle-approval', json={
        'execution_id': execution_id, 'approved': approved, 'message': 'checked',
    })


def test_the_default_workflow_is_active_on_the_new_trigger(workflow):
    assert workflow.is_active and workflow.is_default
    assert workflow.trigger.type.value == 'on_request_definition_change'
    assert [e.value for e in workflow.trigger.entity_types] == ['metric_view']
    approval = next(s for s in workflow.steps if s.step_type.value == 'approval')
    assert approval.config['approvers'] == 'AssetOwner'


def test_the_trigger_asks_the_owners_and_their_approval_delivers(
    client, db_session, asset, user_ws, workflow, mock_test_user
):
    request = _submitted(client, asset)

    assert request['status'] == 'in_review'
    execution_id = request['workflow_execution_id']
    assert [n.recipient for n in _approvals(db_session, execution_id)] == [OWNER]

    _as(OWNER)
    response = _decide(client, execution_id, True)

    assert response.status_code == 200, response.text
    row = db_session.get(MetricViewChangeRequestDb, uuid.UUID(request['id']))
    db_session.refresh(row)
    assert row.status == 'delivered' and row.decided_by == OWNER
    assert row.decision_message == 'checked'
    manual = [n for n in db_session.query(NotificationDb).all()
              if json.loads(n.data or '{}').get('i18n', {}).get('title') == MANUAL_TITLE_KEY]
    assert [n.recipient for n in manual] == [OWNER]
    assert 'ALTER VIEW `main`.`sales`.`orders_mv` AS $$' in manual[0].description


def test_the_requester_cannot_approve_their_own_request(
    client, db_session, asset, user_ws, workflow, mock_test_user
):
    # No owner other than the requester: the approval falls back to the
    # stewards and admins, a role the requester holds
    db_session.query(BusinessOwnerDb).filter(
        BusinessOwnerDb.object_id == str(asset.id)).update({'user_email': mock_test_user.email})
    db_session.flush()
    request = _submitted(client, asset)
    execution_id = request['workflow_execution_id']
    assert all(n.recipient_role_id for n in _approvals(db_session, execution_id))

    response = _decide(client, execution_id, True)

    assert response.status_code == 403
    assert response.json()['detail']['code'] == 'own_change_request_approval'
    # (the refused request rolls the test transaction back: nothing to read after it)


def test_a_rejection_keeps_the_baseline(client, db_session, asset, user_ws, workflow):
    read = client.get(f'/api/assets/{asset.id}/metric-view', headers=TOKEN)
    assert read.status_code == 200, read.text
    baseline_digest = read.json()['baseline']['digest']
    request = _submitted(client, asset)

    _as(OWNER)
    response = _decide(client, request['workflow_execution_id'], False)

    assert response.status_code == 200, response.text
    row = db_session.get(MetricViewChangeRequestDb, uuid.UUID(request['id']))
    db_session.refresh(row)
    assert row.status == 'rejected' and row.delivered_at is None
    baseline = db_session.query(MetricViewBaselineDb).one()
    assert baseline.digest == baseline_digest and baseline.request_id is None


def test_the_routes_refuse_an_invalid_proposal_with_a_coded_error(client, asset, user_ws):
    response = client.post(f'/api/assets/{asset.id}/metric-view/change-requests',
                           headers=TOKEN, json={'definition': 'source: [unclosed\n'})

    assert response.status_code == 422
    detail = response.json()['detail']
    assert detail['code'] == 'metric_view_definition_invalid_yaml'
    assert set(detail['params']) == {'line', 'column'}


def test_the_routes_read_unity_catalog_as_the_user(client, asset, user_ws):
    response = client.get(f'/api/assets/{asset.id}/metric-view/change-requests')

    assert response.status_code == 403
    assert response.json()['detail']['code'] == 'user_token_required'


def test_the_list_shows_the_asset_requests(client, asset, user_ws, workflow):
    request = _submitted(client, asset)

    response = client.get(f'/api/assets/{asset.id}/metric-view/change-requests', headers=TOKEN)

    assert response.status_code == 200, response.text
    assert [(r['id'], r['status']) for r in response.json()] == [(request['id'], 'in_review')]
    detail = client.get(
        f"/api/assets/{asset.id}/metric-view/change-requests/{request['id']}", headers=TOKEN,
    ).json()
    assert detail['base_definition'] == BASE
    assert detail['proposed_metric_view']['measures'][0]['expr'] == 'SUM(net_amount)'
