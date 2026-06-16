"""Integration tests for the Ask Ontos copilot's handbook-grounding path.

These tests exercise ``LLMSearchManager._process_with_llm`` end-to-end
with a fake OpenAI client. Why not hit ``POST /api/llm-search/chat``
through the TestClient? Two reasons:

1. The chat route depends on ``get_obo_workspace_client`` and the audit
   manager pipeline — neither is interesting for verifying that the
   new tool is wired into the registry and that the new prompt is in
   the message stream.
2. Patching at the manager level lets us script the LLM's tool-call
   sequence deterministically (call ``search_ontos_handbook`` -> read
   the result -> emit a final text response). That sequence is what
   we're actually trying to certify.

The fake client returns whatever its ``script`` says next, so a single
test can simulate multiple LLM iterations.
"""

# Set test environment variables BEFORE any app imports
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
from types import SimpleNamespace
from typing import Any, List
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fake OpenAI client
# ---------------------------------------------------------------------------


def _make_tool_call(call_id: str, name: str, arguments: dict) -> SimpleNamespace:
    """Build an object shaped like the OpenAI SDK's tool_call attribute
    tree (id, function.name, function.arguments). The manager only
    reads those four attributes."""
    function = SimpleNamespace(
        name=name,
        arguments=json.dumps(arguments),
    )
    return SimpleNamespace(id=call_id, function=function)


def _make_response(*, content: str | None, tool_calls: List | None) -> SimpleNamespace:
    """Build an object shaped like the OpenAI ``ChatCompletion`` result
    that the manager consumes — only ``choices[0].message.{content,
    tool_calls}`` matter."""
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


class _ScriptedOpenAIClient:
    """Returns scripted responses in order. Records every ``messages=``
    payload it sees so the test can assert against the system prompt
    that was actually sent."""

    def __init__(self, script: List[SimpleNamespace]):
        self._script = list(script)
        self._call_count = 0
        self.captured_messages: List[List[dict]] = []
        # Mirror the OpenAI SDK shape: client.chat.completions.create(...)
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, *, model, messages, tools, tool_choice, max_tokens):
        self.captured_messages.append(messages)
        if not self._script:
            raise AssertionError(
                f"_ScriptedOpenAIClient ran out of scripted responses on "
                f"call #{self._call_count + 1}"
            )
        resp = self._script.pop(0)
        self._call_count += 1
        return resp


# ---------------------------------------------------------------------------
# Manager fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def llm_settings(test_settings):
    """Override the standard test_settings to enable LLM features and
    leave LLM_SYSTEM_PROMPT unset so we exercise the default-prompt
    branch."""
    test_settings.LLM_ENABLED = True
    test_settings.LLM_ENDPOINT = "test-endpoint"
    test_settings.LLM_SYSTEM_PROMPT = None
    return test_settings


