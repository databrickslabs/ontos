"""Contract action errors carry a code the UI can translate.

The contract page's Approve / Reject buttons showed only the HTTP status
("Approve failed (409)"). A workflow
gate that blocks the change already answers `status_change_blocked` (#1019);
a contract whose status no longer allows the decision answers
`invalid_status_transition` with its status, and the English message is the
one these routes always sent. Requesting a review of a draft without a schema
answers `review_schema_required`.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from src.common.api_errors import coded_http_exception_handler
from src.common.workflow_triggers import StatusChangeBlockedError
from src.controller.data_contracts_manager import ReviewSchemaRequiredError
from src.routes import data_contracts_routes

CONTRACT = 'c-1'
USER = SimpleNamespace(email='sue@example.com', username='sue')


def _answer(route, *, status, manager=None):
    """The JSON the app sends for an error of the route."""
    with patch.object(data_contracts_routes.data_contract_repo, 'get',
                      return_value=SimpleNamespace(status=status)), \
            patch.object(data_contracts_routes, '_decide_waiting_review_workflows'):
        with pytest.raises(HTTPException) as raised:
            asyncio.run(getattr(data_contracts_routes, route)(
                contract_id=CONTRACT, request=MagicMock(), db=MagicMock(),
                audit_manager=MagicMock(), current_user=USER,
                manager=manager or MagicMock(), _=True,
            ))
    response = asyncio.run(coded_http_exception_handler(MagicMock(), raised.value))
    return response.status_code, json.loads(response.body)


@pytest.mark.parametrize('route, to_status, message', [
    ('approve_contract', 'approved', 'Invalid transition from approved to APPROVED'),
    ('reject_contract', 'draft', 'Invalid transition from approved to DRAFT'),
])
def test_a_status_that_no_longer_allows_the_decision_has_a_code(route, to_status, message):
    status_code, body = _answer(route, status='approved')

    assert status_code == 409
    assert body == {'detail': {
        'code': 'invalid_status_transition',
        'message': message,
        'params': {'fromStatus': 'approved', 'toStatus': to_status},
    }}


def test_the_status_is_sent_in_lower_case():
    _, body = _answer('approve_contract', status='ACTIVE')

    assert body['detail']['params']['fromStatus'] == 'active'
    assert body['detail']['message'] == 'Invalid transition from ACTIVE to APPROVED'


@pytest.mark.parametrize('route, to_status', [
    ('approve_contract', 'approved'), ('reject_contract', 'draft'),
])
def test_a_blocking_gate_is_answered_with_its_reasons(route, to_status):
    manager = MagicMock()
    manager.transition_status.side_effect = StatusChangeBlockedError(
        'proposed', to_status, [],
    )

    status_code, body = _answer(route, status='proposed', manager=manager)

    assert status_code == 409
    assert body['detail']['code'] == 'status_change_blocked'
    assert body['detail']['params']['fromStatus'] == 'proposed'
    assert body['detail']['params']['toStatus'] == to_status


def test_a_review_request_without_a_schema_has_a_code():
    manager = MagicMock()
    manager.request_steward_review.side_effect = ReviewSchemaRequiredError()

    with pytest.raises(HTTPException) as raised:
        asyncio.run(data_contracts_routes.request_steward_review(
            contract_id=CONTRACT, request=MagicMock(), db=MagicMock(),
            audit_manager=MagicMock(), current_user=USER, notifications=MagicMock(),
            payload=data_contracts_routes.RequestReviewPayload(), manager=manager, _=True,
        ))
    response = asyncio.run(coded_http_exception_handler(MagicMock(), raised.value))

    assert response.status_code == 409
    assert json.loads(response.body) == {'detail': {
        'code': 'review_schema_required',
        'message': 'A schema is required before a contract can be proposed for review.',
        'params': {},
    }}
