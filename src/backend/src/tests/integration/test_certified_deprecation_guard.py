"""Deprecating a certified product or contract needs an approved status change request.

The certified guard of the lifecycle PRD (part of #998): ``transition_status``
refuses a direct move to ``deprecated`` when ``certification_level`` is set,
with the code ``certified_deprecation_requires_approval``. The approved status
change request applies it; uncertified entities deprecate directly; the guard
can be switched off per domain or entity (``disabled_for``), and each skip is
audited as ``GATE_SKIPPED``.

Through the routes, on the test database, with the app's managers. A refused
contract request rolls back the test's transaction (the route's session is
bound to it), so each contract test checks the database before its refusal.
"""
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.app import app
from src.common.authorization import get_user_details_from_sdk
from src.controller.workflows_manager import WorkflowsManager
from src.db_models.audit_log import AuditLogDb
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_domains import DataDomain
from src.db_models.data_products import DataProductDb
from src.db_models.domain_associations import EntityDomainAssociationDb
from src.db_models.notifications import NotificationDb
from src.models.users import UserInfo

CODE = 'certified_deprecation_requires_approval'
REFUSED = 'certified_deprecation_approval_refused'


def _act_as(username: str, groups=('test_admins',)) -> UserInfo:
    """Send the next requests as another user (an admin by default)."""
    user = UserInfo(
        username=username, email=f'{username}@example.com', user=username,
        ip='127.0.0.1', groups=list(groups),
    )

    async def _user():
        return user

    app.dependency_overrides[get_user_details_from_sdk] = _user
    return user


def _domain(db: Session, name: str) -> str:
    domain_id = str(uuid.uuid4())
    db.add(DataDomain(id=domain_id, name=f'{name} {domain_id[:6]}', created_by='admin@example.com'))
    db.commit()
    return domain_id


def _assign(db: Session, entity_type: str, entity_id: str, domain_id: str) -> None:
    db.add(EntityDomainAssociationDb(
        domain_id=domain_id, entity_type=entity_type, entity_id=entity_id, is_primary=True,
    ))
    db.commit()


def _product(db: Session, certified: bool = True, domain_id: str = None) -> str:
    product_id = str(uuid.uuid4())
    db.add(DataProductDb(
        id=product_id, name=f'Product {product_id[:8]}', version='1.0.0', status='active',
        api_version='v1.0.0', kind='DataProduct',
        certification_level=1 if certified else None,
    ))
    db.commit()
    if domain_id:
        _assign(db, 'data_product', product_id, domain_id)
    return product_id


def _contract(db: Session, certified: bool = True, domain_id: str = None) -> str:
    contract_id = str(uuid.uuid4())
    db.add(DataContractDb(
        id=contract_id, name=f'Contract {contract_id[:8]}', version='1.0.0', status='active',
        certification_level=1 if certified else None,
    ))
    db.commit()
    if domain_id:
        _assign(db, 'data_contract', contract_id, domain_id)
    return contract_id


def _status(db: Session, model, entity_id: str) -> str:
    db.expire_all()
    return db.get(model, entity_id).status


def _deprecate_product(client: TestClient, product_id: str):
    return client.post(
        f'/api/data-products/{product_id}/change-status', json={'new_status': 'deprecated'},
    )


def _deprecate_contract(client: TestClient, contract_id: str):
    return client.post(
        f'/api/data-contracts/{contract_id}/change-status', json={'new_status': 'deprecated'},
    )


def _assert_refused(response, entity_type: str, entity_id: str) -> None:
    assert response.status_code == 400, response.text
    detail = response.json()['detail']
    assert detail['code'] == CODE
    assert detail['params']['entityType'] == entity_type
    assert detail['params']['entityId'] == entity_id
    assert detail['params']['certificationLevel'] == 1


def _guard_skips(db: Session, entity_id: str):
    db.expire_all()
    entries = db.query(AuditLogDb).filter(AuditLogDb.action == 'GATE_SKIPPED').all()
    details = [json.loads(e.details) if isinstance(e.details, str) else e.details for e in entries]
    return [d for d in details if d.get('entity_id') == entity_id]


