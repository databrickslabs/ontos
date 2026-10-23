"""Expected refusals keep their message and code in tool results (#1143 follow-up).

#1143 made ``tool_failure`` answer every exception with a generic message and
an error id, so the text of SQL errors and paths stays in the server log. A
``CodedValueError`` is different: it is a refusal whose message is written for
the user (an invalid status transition, a change blocked by a workflow), so the
MCP client and the chat LLM get it as ``Type: message`` with its code, as they
did before #1143. A product's disallowed status transition is now such an
error, with the same message, and is still a ``ValueError`` for the routes.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import asyncio
import json
import logging
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from src.common.api_errors import (
    CodedValueError,
    InvalidStatusTransitionError,
    coded_http_exception_handler,
)
from src.common.workflow_triggers import StatusChangeBlockedError
from src.controller.data_products_manager import DataProductsManager
from src.db_models.data_products import DataProductDb
from src.models.data_products import ChangeStatusPayload
from src.models.lifecycle import DATA_PRODUCT_TRANSITIONS
from src.routes import data_product_routes
from src.tests.unit.test_tool_error_text import SECRET, _assert_generic
from src.tools.base import TOOL_FAILED_CODE, ToolContext, tool_failure
from src.tools.domains import GetDomainTool

USER = SimpleNamespace(email='sue@example.com', username='sue')


class _Refusal(CodedValueError):
    code = 'some_refusal'


@pytest.fixture
def product_manager(db_session):
    mgr = DataProductsManager(
        db=db_session, ws_client=MagicMock(),
        notifications_manager=MagicMock(), tags_manager=MagicMock(),
    )
    mgr._update_search_index = lambda *a, **k: None
    mgr._queue_delivery = lambda *a, **k: None
    return mgr


def _product(db_session, status):
    pid = str(uuid.uuid4())
    db_session.add(DataProductDb(
        id=pid, name=f'Product {pid[:8]}', version='1.0.0', status=status,
        api_version='v1.0.0', kind='DataProduct',
    ))
    db_session.commit()
    return pid


def _invalid_message(from_status, to_status):
    allowed = DATA_PRODUCT_TRANSITIONS.get(from_status, [])
    return (
        f"Invalid status transition from '{from_status}' to '{to_status}'. "
        f"Allowed transitions: {', '.join(allowed) if allowed else 'none'}"
    )


class TestToolFailure:
    def test_a_coded_refusal_keeps_its_type_message_and_code(self, caplog):
        with caplog.at_level(logging.INFO):
            out = tool_failure('some_tool', _Refusal('The product is retired'))

        assert out == {'error': '_Refusal: The product is retired', 'error_code': 'some_refusal'}
        assert 'error id' not in out['error']
        refused = [r for r in caplog.records if 'refused' in r.getMessage()]
        assert [r.levelno for r in refused] == [logging.INFO]
        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]

    def test_a_coded_refusal_without_a_code_gets_the_tool_code(self):
        out = tool_failure('some_tool', CodedValueError('Name is required'))

        assert out == {'error': 'CodedValueError: Name is required', 'error_code': TOOL_FAILED_CODE}

    def test_a_blocked_status_change_has_its_code(self):
        error = StatusChangeBlockedError('approved', 'active', [])

        out = tool_failure('update_data_contract', error)

        assert out['error_code'] == 'status_change_blocked'
        assert out['error'] == f'StatusChangeBlockedError: {error}'

    def test_an_invalid_transition_has_its_code(self):
        out = tool_failure('update_data_product', InvalidStatusTransitionError('Not allowed'))

        assert out == {
            'error': 'InvalidStatusTransitionError: Not allowed',
            'error_code': 'invalid_status_transition',
        }

    @pytest.mark.parametrize('error', [ValueError(SECRET), RuntimeError(SECRET)])
    def test_any_other_error_stays_generic(self, error, caplog):
        with caplog.at_level(logging.ERROR):
            out = tool_failure('some_tool', error)

        assert out['error_code'] == TOOL_FAILED_CODE
        _assert_generic(out['error'])
        assert SECRET in caplog.text

    def test_a_tool_returns_the_refusal(self):
        ctx = ToolContext(db=MagicMock(), settings=MagicMock())
        ctx.db.query.side_effect = StatusChangeBlockedError('approved', 'active', [])

        res = asyncio.run(GetDomainTool().execute(ctx, domain_id='d-1'))

        assert not res.success
        assert res.error_code == 'status_change_blocked'
        assert res.error.startswith(
            "StatusChangeBlockedError: Status transition from 'approved' to 'active' blocked")


class TestProductTransition:
    def test_a_disallowed_transition_is_an_invalid_transition_error(
            self, product_manager, db_session):
        pid = _product(db_session, 'retired')

        with pytest.raises(InvalidStatusTransitionError) as raised:
            product_manager.transition_status(pid, 'active', 'sue')

        assert isinstance(raised.value, ValueError)
        assert raised.value.code == 'invalid_status_transition'
        assert str(raised.value) == _invalid_message('retired', 'active')
        assert raised.value.params == {
            'fromStatus': 'retired', 'toStatus': 'active',
            'allowed': list(DATA_PRODUCT_TRANSITIONS.get('retired', [])),
        }
        assert db_session.get(DataProductDb, pid).status == 'retired'

    def test_a_missing_product_is_still_a_plain_value_error(self, product_manager):
        with pytest.raises(ValueError) as raised:
            product_manager.transition_status('nope', 'active', 'sue')

        assert not isinstance(raised.value, CodedValueError)


def _answer(coro):
    """The status and JSON the app sends for the route's error."""
    with pytest.raises(HTTPException) as raised:
        asyncio.run(coro)
    response = asyncio.run(coded_http_exception_handler(MagicMock(), raised.value))
    return response.status_code, json.loads(response.body)


class TestProductStatusRoutes:
    """The routes answer an invalid transition with the status and message they always did."""

    def test_change_status_answers_400_with_the_message(self, product_manager, db_session):
        pid = _product(db_session, 'retired')

        status_code, body = _answer(data_product_routes.change_product_status(
            product_id=pid, request=MagicMock(), db=db_session, audit_manager=MagicMock(),
            current_user=USER, payload=ChangeStatusPayload(new_status='active'),
            manager=product_manager, _=True,
        ))

        assert status_code == 400
        assert body['detail']['message'] == _invalid_message('retired', 'active')
        assert body['detail']['code'] == 'invalid_status_transition'
        assert body['detail']['params']['fromStatus'] == 'retired'

    def test_submit_for_review_answers_409_with_the_message(self, product_manager, db_session):
        pid = _product(db_session, 'active')

        status_code, body = _answer(data_product_routes.submit_product_for_review(
            product_id=pid, request=MagicMock(), db=db_session, audit_manager=MagicMock(),
            current_user=USER, manager=product_manager, _=True,
        ))

        assert status_code == 409
        assert body['detail']['message'] == _invalid_message('active', 'proposed')
        assert body['detail']['code'] == 'invalid_status_transition'
