"""Integration tests for the Phase 3 user-context preamble.

Exercises the role + page + selected-entity injection through both
``LLMSearchManager.chat`` (directly) and ``get_system_prompt`` (the
assembly point). Verifies:

1. When the chat request includes ``page_name`` / ``selected_entity``,
   the system prompt sent to the model contains a
   ``## Current user context`` H2 block with the matching fields.
2. The role label propagates verbatim from the chat call.
3. Phase 3 fields are all optional — a payload without any of them
   still hits the same code paths without raising and without
   emitting the preamble.

We don't reach through ``POST /api/llm-search/chat`` for these tests
— the route's role-derivation helper (``_derive_effective_role_label``)
is exercised separately in unit tests; here we focus on what the
manager actually sends to the LLM.
"""

# Set test environment variables BEFORE any app imports
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from types import SimpleNamespace
from typing import List
from unittest.mock import MagicMock, patch

import pytest


def _make_response(*, content, tool_calls):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


class _ScriptedOpenAIClient:
    """Records every ``messages=`` payload it sees so a test can
    assert against the actual system message sent."""

    def __init__(self, script):
        self._script = list(script)
        self.captured_messages: List[List[dict]] = []
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, *, model, messages, tools, tool_choice, max_tokens):
        self.captured_messages.append(messages)
        if not self._script:
            raise AssertionError("ScriptedOpenAIClient ran out of scripted responses")
        return self._script.pop(0)


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


# ---------------------------------------------------------------------------
# Direct prompt-assembly tests
# ---------------------------------------------------------------------------


def test_get_system_prompt_renders_full_user_context_block(llm_settings):
    """All three Phase 3 inputs should produce a fully-populated
    ``## Current user context`` block above the default body."""
    from src.controller.system_prompts import get_system_prompt

    prompt = get_system_prompt(
        settings=llm_settings,
        role="Data Consumer",
        page_name="data-products",
        page_url="/data-products/abc",
        selected_entity={
            "type": "data_product",
            "name": "Customer 360",
            "id": "uuid-abc",
        },
    )
    assert "## Current user context" in prompt
    assert "**Role**: Data Consumer" in prompt
    assert "**Currently on**: data-products (/data-products/abc)" in prompt
    assert '"Customer 360"' in prompt
    assert "uuid-abc" in prompt
    # Default body still present below the preamble.
    assert "## Tool-first policy for conceptual questions" in prompt


def test_get_system_prompt_omits_user_context_when_all_inputs_empty(llm_settings):
    """Phase 1 byte-identity contract — when nothing is passed we must
    return the default prompt unchanged so existing tests don't see
    spurious whitespace / preamble drift."""
    from src.controller.system_prompts import (
        _DEFAULT_SYSTEM_PROMPT,
        get_system_prompt,
    )

    prompt = get_system_prompt(settings=llm_settings)
    assert prompt == _DEFAULT_SYSTEM_PROMPT


def test_get_system_prompt_partial_user_context_still_renders(llm_settings):
    """Role alone (no page, no entity) is enough to trigger the
    block — partial payloads are common in practice (e.g., home page
    where the user has a role but no entity selected)."""
    from src.controller.system_prompts import get_system_prompt

    prompt = get_system_prompt(settings=llm_settings, role="Admin")
    assert "## Current user context" in prompt
    assert "**Role**: Admin" in prompt
    # No "Currently on" line because page_name is None.
    assert "**Currently on**" not in prompt
    assert "**Viewing**" not in prompt


def test_user_context_handles_entity_without_id(llm_settings):
    """When ``selected_entity`` lacks an id (e.g., user is creating a
    new draft), the preamble must still render the type + name
    without crashing or emitting a 'None' literal."""
    from src.controller.system_prompts import get_system_prompt

    prompt = get_system_prompt(
        settings=llm_settings,
        role="Data Producer",
        page_name="data-products",
        selected_entity={"type": "data_product", "name": "Draft X"},
    )
    assert '"Draft X"' in prompt
    assert "id:" not in prompt  # no id => no "id: …" suffix
    assert "None" not in prompt  # never leak a Python None


# ---------------------------------------------------------------------------
# End-to-end through LLMSearchManager.chat
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_propagates_user_context_to_system_prompt(
    llm_manager, mock_test_user
):
    """The chat() entry point must pass role / page / entity through
    to the LLM call, which means the system prompt captured by the
    fake client should contain matching strings."""
    scripted = [_make_response(content="ok", tool_calls=None)]
    fake_client = _ScriptedOpenAIClient(scripted)

    with patch.object(llm_manager, "_get_openai_client", return_value=fake_client):
        await llm_manager.chat(
            user_message="hello",
            user_id=mock_test_user.email,
            role="Data Consumer",
            page_name="data-products",
            page_url="/data-products/abc",
            selected_entity={
                "type": "data_product",
                "name": "Customer 360",
                "id": "uuid-abc",
            },
        )

    sys_text = fake_client.captured_messages[0][0]["content"]
    assert "## Current user context" in sys_text
    assert "Data Consumer" in sys_text
    assert "data-products" in sys_text
    assert "Customer 360" in sys_text