class TestDirectDeprecation:
    def test_a_certified_product_is_refused_with_the_code(self, client, db_session):
        product_id = _product(db_session)

        response = _deprecate_product(client, product_id)

        _assert_refused(response, 'data_product', product_id)
        assert _status(db_session, DataProductDb, product_id) == 'active'

    def test_a_certified_contract_is_refused_with_the_code(self, client, db_session):
        contract_id = _contract(db_session)

        response = _deprecate_contract(client, contract_id)

        _assert_refused(response, 'data_contract', contract_id)

    def test_the_deprecate_route_of_a_product_is_refused_too(self, client, db_session):
        product_id = _product(db_session)

        response = client.post(f'/api/data-products/{product_id}/deprecate')

        _assert_refused(response, 'data_product', product_id)
        assert _status(db_session, DataProductDb, product_id) == 'active'

    def test_an_uncertified_product_deprecates_directly(self, client, db_session):
        product_id = _product(db_session, certified=False)

        response = _deprecate_product(client, product_id)

        assert response.status_code == 200, response.text
        assert _status(db_session, DataProductDb, product_id) == 'deprecated'

    def test_an_uncertified_contract_deprecates_directly(self, client, db_session):
        contract_id = _contract(db_session, certified=False)

        response = _deprecate_contract(client, contract_id)

        assert response.status_code == 200, response.text
        assert _status(db_session, DataContractDb, contract_id) == 'deprecated'

    def test_other_transitions_of_a_certified_product_are_not_guarded(self, client, db_session):
        product_id = _product(db_session)
        db_session.get(DataProductDb, product_id).status = 'approved'
        db_session.commit()

        response = client.post(
            f'/api/data-products/{product_id}/change-status', json={'new_status': 'active'},
        )

        assert response.status_code == 200, response.text
        assert _status(db_session, DataProductDb, product_id) == 'active'


def _request(client: TestClient, kind: str, entity_id: str, target: str = 'deprecated'):
    requested = client.post(
        f'/api/{kind}/{entity_id}/request-status-change',
        json={'target_status': target,
              'justification': 'Replaced by the v2 version, consumers moved'},
    )
    assert requested.status_code == 200, requested.text
    return requested.json()


def _decide(client: TestClient, kind: str, entity_id: str, target: str = 'deprecated'):
    return client.post(
        f'/api/{kind}/{entity_id}/handle-status-change',
        json={'decision': 'approve', 'target_status': target,
              'requester_email': 'test@example.com'},
    )


def _assert_approval_refused(response, reason: str) -> None:
    assert response.status_code == 400, response.text
    detail = response.json()['detail']
    assert detail['code'] == REFUSED
    assert detail['params']['reason'] == reason


class TestApprovedRequest:
    def test_an_approved_product_request_deprecates_it(self, client, db_session):
        WorkflowsManager(db=db_session).load_from_yaml()
        product_id = _product(db_session)

        execution_id = _request(client, 'data-products', product_id).get('execution_id')
        assert execution_id
        assert _status(db_session, DataProductDb, product_id) == 'active'

        _act_as('steward')
        approved = client.post(
            '/api/workflows/handle-approval',
            json={'execution_id': execution_id, 'approved': True, 'message': 'OK'},
        )

        assert approved.status_code == 200, approved.text
        assert _status(db_session, DataProductDb, product_id) == 'deprecated'

    def test_the_requester_approving_their_own_product_request_does_not_count(
        self, client, db_session,
    ):
        WorkflowsManager(db=db_session).load_from_yaml()
        product_id = _product(db_session)
        execution_id = _request(client, 'data-products', product_id)['execution_id']

        approved = client.post(
            '/api/workflows/handle-approval',
            json={'execution_id': execution_id, 'approved': True, 'message': 'OK'},
        )

        assert approved.status_code == 200, approved.text
        assert _status(db_session, DataProductDb, product_id) == 'active'

    def test_resuming_the_execution_is_not_an_approval(self, client, db_session):
        WorkflowsManager(db=db_session).load_from_yaml()
        product_id = _product(db_session)
        execution_id = _request(client, 'data-products', product_id)['execution_id']

        _act_as('steward')
        resumed = client.post(
            f'/api/workflows/executions/{execution_id}/resume', json={'approved': True},
        )

        assert resumed.status_code == 200, resumed.text
        assert _status(db_session, DataProductDb, product_id) == 'active'

    @pytest.mark.parametrize('kind, model, make', [
        ('data-products', DataProductDb, _product),
        ('data-contracts', DataContractDb, _contract),
    ])
    def test_another_admin_approving_a_pending_request_applies_it(
        self, client, db_session, kind, model, make,
    ):
        entity_id = make(db_session)
        _request(client, kind, entity_id)
        assert _status(db_session, model, entity_id) == 'active'

        _act_as('steward')
        approved = _decide(client, kind, entity_id)

        assert approved.status_code == 200, approved.text
        assert _status(db_session, model, entity_id) == 'deprecated'

    @pytest.mark.parametrize('kind, entity_type, make', [
        ('data-products', 'data_product', _product),
        ('data-contracts', 'data_contract', _contract),
    ])
    def test_an_approval_without_a_request_is_refused(
        self, client, db_session, kind, entity_type, make,
    ):
        entity_id = make(db_session)

        _assert_approval_refused(_decide(client, kind, entity_id), 'no_pending_request')

    @pytest.mark.parametrize('kind, model, make', [
        ('data-products', DataProductDb, _product), ('data-contracts', DataContractDb, _contract),
    ])
    def test_an_approval_for_another_target_is_refused(
        self, client, db_session, kind, model, make,
    ):
        # Approved entities may go to active or deprecated: the request is for active
        entity_id = make(db_session)
        db_session.get(model, entity_id).status = 'approved'
        db_session.commit()
        _request(client, kind, entity_id, target='active')

        _act_as('steward')
        _assert_approval_refused(_decide(client, kind, entity_id), 'target_mismatch')

    @pytest.mark.parametrize('kind, make', [
        ('data-products', _product), ('data-contracts', _contract),
    ])
    def test_approving_ones_own_request_is_refused(self, client, db_session, kind, make):
        entity_id = make(db_session)
        _request(client, kind, entity_id)

        _assert_approval_refused(_decide(client, kind, entity_id), 'self_approval')

    def test_a_decided_request_cannot_be_approved_again(self, client, db_session):
        product_id = _product(db_session)
        _request(client, 'data-products', product_id)
        _act_as('steward')
        denied = client.post(
            f'/api/data-products/{product_id}/handle-status-change',
            json={'decision': 'deny', 'target_status': 'deprecated',
                  'requester_email': 'test_user'},
        )
        assert denied.status_code == 200, denied.text

        _assert_approval_refused(_decide(client, 'data-products', product_id),
                                 'no_pending_request')