@pytest.fixture
def llm_manager(db_session, llm_settings, mock_workspace_client):
    """Build a real LLMSearchManager with mocked downstream managers.

    The integration boundary we care about is:
      manager -> tool registry -> SearchOntosHandbookTool -> filesystem

    Nothing else needs to be real.
    """
    from src.controller.llm_search_manager import LLMSearchManager

    return LLMSearchManager(
        db=db_session,
        settings=llm_settings,
        data_products_manager=MagicMock(),
        data_contracts_manager=MagicMock(),
        semantic_models_manager=MagicMock(),
        costs_manager=MagicMock(),
        search_manager=MagicMock(),
        workspace_client=mock_workspace_client,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_registry_contains_handbook_search_tool(llm_manager):
    """First-line check: the new tool actually got registered. If this
    fails, the rest of the integration is moot."""
    tool_names = llm_manager._tool_registry.list_tool_names()
    assert "search_ontos_handbook" in tool_names


def test_handbook_category_visible_for_conceptual_query():
    """The query classifier must surface the ``handbook`` category for
    a 'what is X' question so the new tool is in the LLM's tool list."""
    from src.tools.query_classifier import classify_query

    cats = classify_query("what is a data steward?")
    assert "handbook" in cats


def test_handbook_category_visible_for_default_path():
    """Vague queries fall back to DEFAULT_CATEGORIES — ``handbook``
    must be in there so the tool is always at least nominally visible."""
    from src.tools.query_classifier import classify_query, DEFAULT_CATEGORIES

    assert "handbook" in DEFAULT_CATEGORIES
    # An empty query takes the default path explicitly.
    cats = classify_query("")
    assert "handbook" in cats


@pytest.mark.asyncio
async def test_chat_calls_handbook_search_tool_for_conceptual_question(
    llm_manager, mock_test_user
):
    """Script the LLM to ask for ``search_ontos_handbook`` and then
    emit a final text answer. Verify that the manager executed the
    tool, the tool returned real corpus matches, and the final answer
    reached the caller."""
    # The full chat() entry point manages session creation + persistence.
    # We script two LLM iterations: first a tool call, then a final reply.
    scripted = [
        _make_response(
            content=None,
            tool_calls=[
                _make_tool_call(
                    call_id="call_1",
                    name="search_ontos_handbook",
                    arguments={"query": "data steward"},
                )
            ],
        ),
        _make_response(
            content=(
                "A Data Steward in Ontos is a built-in role that... "
                "[Documented]\n<!-- ref: roles-and-rbac.md#data-steward -->"
            ),
            tool_calls=None,
        ),
    ]
    fake_client = _ScriptedOpenAIClient(scripted)

    with patch.object(llm_manager, "_get_openai_client", return_value=fake_client):
        response = await llm_manager.chat(
            user_message="What is a Data Steward?",
            user_id=mock_test_user.email,
            debug=True,
        )

    # The manager executed exactly one tool call — our new one.
    assert response.tool_calls_executed == 1
    assert response.sources, "expected at least one source recorded"
    assert response.sources[0]["tool"] == "search_ontos_handbook"
    assert response.sources[0]["success"] is True

    # The final answer reached us verbatim.
    assert response.message.content.startswith("A Data Steward in Ontos")

    # Debug payload records the new tool was offered.
    assert response.debug is not None
    assert "search_ontos_handbook" in response.debug["query_classification"]["tools_provided"]


@pytest.mark.asyncio
async def test_chat_sends_grounded_system_prompt(llm_manager, mock_test_user):
    """The first message sent to the LLM must be a system message
    containing the new tool-first policy. If the prompt source
    regresses to the old constant, this fails."""
    scripted = [
        _make_response(content="Brief answer.", tool_calls=None),
    ]
    fake_client = _ScriptedOpenAIClient(scripted)

    with patch.object(llm_manager, "_get_openai_client", return_value=fake_client):
        await llm_manager.chat(
            user_message="What is a Data Steward?",
            user_id=mock_test_user.email,
            debug=False,
        )

    # Inspect the messages that were actually sent on the first LLM call.
    assert fake_client.captured_messages, "fake client received no calls"
    first_call_messages = fake_client.captured_messages[0]
    system_msg = first_call_messages[0]
    assert system_msg["role"] == "system"
    sys_text = system_msg["content"]

    # Phrasing markers from the new prompt — load-bearing changes that
    # we want to lock in.
    assert "search_ontos_handbook" in sys_text, (
        "system prompt does not mention the new tool — the new prompt is "
        "probably not being assembled"
    )
    assert "[Documented]" in sys_text, (
        "system prompt missing the three-tier confidence label scheme"
    )
    assert "Tier 0" in sys_text, (
        "system prompt missing the new Tier 0 = handbook-corpus framing"
    )


@pytest.mark.asyncio
async def test_chat_honors_llm_system_prompt_override(llm_manager, mock_test_user):
    """Settings-level override path: ``LLM_SYSTEM_PROMPT`` was previously
    dead code. With the new get_system_prompt() helper it must take
    precedence and be sent verbatim."""
    sentinel = "OVERRIDE PROMPT — Ontos copilot in override mode."
    llm_manager._settings.LLM_SYSTEM_PROMPT = sentinel

    scripted = [_make_response(content="ok", tool_calls=None)]
    fake_client = _ScriptedOpenAIClient(scripted)

    with patch.object(llm_manager, "_get_openai_client", return_value=fake_client):
        await llm_manager.chat(
            user_message="hello",
            user_id=mock_test_user.email,
        )

    first_call_messages = fake_client.captured_messages[0]
    assert first_call_messages[0]["role"] == "system"
    assert first_call_messages[0]["content"] == sentinel
