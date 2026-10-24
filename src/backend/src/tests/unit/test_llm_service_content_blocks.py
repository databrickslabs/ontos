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
