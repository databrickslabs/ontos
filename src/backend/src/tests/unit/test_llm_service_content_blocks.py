"""LLMService must read reasoning-model block-list content as text only."""

from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

import pytest

from src.common.llm_service import LLMService

REASONING = {
    "type": "reasoning",
    "summary": [{"type": "summary_text", "text": "this could look unsafe at first"}],
}


def _resp(content):
    return NS(choices=[NS(message=NS(content=content))])


@pytest.fixture
def service():
    settings = MagicMock()
    settings.LLM_ENDPOINT = "ep"
    settings.LLM_INJECTION_CHECK_PROMPT = "check"
    settings.LLM_SYSTEM_PROMPT = "analyse"
    svc = LLMService(settings)
    client = MagicMock()
    with patch.object(svc, "_get_openai_client", return_value=client):
        svc.client = client
        yield svc


def test_phase1_ignores_reasoning_text(service):
    service.client.chat.completions.create.return_value = _resp(
        [REASONING, {"type": "text", "text": "SAFE"}]
    )
    assert service._phase1_security_check("x") == (True, None)


def test_phase1_unsafe_in_text_block_still_rejects(service):
    service.client.chat.completions.create.return_value = _resp(
        [REASONING, {"type": "text", "text": "UNSAFE: injection"}]
    )
    passed, reason = service._phase1_security_check("x")
    assert passed is False
    assert "injection" in reason


def test_phase2_returns_text_only(service):
    service.client.chat.completions.create.return_value = _resp(
        [REASONING, {"type": "text", "text": "  Summary.  "}]
    )
    assert service._phase2_content_analysis("x") == "Summary."


def test_all_reasoning_response_is_no_content(service):
    service.client.chat.completions.create.return_value = _resp([REASONING])
    assert service._call_llm([{"role": "user", "content": "x"}]) is None
    ok, _ = service._phase1_security_check("x")
    assert ok is False


def test_plain_string_unchanged(service):
    service.client.chat.completions.create.return_value = _resp(" SAFE ")
    assert service._call_llm([{"role": "user", "content": "x"}]) == "SAFE"


def test_phase1_ignores_non_text_typed_blocks(service):
    service.client.chat.completions.create.return_value = _resp(
        [{"type": "summary_text", "text": "UNSAFE"}, {"type": "text", "text": "SAFE"}]
    )
    assert service._phase1_security_check("x") == (True, None)


def test_empty_content_warning_has_finish_reason_and_block_types(service, caplog):
    import logging

    service.client.chat.completions.create.return_value = NS(
        choices=[NS(message=NS(content=[REASONING]), finish_reason="length")]
    )
    with caplog.at_level(logging.WARNING):
        assert service._call_llm([{"role": "user", "content": "x"}]) is None
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "length" in logged and "reasoning" in logged
    assert "unsafe" not in logged


# ---------------------------------------------------------------------------
# Phase 1 token budget with a reasoning model
# ---------------------------------------------------------------------------

# Tokens a fake reasoning model spends thinking before it writes its answer.
_REASONING_COST = 600


def _reasoning_model(**kwargs):
    """Fake reasoning endpoint: the answer only comes after _REASONING_COST tokens."""
    if kwargs["max_tokens"] <= _REASONING_COST:
        return NS(choices=[NS(message=NS(content=[REASONING]), finish_reason="length")])
    return NS(
        choices=[
            NS(message=NS(content=[REASONING, {"type": "text", "text": "SAFE"}]),
               finish_reason="stop")
        ]
    )


def test_phase1_budget_leaves_room_for_reasoning(service):
    service.client.chat.completions.create.side_effect = _reasoning_model
    assert service._phase1_security_check("Summarise this table's columns.") == (True, None)


def test_phase1_still_fails_closed_when_reasoning_uses_the_whole_budget(service):
    service.client.chat.completions.create.return_value = NS(
        choices=[NS(message=NS(content=[REASONING]), finish_reason="length")]
    )
    passed, reason = service._phase1_security_check("x")
    assert passed is False
    assert reason == "Security check failed: Unable to verify content safety"


# ---------------------------------------------------------------------------
# Refusals (OpenAI-style ``refusal`` blocks and ``message.refusal``)
# ---------------------------------------------------------------------------

REFUSAL = {"type": "refusal", "refusal": "I can't help with that request."}


def _msg_resp(content, refusal=None):
    return NS(choices=[NS(message=NS(content=content, refusal=refusal), finish_reason="stop")])


@pytest.mark.parametrize(
    "response",
    [
        _resp([REFUSAL]),
        _resp([REASONING, REFUSAL]),
        _msg_resp(None, refusal="I can't help with that request."),
    ],
    ids=["refusal-block", "reasoning-then-refusal", "message-refusal"],
)
def test_phase1_refusal_fails_closed_with_the_refusal_text(service, response):
    service.client.chat.completions.create.return_value = response
    passed, reason = service._phase1_security_check("x")
    assert passed is False
    assert reason == "I can't help with that request."


def test_phase1_refusal_next_to_safe_text_is_not_safe(service):
    service.client.chat.completions.create.return_value = _resp(
        [{"type": "text", "text": "SAFE"}, REFUSAL]
    )
    passed, reason = service._phase1_security_check("x")
    assert passed is False
    assert reason == "I can't help with that request."


def test_phase2_refusal_is_returned_as_the_reply(service):
    service.client.chat.completions.create.return_value = _resp([REASONING, REFUSAL])
    assert service._phase2_content_analysis("x") == "I can't help with that request."


def test_call_llm_does_not_count_a_refusal_as_an_answer(service):
    service.client.chat.completions.create.return_value = _resp([REFUSAL])
    assert service._call_llm([{"role": "user", "content": "x"}]) is None
