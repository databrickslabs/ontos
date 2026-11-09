"""A failed chat turn never shows or stores the exception's text.

The assistant message of a failed turn is returned to the user and stored in
the chat session, so it carries a code, an error id and a generic English text;
the exception's text goes to the server log under the same error id.
"""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import openai
import pytest
from pydantic import BaseModel, ValidationError

from src.controller.llm_search_manager import (
    CHAT_ERROR_MESSAGES,
    LLMSearchManager,
    chat_error_code,
)
from src.tools.base import BaseTool, ToolResult
from src.tools.registry import ToolRegistry

SECRET = "SELECT ssn FROM main.hr.salaries WHERE token='dapi-secret'"


class _Strict(BaseModel):
    count: int


def _validation_error() -> ValidationError:
    try:
        _Strict(count=SECRET)
    except ValidationError as e:
        return e
    raise AssertionError("expected a ValidationError")


def _manager(db_session) -> LLMSearchManager:
    settings = SimpleNamespace(LLM_ENABLED=True)
    return LLMSearchManager(db=db_session, settings=settings)


def _stored_contents(manager, session_id):
    session = manager._session_store.get(manager._db, session_id)
    return [m.content or "" for m in session.messages]


@pytest.mark.parametrize(
    "exc, code",
    [
        (_validation_error(), "chat_validation_failed"),
        (TimeoutError(SECRET), "chat_timeout"),
        (asyncio.TimeoutError(), "chat_timeout"),
        (httpx.ReadTimeout(SECRET), "chat_timeout"),
        (ConnectionError(SECRET), "chat_connection_failed"),
        (httpx.ConnectError(SECRET), "chat_connection_failed"),
        (openai.APIConnectionError(request=httpx.Request("POST", "http://llm")), "chat_connection_failed"),
        (openai.APITimeoutError(request=httpx.Request("POST", "http://llm")), "chat_timeout"),
        (RuntimeError(SECRET), "chat_failed"),
        (RuntimeError("upstream: Connection reset by peer"), "chat_connection_failed"),
    ],
)
def test_the_code_comes_from_the_exception_type(exc, code):
    assert chat_error_code(exc) == code


@pytest.mark.asyncio
async def test_a_validation_error_doesnt_reach_the_user_or_the_session(db_session, caplog):
    manager = _manager(db_session)
    with patch.object(
        manager, "_process_with_llm", AsyncMock(side_effect=_validation_error())
    ), caplog.at_level(logging.ERROR):
        response = await manager.chat("how many people earn more than me?", user_id="u@example.com")

    message = response.message
    assert message.error_code == "chat_validation_failed"
    error_id = message.error_params["errorId"]
    assert message.content == CHAT_ERROR_MESSAGES["chat_validation_failed"].format(errorId=error_id)
    assert SECRET not in message.content
    assert "count" not in message.content  # the pydantic field and its error stay in the log

    stored = _stored_contents(manager, response.session_id)
    assert stored[-1] == message.content
    assert all(SECRET not in text for text in stored)

    logged = "\n".join(r.getMessage() + (r.exc_text or "") for r in caplog.records)
    assert error_id in logged
    assert "ValidationError" in logged


@pytest.mark.asyncio
async def test_any_other_error_gets_a_generic_text_with_an_error_id(db_session):
    manager = _manager(db_session)
    with patch.object(manager, "_process_with_llm", AsyncMock(side_effect=RuntimeError(SECRET))):
        response = await manager.chat("hi", user_id="u@example.com")

    message = response.message
    assert message.error_code == "chat_failed"
    assert SECRET not in message.content
    assert "RuntimeError" not in message.content
    assert message.error_params["errorId"] in message.content


class _BrokenTool(BaseTool):
    name = "broken_tool"
    description = "Always raises"
    parameters = {}
    required_params = []

    async def execute(self, ctx, **kwargs) -> ToolResult:
        raise RuntimeError(SECRET)


@pytest.mark.asyncio
async def test_a_tool_exception_reaches_neither_the_llm_nor_mcp_clients(caplog):
    registry = ToolRegistry()
    registry.register(_BrokenTool())
    with caplog.at_level(logging.ERROR):
        result = await registry.execute("broken_tool", ctx=None, args={})

    assert result.success is False
    assert SECRET not in result.error
    assert "error id" in result.error
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert SECRET in logged


@pytest.mark.asyncio
async def test_an_error_whose_text_names_a_validation_error_isnt_quoted(db_session):
    # Before: "ValidationError" anywhere in the text added `Details: <text>` to the reply.
    manager = _manager(db_session)
    error = RuntimeError(f"1 validation error for ToolArgs (ValidationError): input {SECRET}")
    with patch.object(manager, "_process_with_llm", AsyncMock(side_effect=error)):
        response = await manager.chat("q", user_id="u@example.com")

    assert SECRET not in response.message.content
    assert "Details" not in response.message.content
    assert all(SECRET not in text for text in _stored_contents(manager, response.session_id))