def _change(client: TestClient, kind: str, entity_id: str, status: str) -> None:
    changed = client.post(f'/api/{kind}/{entity_id}/change-status', json={'new_status': status})
    assert changed.status_code == 200, changed.text


KINDS = [
    ('data-products', DataProductDb, _product),
    ('data-contracts', DataContractDb, _contract),
]


class TestOneDecisionPerRequest:
    """A decision is tied to one request: once decided, or once the entity moved, it is gone."""

    def test_a_request_rejected_in_the_workflow_cannot_be_approved_later(
        self, client, db_session,
    ):
        WorkflowsManager(db=db_session).load_from_yaml()
        product_id = _product(db_session)
        execution_id = _request(client, 'data-products', product_id)['execution_id']
        _act_as('steward')
        rejected = client.post(
            '/api/workflows/handle-approval',
            json={'execution_id': execution_id, 'approved': False, 'message': 'No'},
        )
        assert rejected.status_code == 200, rejected.text

        _act_as('second_admin')
        _assert_approval_refused(_decide(client, 'data-products', product_id),
                                 'no_pending_request')

    def test_a_workflow_approval_after_the_request_was_decided_elsewhere_applies_nothing(
        self, client, db_session,
    ):
        WorkflowsManager(db=db_session).load_from_yaml()
        product_id = _product(db_session)
        execution_id = _request(client, 'data-products', product_id)['execution_id']
        _act_as('steward')
        assert _decide(client, 'data-products', product_id).status_code == 200
        _change(client, 'data-products', product_id, 'active')

        approved = client.post(
            '/api/workflows/handle-approval',
            json={'execution_id': execution_id, 'approved': True, 'message': 'OK'},
        )

        assert approved.status_code == 200, approved.text
        assert _status(db_session, DataProductDb, product_id) == 'active'

    @pytest.mark.parametrize('kind, model, make', KINDS)
    def test_a_request_outlived_by_a_transition_is_not_pending(
        self, client, db_session, kind, model, make,
    ):
        # Requested while uncertified; deprecated and reactivated directly; then
        # certified: the old request must not deprecate it now
        entity_id = make(db_session, certified=False)
        _request(client, kind, entity_id)
        _change(client, kind, entity_id, 'deprecated')
        _change(client, kind, entity_id, 'active')
        db_session.get(model, entity_id).certification_level = 1
        db_session.commit()

        _act_as('steward')
        _assert_approval_refused(_decide(client, kind, entity_id), 'no_pending_request')

    @pytest.mark.parametrize('kind, model, make', KINDS)
    def test_a_second_request_does_not_deprecate_again_after_a_reactivation(
        self, client, db_session, kind, model, make,
    ):
        entity_id = make(db_session)
        _request(client, kind, entity_id)
        _request(client, kind, entity_id)
        _act_as('steward')
        assert _decide(client, kind, entity_id).status_code == 200
        assert _status(db_session, model, entity_id) == 'deprecated'
        _change(client, kind, entity_id, 'active')

        _assert_approval_refused(_decide(client, kind, entity_id), 'no_pending_request')

    def test_a_contract_request_denied_cannot_be_approved_later(self, client, db_session):
        contract_id = _contract(db_session)
        _request(client, 'data-contracts', contract_id)
        _act_as('steward')
        denied = client.post(
            f'/api/data-contracts/{contract_id}/handle-status-change',
            json={'decision': 'deny', 'target_status': 'deprecated',
                  'requester_email': 'test@example.com'},
        )
        assert denied.status_code == 200, denied.text

        _assert_approval_refused(_decide(client, 'data-contracts', contract_id),
                                 'no_pending_request')


