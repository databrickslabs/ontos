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
from src.controller.certified_deprecation_guard import request_is_closed
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


def _request_contract_deprecation(client: TestClient, contract_id: str) -> dict:
    requested = client.post(
        f'/api/data-contracts/{contract_id}/request-status-change',
        json={'target_status': 'deprecated',
              'justification': 'Replaced by the v2 contract, consumers moved'},
    )
    assert requested.status_code == 200, requested.text
    return requested.json()


def _approvals(db: Session, contract_id: str):
    """The workflow approval notifications of a contract's request."""
    db.expire_all()
    notes = db.query(NotificationDb).filter(
        NotificationDb.action_type == 'workflow_approval',
    ).all()
    return [n for n in notes if json.loads(n.action_payload).get('entity_id') == contract_id]


def _handle_approval(client: TestClient, execution_id: str, approved: bool = True):
    return client.post(
        '/api/workflows/handle-approval',
        json={'execution_id': execution_id, 'approved': approved, 'message': 'Decided'},
    )


def _requester_notices(db: Session, contract_id: str):
    db.expire_all()
    return [
        n for n in db.query(NotificationDb).filter(
            NotificationDb.recipient == 'test@example.com',
        ).all()
        if (n.subtitle or '').endswith(f'Contract {contract_id[:8]}')
    ]


