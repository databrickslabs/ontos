"""Integration tests for the Phase 2 adoption-mode preamble.

Exercises ``LLMSearchManager._process_with_llm`` end-to-end with a
fake OpenAI client. Verifies:

1. The new ``get_app_state`` tool is registered AND in the always-on
   category set so it appears in the LLM's tool list on every call.
2. The system prompt actually sent to the model contains the
   adoption-mode preamble matching the live DB state.
3. The default (no preamble) prompt round-trips byte-identical to
   Phase 1 when no Phase 2/3 context is available — protects the
   Phase 1 integration tests from a silent regression.
4. ``GET /api/llm-search/status`` exposes ``adoption_mode`` so the
   frontend can pick mode-aware starter prompts.

Patterned after ``test_llm_search_concepts.py``.
"""

# Set test environment variables BEFORE any app imports
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
import uuid
from types import SimpleNamespace
from typing import List
from unittest.mock import MagicMock, patch

import pytest

from src.db_models.data_products import DataProductDb


# ---------------------------------------------------------------------------
# Fake OpenAI client (same shape as the concepts integration test)
# ---------------------------------------------------------------------------


def _make_response(*, content, tool_calls):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


class _ScriptedOpenAIClient:
    """Records every ``messages=`` payload it sees so a test can
    assert against the actual system message sent on a given call."""

    def __init__(self, script):
        self._script = list(script)
        self._call_count = 0
        self.captured_messages: List[List[dict]] = []
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, *, model, messages, tools, tool_choice, max_tokens):
        self.captured_messages.append(messages)
        if not self._script:
            raise AssertionError("ScriptedOpenAIClient ran out of scripted responses")
        resp = self._script.pop(0)
        self._call_count += 1
        return resp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def llm_settings(test_settings):
    test_settings.LLM_ENABLED = True
    test_settings.LLM_ENDPOINT = "test-endpoint"
    test_settings.LLM_SYSTEM_PROMPT = None
    return test_settings


@pytest.fixture
def llm_manager(db_session, llm_settings, mock_workspace_client):
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


def _seed_published_product(db_session):
    """Push the workspace from 'blank' to 'active' by inserting one
    published product. Returns the row so the caller can roll it back
    if needed (the autouse db_session rolls back on teardown anyway)."""
    product = DataProductDb(
        id=str(uuid.uuid4()),
        name="Seed Published",
        version="1.0.0",
        status="active",
        publication_scope="organization",
    )
    db_session.add(product)
    db_session.commit()
    return product


# ---------------------------------------------------------------------------
# Registry / always-on category
# ---------------------------------------------------------------------------


def test_registry_contains_app_state_tool(llm_manager):
    assert "get_app_state" in llm_manager._tool_registry.list_tool_names()


def test_app_state_category_is_always_on():
    """``get_app_state`` must be available on EVERY chat call so the
    LLM can introspect adoption when relevant; the prompt only carries
    a static preamble, the tool gives counts."""
    from src.tools.query_classifier import classify_query, ALWAYS_INCLUDED_CATEGORIES

    assert "app_state" in ALWAYS_INCLUDED_CATEGORIES
    # Random unrelated query — `app_state` must still surface.
    cats = classify_query("show me cost rollups")
    assert "app_state" in cats


# ---------------------------------------------------------------------------
# System-prompt injection (blank vs active)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blank_workspace_injects_blank_preamble(llm_manager, mock_test_user):
    """With zero published products in the DB, the assembled system
    prompt must contain the blank-mode preamble AND the new
    ``## Current workspace state`` H2 above the default body."""
    scripted = [_make_response(content="ok", tool_calls=None)]
    fake_client = _ScriptedOpenAIClient(scripted)

    with patch.object(llm_manager, "_get_openai_client", return_value=fake_client):
        await llm_manager.chat(
            user_message="hello",
            user_id=mock_test_user.email,
        )

    first_call_messages = fake_client.captured_messages[0]
    sys_text = first_call_messages[0]["content"]

    assert "## Current workspace state" in sys_text, (
        "blank-mode preamble heading is missing — adoption-mode "
        "injection probably regressed"
    )
    assert "no data products are published yet" in sys_text
    # Phase 1 body must still be present below the preamble.
    assert "## Tool-first policy for conceptual questions" in sys_text


@pytest.mark.asyncio
async def test_active_workspace_injects_active_preamble(
    llm_manager, mock_test_user, db_session
):
    _seed_published_product(db_session)

    scripted = [_make_response(content="ok", tool_calls=None)]
    fake_client = _ScriptedOpenAIClient(scripted)

    with patch.object(llm_manager, "_get_openai_client", return_value=fake_client):
        await llm_manager.chat(
            user_message="hello",
            user_id=mock_test_user.email,
        )

    sys_text = fake_client.captured_messages[0][0]["content"]
    assert "## Current workspace state" in sys_text
    assert "has published data products" in sys_text


# ---------------------------------------------------------------------------
# Override path still wins
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_system_prompt_override_skips_adoption_preamble(
    llm_manager, mock_test_user
):
    """``LLM_SYSTEM_PROMPT`` is a full replacement — the adoption-mode
    preamble must NOT be prepended on top, otherwise the override
    promise breaks."""
    sentinel = "OVERRIDE PROMPT — exact bytes only."
    llm_manager._settings.LLM_SYSTEM_PROMPT = sentinel

    scripted = [_make_response(content="ok", tool_calls=None)]
    fake_client = _ScriptedOpenAIClient(scripted)

    with patch.object(llm_manager, "_get_openai_client", return_value=fake_client):
        await llm_manager.chat(
            user_message="hello",
            user_id=mock_test_user.email,
        )

    sys_text = fake_client.captured_messages[0][0]["content"]
    assert sys_text == sentinel


# ---------------------------------------------------------------------------
# get_status surfaces the mode
# ---------------------------------------------------------------------------


def test_get_status_returns_adoption_mode(llm_manager):
    """``adoption_mode`` must be on the status payload so the frontend
    can switch starter prompts without a separate round-trip."""
    status = llm_manager.get_status()
    assert status.adoption_mode in ("blank", "active")
    # No published products seeded -> blank.
    assert status.adoption_mode == "blank"


def test_get_status_returns_active_after_publish(llm_manager, db_session):
    _seed_published_product(db_session)
    status = llm_manager.get_status()
    assert status.adoption_mode == "active"


# ---------------------------------------------------------------------------
# Snapshot failure degrades gracefully
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_failure_falls_back_to_default_prompt(
    llm_manager, mock_test_user
):
    """If the snapshot raises, the manager must log and proceed with
    ``adoption_mode=None`` — the chat must still succeed and the
    prompt sent must be the Phase 1 default (no preamble heading)."""
    scripted = [_make_response(content="ok", tool_calls=None)]
    fake_client = _ScriptedOpenAIClient(scripted)

    with patch(
        "src.tools.app_state.get_adoption_snapshot",
        side_effect=RuntimeError("snapshot broke"),
    ):
        with patch.object(llm_manager, "_get_openai_client", return_value=fake_client):
            response = await llm_manager.chat(
                user_message="hello",
                user_id=mock_test_user.email,
            )

    assert response.message.content
    sys_text = fake_client.captured_messages[0][0]["content"]
    # No preamble when the snapshot failed.
    assert "## Current workspace state" not in sys_text
    # But the Phase 1 body must still be present.
    assert "## Tool-first policy for conceptual questions" in sys_text