def _request_contract_deprecation(client: TestClient, contract_id: str) -> None:
    requested = client.post(
        f'/api/data-contracts/{contract_id}/request-status-change',
        json={'target_status': 'deprecated',
              'justification': 'Replaced by the v2 contract, consumers moved'},
    )
    assert requested.status_code == 200, requested.text


def _admin_requests(db: Session, contract_id: str):
    """The admins' notifications of a contract's status change requests."""
    db.expire_all()
    notes = db.query(NotificationDb).filter(
        NotificationDb.action_type == 'handle_status_change_request',
    ).all()
    return [n for n in notes if json.loads(n.action_payload)['contract_id'] == contract_id]


class TestContractRequestNotification:
    """The admins' notification is what the UI decides a contract's request from."""

    def test_the_admin_notification_carries_the_decision_action(self, client, db_session):
        contract_id = _contract(db_session)

        _request_contract_deprecation(client, contract_id)

        notes = _admin_requests(db_session, contract_id)
        assert len(notes) == 1
        note = notes[0]
        assert note.recipient == 'Admin' and note.read is False
        assert note.recipient_role_id
        assert json.loads(note.action_payload) == {
            'contract_id': contract_id,
            'contract_name': f'Contract {contract_id[:8]}',
            'requester_email': 'test@example.com',
            'from_status': 'active',
            'target_status': 'deprecated',
            'justification': 'Replaced by the v2 contract, consumers moved',
        }
        i18n = json.loads(note.data)['i18n']
        assert i18n['title'] == 'notifications:contractStatusChangeRequest.title'
        assert i18n['description'] == 'notifications:contractStatusChangeRequest.description'
        assert i18n['statusNamespace'] == 'data-contracts'
        assert i18n['params']['fromStatus'] == 'active'
        assert i18n['params']['toStatus'] == 'deprecated'

    def test_approving_marks_it_handled_and_a_second_approval_is_coded(
        self, client, db_session,
    ):
        contract_id = _contract(db_session)
        _request_contract_deprecation(client, contract_id)
        body = {'decision': 'approve', 'target_status': 'deprecated',
                'requester_email': 'test@example.com'}
        _act_as('steward')

        approved = client.post(f'/api/data-contracts/{contract_id}/handle-status-change', json=body)

        assert approved.status_code == 200, approved.text
        assert _status(db_session, DataContractDb, contract_id) == 'deprecated'
        notes = _admin_requests(db_session, contract_id)
        assert [n.read for n in notes] == [True]
        # Decided, not only read: the bell opens it read-only
        payload = json.loads(notes[0].action_payload)
        assert payload['handled'] is True and payload['decision'] == 'approve'

        again = client.post(f'/api/data-contracts/{contract_id}/handle-status-change', json=body)

        assert again.status_code == 409, again.text
        detail = again.json()['detail']
        assert detail['code'] == 'invalid_status_transition'
        assert detail['params'] == {'fromStatus': 'deprecated', 'toStatus': 'deprecated'}

    def test_an_admin_role_member_outside_an_admins_group_sees_the_request(
        self, client, db_session,
    ):
        # The Admin role's groups are the test settings' APP_ADMIN_DEFAULT_GROUPS
        # (test_admins): no group is called "admins"
        contract_id = _contract(db_session)
        _request_contract_deprecation(client, contract_id)
        _act_as('steward', groups=['test_admins'])

        listed = client.get('/api/notifications')

        assert listed.status_code == 200, listed.text
        items = listed.json()
        items = items if isinstance(items, list) else items.get('items', [])
        assert any(
            n.get('action_type') == 'handle_status_change_request'
            and (n.get('action_payload') or {}).get('contract_id') == contract_id
            for n in items
        ), items

    def test_a_user_without_the_admin_role_does_not_see_it(self, client, db_session):
        contract_id = _contract(db_session)
        _request_contract_deprecation(client, contract_id)
        _act_as('reader', groups=['readers'])

        listed = client.get('/api/notifications')

        items = listed.json() if listed.status_code == 200 else []
        items = items if isinstance(items, list) else items.get('items', [])
        assert not any(
            (n.get('action_payload') or {}).get('contract_id') == contract_id for n in items
        )