class TestContractRequestWorkflow:
    """A contract's status change request goes through the Status Change Request workflow.

    One mechanism for products and contracts (#1120).
    """

    def test_the_request_starts_the_workflow_and_asks_the_admin_role(self, client, db_session):
        WorkflowsManager(db=db_session).load_from_yaml()
        contract_id = _contract(db_session)

        response = _request_contract_deprecation(client, contract_id)

        assert response['execution_id'] and response['request_id']
        assert response['workflow_status'] == 'paused'
        approvals = _approvals(db_session, contract_id)
        assert len(approvals) == 1
        assert approvals[0].recipient == 'Admin' and approvals[0].recipient_role_id
        payload = json.loads(approvals[0].action_payload)
        assert payload['execution_id'] == response['execution_id']
        assert payload['entity_type'] == 'data_contract'
        assert payload['requester_email'] == 'test@example.com'
        # The contract-specific notifications are gone
        db_session.expire_all()
        assert db_session.query(NotificationDb).filter(
            NotificationDb.action_type == 'handle_status_change_request',
        ).count() == 0
        # The requester's confirmation comes from the workflow, translated
        notices = _requester_notices(db_session, contract_id)
        assert [json.loads(n.data)['i18n']['description'] for n in notices] == [
            'notifications:workflowDefaults.messages.status-change-request.notify-requester',
        ]

    @pytest.mark.parametrize('certified', [True, False])
    def test_an_approval_at_the_workflow_step_deprecates_the_contract(
        self, client, db_session, certified,
    ):
        WorkflowsManager(db=db_session).load_from_yaml()
        contract_id = _contract(db_session, certified=certified)
        response = _request_contract_deprecation(client, contract_id)
        execution_id, request_id = response['execution_id'], response['request_id']
        assert _status(db_session, DataContractDb, contract_id) == 'active'

        _act_as('steward')
        approved = _handle_approval(client, execution_id)

        assert approved.status_code == 200, approved.text
        assert _status(db_session, DataContractDb, contract_id) == 'deprecated'
        # The transition closed the request
        assert request_is_closed(db_session, 'data_contract', contract_id, request_id)

    def test_a_rejection_keeps_the_status_and_ends_the_request(self, client, db_session):
        WorkflowsManager(db=db_session).load_from_yaml()
        contract_id = _contract(db_session)
        execution_id = _request_contract_deprecation(client, contract_id)['execution_id']

        _act_as('steward')
        rejected = _handle_approval(client, execution_id, approved=False)

        assert rejected.status_code == 200, rejected.text
        assert _status(db_session, DataContractDb, contract_id) == 'active'
        keys = [json.loads(n.data)['i18n'].get('description')
                for n in _requester_notices(db_session, contract_id)]
        assert 'notifications:workflowDefaults.messages.status-change-request.notify-rejected' \
            in keys
        _act_as('second_admin')
        _assert_approval_refused(_decide(client, 'data-contracts', contract_id),
                                 'no_pending_request')

    def test_a_clarification_through_the_api_keeps_the_request_open(self, client, db_session):
        WorkflowsManager(db=db_session).load_from_yaml()
        contract_id = _contract(db_session)
        execution_id = _request_contract_deprecation(client, contract_id)['execution_id']
        _act_as('steward')
        clarify = client.post(
            f'/api/data-contracts/{contract_id}/handle-status-change',
            json={'decision': 'clarify', 'target_status': 'deprecated',
                  'requester_email': 'test@example.com', 'message': 'Which consumers?'},
        )
        assert clarify.status_code == 200, clarify.text
        assert _status(db_session, DataContractDb, contract_id) == 'active'

        approved = _handle_approval(client, execution_id)

        assert approved.status_code == 200, approved.text
        assert _status(db_session, DataContractDb, contract_id) == 'deprecated'

    def test_a_request_whose_contract_moved_meanwhile_is_not_applied(self, client, db_session):
        contract_id = _contract(db_session, certified=False)
        db_session.get(DataContractDb, contract_id).status = 'approved'
        db_session.commit()
        WorkflowsManager(db=db_session).load_from_yaml()
        execution_id = _request_contract_deprecation(client, contract_id)['execution_id']
        _change(client, 'data-contracts', contract_id, 'active')

        _act_as('steward')
        approved = _handle_approval(client, execution_id)

        assert approved.status_code == 200, approved.text
        assert _status(db_session, DataContractDb, contract_id) == 'active'
        db_session.expire_all()
        warned = db_session.query(NotificationDb).filter(
            NotificationDb.title == 'Status change not applied',
        ).all()
        warned = [n for n in warned if n.subtitle == f'Contract {contract_id[:8]}']
        assert sorted(n.recipient for n in warned) == ['steward@example.com', 'test@example.com']
        i18n = json.loads(warned[0].data)['i18n']
        assert i18n['description'] == 'notifications:statusChangeNotApplied.statusChanged'
        assert i18n['statusNamespace'] == 'data-contracts'
        assert i18n['params'] == {
            'fromStatus': 'approved', 'toStatus': 'deprecated', 'currentStatus': 'active',
        }

    def test_a_workflow_approval_after_an_api_decision_applies_nothing(self, client, db_session):
        WorkflowsManager(db=db_session).load_from_yaml()
        contract_id = _contract(db_session)
        execution_id = _request_contract_deprecation(client, contract_id)['execution_id']
        _act_as('steward')
        assert _decide(client, 'data-contracts', contract_id).status_code == 200
        _change(client, 'data-contracts', contract_id, 'active')

        approved = _handle_approval(client, execution_id)

        assert approved.status_code == 200, approved.text
        assert _status(db_session, DataContractDb, contract_id) == 'active'

    def test_the_requester_approving_their_own_request_does_not_count(self, client, db_session):
        WorkflowsManager(db=db_session).load_from_yaml()
        contract_id = _contract(db_session)
        execution_id = _request_contract_deprecation(client, contract_id)['execution_id']

        approved = _handle_approval(client, execution_id)

        assert approved.status_code == 200, approved.text
        assert _status(db_session, DataContractDb, contract_id) == 'active'
        db_session.expire_all()
        refused = [
            n for n in db_session.query(NotificationDb).filter(
                NotificationDb.title == 'Status change not applied',
            ).all()
            if n.subtitle == f'Contract {contract_id[:8]}'
        ]
        assert len(refused) == 1
        i18n = json.loads(refused[0].data)['i18n']
        assert i18n['description'] == 'notifications:statusChangeNotApplied.refused'
        assert i18n['error']['code'] == REFUSED
        assert i18n['error']['params']['reason'] == 'self_approval'

    def test_a_domain_scoped_copy_asks_the_domain_owner(self, client, db_session):
        from src.db_models.business_owners import BusinessOwnerDb
        from src.db_models.business_roles import BusinessRoleDb
        from src.models.process_workflows import (
            ProcessWorkflowCreate, ScopeType, StepType, TriggerType, WorkflowScope,
            WorkflowStepCreate, WorkflowTrigger, EntityType,
        )
        from src.repositories.process_workflows_repository import process_workflow_repo

        manager = WorkflowsManager(db=db_session)
        manager.load_from_yaml()
        default = process_workflow_repo.get_by_name(db_session, 'Status Change Request')
        process_workflow_repo.toggle_active(db_session, default.id, False)
        sales = _domain(db_session, 'Sales')
        contract_id = _contract(db_session, domain_id=sales)
        role = BusinessRoleDb(id=uuid.uuid4(), name=f'Owner {uuid.uuid4().hex[:6]}')
        db_session.add(role)
        db_session.flush()
        db_session.add(BusinessOwnerDb(
            id=uuid.uuid4(), object_type='data_domain', object_id=sales,
            user_email='owner@example.com', role_id=role.id, is_active=True,
        ))
        db_session.commit()
        manager.create_workflow(ProcessWorkflowCreate(
            name='Sales Status Change Request',
            trigger=WorkflowTrigger(
                type=TriggerType.ON_REQUEST_STATUS_CHANGE,
                entity_types=[EntityType.DATA_CONTRACT],
            ),
            scope=WorkflowScope(type=ScopeType.DOMAIN, ids=[sales]),
            is_active=True,
            steps=[
                WorkflowStepCreate(
                    step_id='request-approval', name='Domain owner approval',
                    step_type=StepType.APPROVAL,
                    config={'approvers': 'DomainOwner', 'timeout_days': 5},
                    on_pass='success', on_fail='fail-rejected', order=0,
                ),
                WorkflowStepCreate(step_id='success', name='Approved',
                                   step_type=StepType.PASS, order=1),
                WorkflowStepCreate(step_id='fail-rejected', name='Rejected',
                                   step_type=StepType.FAIL, order=2),
            ],
        ))

        execution_id = _request_contract_deprecation(client, contract_id)['execution_id']

        assert [n.recipient for n in _approvals(db_session, contract_id)] == [
            'owner@example.com',
        ]
        # Not an admin: the owner decides it as the step's approver
        _act_as('owner', groups=['owners'])
        approved = _handle_approval(client, execution_id)
        assert approved.status_code == 200, approved.text
        assert _status(db_session, DataContractDb, contract_id) == 'deprecated'


class TestContractHandleStatusChange:
    """``handle-status-change`` stays for API clients."""

    def test_a_second_approval_is_coded(self, client, db_session):
        contract_id = _contract(db_session)
        _request_contract_deprecation(client, contract_id)
        body = {'decision': 'approve', 'target_status': 'deprecated',
                'requester_email': 'test@example.com'}
        _act_as('steward')

        approved = client.post(f'/api/data-contracts/{contract_id}/handle-status-change', json=body)

        assert approved.status_code == 200, approved.text
        assert _status(db_session, DataContractDb, contract_id) == 'deprecated'

        again = client.post(f'/api/data-contracts/{contract_id}/handle-status-change', json=body)

        assert again.status_code == 409, again.text
        detail = again.json()['detail']
        assert detail['code'] == 'invalid_status_transition'
        assert detail['params'] == {'fromStatus': 'deprecated', 'toStatus': 'deprecated'}


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