@pytest.mark.asyncio
async def test_chat_without_context_still_works(llm_manager, mock_test_user):
    """Backward compatibility: payload with no Phase 3 fields must
    still chat successfully and must NOT emit the preamble heading."""
    scripted = [_make_response(content="ok", tool_calls=None)]
    fake_client = _ScriptedOpenAIClient(scripted)

    with patch.object(llm_manager, "_get_openai_client", return_value=fake_client):
        response = await llm_manager.chat(
            user_message="hello",
            user_id=mock_test_user.email,
        )

    assert response.message.content
    sys_text = fake_client.captured_messages[0][0]["content"]
    assert "## Current user context" not in sys_text


@pytest.mark.asyncio
async def test_chat_context_is_cleared_between_calls(llm_manager, mock_test_user):
    """``self._chat_context`` is set by ``chat()`` and must be reset
    in a finally block so the next call without context doesn't
    inherit the previous call's role / page."""
    # First call WITH context.
    scripted_a = [_make_response(content="ok", tool_calls=None)]
    fake_a = _ScriptedOpenAIClient(scripted_a)
    with patch.object(llm_manager, "_get_openai_client", return_value=fake_a):
        await llm_manager.chat(
            user_message="hello",
            user_id=mock_test_user.email,
            role="Admin",
            page_name="settings",
        )
    assert llm_manager._chat_context is None

    # Second call WITHOUT context — must not leak "Admin" / "settings".
    scripted_b = [_make_response(content="ok", tool_calls=None)]
    fake_b = _ScriptedOpenAIClient(scripted_b)
    with patch.object(llm_manager, "_get_openai_client", return_value=fake_b):
        await llm_manager.chat(
            user_message="hello",
            user_id=mock_test_user.email,
        )

    sys_text_b = fake_b.captured_messages[0][0]["content"]
    assert "Admin" not in sys_text_b or "## Current user context" not in sys_text_b


# ---------------------------------------------------------------------------
# Route role-derivation helper
# ---------------------------------------------------------------------------


def test_derive_effective_role_label_returns_none_when_no_settings_manager():
    """Defense-in-depth: a missing settings_manager on app.state
    (unusual but possible during boot) must not 500 the chat call."""
    from src.routes.llm_search_routes import _derive_effective_role_label
    from src.models.users import UserInfo

    request = MagicMock()
    request.app.state = SimpleNamespace()  # no settings_manager attr
    user = UserInfo(
        email="u@example.com",
        username="u",
        user="u",
        ip="127.0.0.1",
        groups=["admins"],
    )
    assert _derive_effective_role_label(request, user) is None


def test_derive_effective_role_label_returns_none_for_empty_groups():
    """Anonymous-style call (no groups). Helper should short-circuit."""
    from src.routes.llm_search_routes import _derive_effective_role_label
    from src.models.users import UserInfo

    request = MagicMock()
    request.app.state.settings_manager = MagicMock()
    request.app.state.settings_manager.list_app_roles.return_value = [
        SimpleNamespace(name="Admin", assigned_groups=["admins"]),
    ]
    user = UserInfo(
        email="u@example.com",
        username="u",
        user="u",
        ip="127.0.0.1",
        groups=[],
    )
    assert _derive_effective_role_label(request, user) is None


def test_derive_effective_role_label_intersects_groups():
    """Group intersection (case-insensitive) -> role name string."""
    from src.routes.llm_search_routes import _derive_effective_role_label
    from src.models.users import UserInfo

    request = MagicMock()
    request.app.state.settings_manager = MagicMock()
    request.app.state.settings_manager.list_app_roles.return_value = [
        SimpleNamespace(name="Admin", assigned_groups=["admins"]),
        SimpleNamespace(name="Data Producer", assigned_groups=["data-producers"]),
        SimpleNamespace(name="Data Consumer", assigned_groups=["data-consumers"]),
    ]
    user = UserInfo(
        email="u@example.com",
        username="u",
        user="u",
        ip="127.0.0.1",
        groups=["Data-Producers"],  # mixed case — must still match
    )
    assert _derive_effective_role_label(request, user) == "Data Producer"


def test_derive_effective_role_label_joins_multiple_roles():
    """A user in multiple role groups returns a comma-joined label."""
    from src.routes.llm_search_routes import _derive_effective_role_label
    from src.models.users import UserInfo

    request = MagicMock()
    request.app.state.settings_manager = MagicMock()
    request.app.state.settings_manager.list_app_roles.return_value = [
        SimpleNamespace(name="Admin", assigned_groups=["admins"]),
        SimpleNamespace(name="Data Producer", assigned_groups=["data-producers"]),
    ]
    user = UserInfo(
        email="u@example.com",
        username="u",
        user="u",
        ip="127.0.0.1",
        groups=["admins", "data-producers"],
    )
    label = _derive_effective_role_label(request, user)
    assert "Admin" in label
    assert "Data Producer" in label
    assert ", " in label