class TestSwitchedOff:
    def _switch_off(self, client: TestClient, **disabled_for):
        body = {'domains': [], 'data_products': [], 'data_contracts': [], **disabled_for}
        response = client.put('/api/certified-deprecation-guard', json=body)
        assert response.status_code == 200, response.text
        assert client.get('/api/certified-deprecation-guard').json() == body

    def test_a_switched_off_domain_deprecates_directly_and_the_skip_is_audited(
        self, client, db_session,
    ):
        sales, finance = _domain(db_session, 'Sales'), _domain(db_session, 'Finance')
        exempt = _product(db_session, domain_id=sales)
        guarded = _product(db_session, domain_id=finance)
        self._switch_off(client, domains=[sales])

        assert _deprecate_product(client, exempt).status_code == 200
        _assert_refused(_deprecate_product(client, guarded), 'data_product', guarded)

        assert _status(db_session, DataProductDb, exempt) == 'deprecated'
        assert _status(db_session, DataProductDb, guarded) == 'active'
        skips = _guard_skips(db_session, exempt)
        assert len(skips) == 1
        assert skips[0]['guard'] == 'certified_deprecation'
        assert skips[0]['disabled_for'] == {'kind': 'domain', 'id': sales}
        assert skips[0]['from_status'] == 'active' and skips[0]['to_status'] == 'deprecated'
        assert _guard_skips(db_session, guarded) == []

    def test_a_switched_off_contract_domain_deprecates_directly(self, client, db_session):
        sales, finance = _domain(db_session, 'Sales'), _domain(db_session, 'Finance')
        exempt = _contract(db_session, domain_id=sales)
        guarded = _contract(db_session, domain_id=finance)
        self._switch_off(client, domains=[sales])

        assert _deprecate_contract(client, exempt).status_code == 200
        assert _status(db_session, DataContractDb, exempt) == 'deprecated'
        assert _guard_skips(db_session, exempt)[0]['disabled_for'] == {
            'kind': 'domain', 'id': sales,
        }

        _assert_refused(_deprecate_contract(client, guarded), 'data_contract', guarded)

    def test_a_switched_off_product_deprecates_directly(self, client, db_session):
        exempt, guarded = _product(db_session), _product(db_session)
        self._switch_off(client, data_products=[exempt])

        assert _deprecate_product(client, exempt).status_code == 200
        _assert_refused(_deprecate_product(client, guarded), 'data_product', guarded)
        assert _guard_skips(db_session, exempt)[0]['disabled_for'] == {
            'kind': 'data_product', 'id': exempt,
        }

    def test_the_switch_needs_admin_on_certification_levels(self, client, db_session):
        role = client.post('/api/settings/roles', json={
            'name': f'Cert editor {uuid.uuid4().hex[:6]}', 'description': 'test',
            'assigned_groups': ['cert_editors'],
            'feature_permissions': {'settings-certification-levels': 'Read/Write'},
        })
        assert role.status_code == 201, role.text
        _act_as('editor', groups=['cert_editors'])
        body = {'domains': [], 'data_products': [], 'data_contracts': []}

        assert client.get('/api/certified-deprecation-guard').status_code == 200
        assert client.put('/api/certified-deprecation-guard', json=body).status_code == 403

    def test_an_unknown_entity_is_refused_with_a_code(self, client, db_session):
        response = client.put(
            '/api/certified-deprecation-guard',
            json={'domains': ['no-such-domain'], 'data_products': [], 'data_contracts': []},
        )

        assert response.status_code == 400, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'gate_exemption_not_found'
        assert detail['params'] == {'kind': 'domain', 'id': 'no-such-domain'}
