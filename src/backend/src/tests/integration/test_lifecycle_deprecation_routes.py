"""The HTTP status of a deprecation the details don't allow (#1042).

A missing reason, a past sunset date or an unusable replacement is a
``LifecycleFieldError``: every route that deprecates, requests a deprecation
or approves one answers it with 400 and its code, never with the 404 of a
missing entity (``Replacement ... not found``) nor the 409 of a state conflict.

Through the routes, on the test database, with the app's managers. A refused
contract request can roll back the test's transaction (the route's session is
bound to it), so the tests only check the answer after a refusal.
"""
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.controller.change_log_manager import change_log_manager
from src.controller.lifecycle_fields import utc_today
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb

REASON = 'Replaced by the v2 version, consumers moved'
MISSING = 'no-such-entity'
KINDS = [('data-products', 'data_product'), ('data-contracts', 'data_contract')]


def _product(db: Session) -> str:
    product_id = str(uuid.uuid4())
    db.add(DataProductDb(
        id=product_id, name=f'Product {product_id[:8]}', version='1.0.0', status='active',
        api_version='v1.0.0', kind='DataProduct',
    ))
    db.commit()
    return product_id


def _contract(db: Session) -> str:
    contract_id = str(uuid.uuid4())
    db.add(DataContractDb(
        id=contract_id, name=f'Contract {contract_id[:8]}', version='1.0.0', status='active',
    ))
    db.commit()
    return contract_id


def _entity(db: Session, kind: str) -> str:
    return _product(db) if kind == 'data-products' else _contract(db)


def _assert_code(response, code: str) -> None:
    assert response.status_code == 400, response.text
    assert response.json()['detail']['code'] == code


class TestDeprecateRoute:
    def test_a_bodyless_deprecate_needs_a_reason(self, client: TestClient, db_session):
        product_id = _product(db_session)

        response = client.post(f'/api/data-products/{product_id}/deprecate')

        _assert_code(response, 'deprecation_reason_required')

    @pytest.mark.parametrize('body, code', [
        ({'sunset_date': (utc_today() - timedelta(days=1)).isoformat()}, 'sunset_date_in_past'),
        ({'replacement_id': MISSING}, 'replacement_not_found'),
    ])
    def test_invalid_details_are_answered_with_400(self, client, db_session, body, code):
        product_id = _product(db_session)

        response = client.post(
            f'/api/data-products/{product_id}/deprecate',
            json={'deprecation_reason': REASON, **body},
        )

        _assert_code(response, code)

    def test_a_valid_deprecation_still_succeeds(self, client, db_session):
        product_id = _product(db_session)

        response = client.post(
            f'/api/data-products/{product_id}/deprecate', json={'deprecation_reason': REASON},
        )

        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'deprecated'


class TestRequestRoutes:
    @pytest.mark.parametrize('kind, entity_type', KINDS)
    def test_a_missing_replacement_is_a_400_not_a_404(
        self, client, db_session, kind, entity_type,
    ):
        entity_id = _entity(db_session, kind)

        response = client.post(
            f'/api/{kind}/{entity_id}/request-status-change',
            json={'target_status': 'deprecated', 'justification': REASON,
                  'replacement_id': MISSING},
        )

        _assert_code(response, 'replacement_not_found')
        assert response.json()['detail']['params'] == {'replacementId': MISSING}

    @pytest.mark.parametrize('kind', ['data-products', 'data-contracts'])
    def test_a_past_sunset_date_is_a_400(self, client, db_session, kind):
        entity_id = _entity(db_session, kind)

        response = client.post(
            f'/api/{kind}/{entity_id}/request-status-change',
            json={'target_status': 'deprecated', 'justification': REASON,
                  'sunset_date': (utc_today() - timedelta(days=1)).isoformat()},
        )

        _assert_code(response, 'sunset_date_in_past')

    @pytest.mark.parametrize('kind', ['data-products', 'data-contracts'])
    def test_a_missing_entity_is_still_a_404(self, client, kind):
        response = client.post(
            f'/api/{kind}/{uuid.uuid4()}/request-status-change',
            json={'target_status': 'deprecated', 'justification': REASON},
        )

        assert response.status_code == 404, response.text


class TestHandleRoutes:
    @pytest.mark.parametrize('kind, entity_type', KINDS)
    def test_approving_a_request_whose_replacement_is_gone_is_a_400(
        self, client, db_session, kind, entity_type,
    ):
        # The replacement existed when the request was made; it is gone now
        entity_id = _entity(db_session, kind)
        change_log_manager.log_change_with_details(
            db_session, entity_type=entity_type, entity_id=entity_id,
            action='status_change_requested', username='requester@example.com',
            details={'requester_email': 'requester@example.com', 'request_id': 'req-1',
                     'from_status': 'active', 'current_status': 'active',
                     'target_status': 'deprecated', 'justification': REASON,
                     'replacement_id': MISSING},
        )

        response = client.post(
            f'/api/{kind}/{entity_id}/handle-status-change',
            json={'decision': 'approve', 'target_status': 'deprecated',
                  'requester_email': 'requester@example.com'},
        )

        _assert_code(response, 'replacement_not_found')
