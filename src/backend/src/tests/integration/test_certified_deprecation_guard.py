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

from src.controller.workflows_manager import WorkflowsManager
from src.db_models.audit_log import AuditLogDb
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_domains import DataDomain
from src.db_models.data_products import DataProductDb
from src.db_models.domain_associations import EntityDomainAssociationDb
from src.db_models.notifications import NotificationDb

CODE = 'certified_deprecation_requires_approval'


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
    assert response.status_code in (400, 409), response.text
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


class TestApprovedRequest:
    def test_an_approved_product_request_deprecates_it(self, client, db_session):
        WorkflowsManager(db=db_session).load_from_yaml()
        product_id = _product(db_session)

        requested = client.post(
            f'/api/data-products/{product_id}/request-status-change',
            json={'target_status': 'deprecated',
                  'justification': 'Replaced by the v2 product, consumers moved'},
        )
        assert requested.status_code == 200, requested.text
        execution_id = requested.json().get('execution_id')
        assert execution_id, requested.json()
        assert _status(db_session, DataProductDb, product_id) == 'active'

        approved = client.post(
            '/api/workflows/handle-approval',
            json={'execution_id': execution_id, 'approved': True, 'message': 'OK'},
        )

        assert approved.status_code == 200, approved.text
        assert _status(db_session, DataProductDb, product_id) == 'deprecated'

    def test_an_admin_approving_a_contract_request_deprecates_it(self, client, db_session):
        contract_id = _contract(db_session)
        requested = client.post(
            f'/api/data-contracts/{contract_id}/request-status-change',
            json={'target_status': 'deprecated',
                  'justification': 'Replaced by the v2 contract, consumers moved'},
        )
        assert requested.status_code == 200, requested.text
        assert _status(db_session, DataContractDb, contract_id) == 'active'

        approved = client.post(
            f'/api/data-contracts/{contract_id}/handle-status-change',
            json={'decision': 'approve', 'target_status': 'deprecated',
                  'requester_email': 'test@example.com'},
        )

        assert approved.status_code == 200, approved.text
        assert _status(db_session, DataContractDb, contract_id) == 'deprecated'

    def test_an_admin_approving_a_product_request_deprecates_it(self, client, db_session):
        product_id = _product(db_session)

        approved = client.post(
            f'/api/data-products/{product_id}/handle-status-change',
            json={'decision': 'approve', 'target_status': 'deprecated',
                  'requester_email': 'test@example.com'},
        )

        assert approved.status_code == 200, approved.text
        assert _status(db_session, DataProductDb, product_id) == 'deprecated'


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
        assert note.recipient == 'admins' and note.read is False
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

        approved = client.post(f'/api/data-contracts/{contract_id}/handle-status-change', json=body)

        assert approved.status_code == 200, approved.text
        assert _status(db_session, DataContractDb, contract_id) == 'deprecated'
        assert [n.read for n in _admin_requests(db_session, contract_id)] == [True]

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

    def test_an_unknown_entity_is_refused_with_a_code(self, client, db_session):
        response = client.put(
            '/api/certified-deprecation-guard',
            json={'domains': ['no-such-domain'], 'data_products': [], 'data_contracts': []},
        )

        assert response.status_code == 400, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'gate_exemption_not_found'
        assert detail['params'] == {'kind': 'domain', 'id': 'no-such-domain'}
