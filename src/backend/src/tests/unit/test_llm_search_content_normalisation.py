"""Tests for normalising reasoning-model message content in LLMSearchManager.

Databricks' OpenAI-compatible serving shim returns an assistant message's
``content`` as a plain string for most models, but as a *list* of structured
blocks for reasoning-capable models (Claude Sonnet/Opus 5, Claude Haiku 5.5,
gpt-oss, and similar): e.g. ``[{"type": "reasoning", ...}, {"type": "text",
"text": "..."}]``.

``_strip_internal_citations`` previously assumed a string and ran a regex
straight on ``content``. When "Ask Ontos" was pointed at a reasoning endpoint
the agent therefore crashed on every answer with::

    TypeError: expected string or bytes-like object, got 'list'

The serving endpoint still returned HTTP 200 (so the call was billed), but the
user only ever saw "I encountered an error ... (TypeError)". These tests lock
in the content-normalisation helpers that keep the text, drop the reasoning
block, and leave string/None handling unchanged.
"""

import pytest

from src.common.llm_content import block_text, block_types, coerce_message_text
from src.controller.llm_search_manager import _strip_internal_citations


class _Block:
    """Minimal stand-in for an OpenAI-SDK content block (attribute access)."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


# ---------------------------------------------------------------------------
# block_text
# ---------------------------------------------------------------------------


def test_block_text_keeps_text_block_drops_reasoning():
    assert block_text({"type": "text", "text": "hello"}) == "hello"
    assert block_text({"type": "reasoning", "text": "scratchpad"}) == ""
    assert block_text({"type": "thinking", "text": "scratchpad"}) == ""


def test_block_text_handles_objects_and_raw_strings():
    assert block_text(_Block(type="text", text="hi")) == "hi"
    assert block_text(_Block(type="reasoning", text=None)) == ""
    assert block_text("raw string") == "raw string"
    assert block_text(123) == ""


# ---------------------------------------------------------------------------
# coerce_message_text
# ---------------------------------------------------------------------------


def test_coerce_passthrough_string_and_none():
    assert coerce_message_text("already text") == "already text"
    assert coerce_message_text(None) == ""


def test_coerce_joins_text_blocks_and_drops_reasoning():
    content = [
        {"type": "reasoning", "summary": [{"type": "summary_text", "text": "internal"}]},
        {"type": "text", "text": "A data product is "},
        {"type": "text", "text": "a curated asset."},
    ]
    assert coerce_message_text(content) == "A data product is a curated asset."


def test_block_text_is_an_allowlist():
    assert block_text({"text": "untyped"}) == "untyped"
    assert block_text({"type": None, "text": "untyped"}) == "untyped"
    assert block_text({"type": "output_text", "text": "out"}) == "out"
    for kind in ("summary_text", "redacted_thinking", "tool_use", "reasoning", "image"):
        assert block_text({"type": kind, "text": "UNSAFE"}) == ""
        assert block_text(_Block(type=kind, text="UNSAFE")) == ""


def test_coerce_bare_block_never_falls_back_to_repr():
    reasoning = {"type": "reasoning", "text": "secret", "summary": []}
    assert coerce_message_text(reasoning) == ""
    assert coerce_message_text(_Block(type="reasoning", text="secret")) == ""
    assert coerce_message_text({"type": "text", "text": "ok"}) == "ok"
    assert coerce_message_text(_Block(type="text", text="ok")) == "ok"
    assert coerce_message_text(42) == "42"


def test_coerce_bare_object_with_text_but_no_type():
    class _TextOnly:
        text = "plain answer"

    assert coerce_message_text(_TextOnly()) == "plain answer"


def test_coerce_handles_object_blocks():
    content = [_Block(type="reasoning", text=None), _Block(type="text", text="answer")]
    assert coerce_message_text(content) == "answer"


# ---------------------------------------------------------------------------
# _strip_internal_citations (the function that used to crash)
# ---------------------------------------------------------------------------


def test_strip_on_list_content_does_not_raise_and_drops_reasoning():
    """Regression: a non-empty list must not raise TypeError."""
    content = [
        {"type": "reasoning", "summary": [{"type": "summary_text", "text": "internal"}]},
        {"type": "text", "text": "A data product is a curated asset."},
    ]
    cleaned, citations, confidence = _strip_internal_citations(content)
    assert cleaned == "A data product is a curated asset."
    assert "internal" not in cleaned
    assert citations == []
    assert confidence == []


def test_strip_on_list_still_extracts_citations_and_labels():
    content = [
        {"type": "reasoning", "summary": []},
        {
            "type": "text",
            "text": (
                "Ownership is per data product <!-- ref: ownership.md#model --> here. [Confirmed]"
            ),
        },
    ]
    cleaned, citations, confidence = _strip_internal_citations(content)
    assert citations == ["ownership.md#model"]
    assert confidence == ["Confirmed"]
    assert "<!-- ref:" not in cleaned
    assert "[Confirmed]" not in cleaned


def test_strip_string_behaviour_unchanged():
    cleaned, citations, confidence = _strip_internal_citations(
        "A contract defines a schema <!-- ref: contracts.md#intro -->. [Documented]"
    )
    assert citations == ["contracts.md#intro"]
    assert confidence == ["Documented"]
    assert "<!-- ref:" not in cleaned
    assert "[Documented]" not in cleaned


def test_strip_none_and_empty_return_empty():
    assert _strip_internal_citations(None) == ("", [], [])
    assert _strip_internal_citations("") == ("", [], [])
    assert _strip_internal_citations([]) == ("", [], [])


# ---------------------------------------------------------------------------
# block_types (log helper) and the empty-answer fallback in the agent loop
# ---------------------------------------------------------------------------


def test_block_types_lists_types_without_content():
    content = [{"type": "reasoning", "text": "secret"}, _Block(type="text", text="x"), "raw"]
    assert block_types(content) == ["reasoning", "text", "str"]
    assert block_types("plain") == []
    assert block_types(None) == []


@pytest.fixture
def chat_manager(db_session):
    from types import SimpleNamespace

    from src.controller.llm_search_manager import LLMSearchManager

    return LLMSearchManager(
        db=db_session,
        settings=SimpleNamespace(LLM_ENABLED=True, LLM_ENDPOINT="ep", LLM_SYSTEM_PROMPT=None),
    )


def _final_answer_client(content):
    from types import SimpleNamespace as NS
    from unittest.mock import MagicMock

    client = MagicMock()
    client.chat.completions.create.return_value = NS(
        choices=[NS(message=NS(content=content, tool_calls=None), finish_reason="length")],
        usage=None,
    )
    return client


async def _chat(manager, content):
    from unittest.mock import patch

    client = _final_answer_client(content)
    with patch.object(manager, "_get_openai_client", return_value=client), patch(
        "src.tools.app_state.get_adoption_snapshot", return_value={}
    ):
        return await manager.chat("hi", user_id="u@example.com")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        [{"type": "reasoning", "summary": [{"type": "summary_text", "text": "hidden"}]}],
        "   ",
        "*****",
        [{"type": "text", "text": "****"}],
    ],
    ids=["reasoning-only", "blank", "asterisks", "asterisks-block"],
)
async def test_empty_answer_is_a_coded_error(chat_manager, caplog, content):
    import logging

    with caplog.at_level(logging.WARNING):
        response = await _chat(chat_manager, content)
    message = response.message
    assert message.error_code == "chat_empty_answer"
    error_id = message.error_params["errorId"]
    assert error_id in message.content
    assert "hidden" not in message.content
    logged = "\n".join(r.getMessage() + (r.exc_text or "") for r in caplog.records)
    assert error_id in logged
    assert "hidden" not in logged
    assert "finish_reason" in logged


@pytest.mark.asyncio
async def test_normal_answer_is_unchanged(chat_manager):
    response = await _chat(
        chat_manager, [{"type": "reasoning"}, {"type": "text", "text": "Real answer."}]
    )
    assert response.message.content == "Real answer."
    assert response.message.error_code is None
