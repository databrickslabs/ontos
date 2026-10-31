"""Helpers for reading the ``content`` of an LLM chat-completion message.

Databricks' OpenAI-compatible serving shim returns ``content`` as a *list* of
structured blocks for reasoning-capable models (Claude Sonnet/Opus 5, Claude
Haiku 5.5, gpt-oss, and similar), e.g.
``[{"type": "reasoning", ...}, {"type": "text", "text": "..."}]``. Older
models return a plain string. Every reader that parses or shows
``message.content`` goes through :func:`coerce_message_text` so it only ever
sees the user-facing text. The exception is content echoed back to the model
unchanged (the ontology generator's tool-call path), which keeps its original
shape.
"""

from typing import Any

# Block types that carry the model's answer. A block with no type is also kept.
# Every other typed block (reasoning, thinking, redacted_thinking, summary_text,
# tool_use, ...) is not part of the answer and is dropped.
_TEXT_BLOCK_TYPES = ("text", "output_text")


def _is_answer_type(block_type: Any) -> bool:
    return block_type is None or block_type in _TEXT_BLOCK_TYPES


def block_text(block: Any) -> str:
    """Extract user-facing text from one content block, or "" if it carries none.

    Allowlist: a block is read only when it has no type or its type is
    ``text`` / ``output_text``; every other typed block is dropped, so the
    model's scratchpad (reasoning, thinking, summaries) never reaches the user
    or a safety check. Plain strings are kept.
    """
    # dict-shaped block (raw JSON from the serving shim)
    if isinstance(block, dict):
        if not _is_answer_type(block.get("type")):
            return ""
        text = block.get("text")
        return text if isinstance(text, str) else ""
    # object-shaped block (OpenAI SDK / pydantic)
    if not _is_answer_type(getattr(block, "type", None)):
        return ""
    text = getattr(block, "text", None)
    if isinstance(text, str):
        return text
    if isinstance(block, str):
        return block
    return ""


def coerce_message_text(content: Any) -> str:
    """Normalise an LLM message's ``content`` to a plain string.

    Keeps only answer text blocks (see :func:`block_text`) and joins them.
    ``None`` becomes ``""``. A lone block (dict, or object with a ``type`` or
    ``text``) is read like a one-item list and never stringified, so a bare
    reasoning block yields ``""``.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        return "".join(block_text(b) for b in content)
    if isinstance(content, dict) or hasattr(content, "type") or hasattr(content, "text"):
        return block_text(content)
    # Other scalar: best-effort stringify.
    return str(content)


def block_types(content: Any) -> list:
    """Return the block ``type`` names of a block-list ``content`` (for logging)."""
    if not isinstance(content, (list, tuple)):
        return []
    types = []
    for b in content:
        t = b.get("type") if isinstance(b, dict) else getattr(b, "type", None)
        types.append(t if isinstance(t, str) else type(b).__name__)
    return types
