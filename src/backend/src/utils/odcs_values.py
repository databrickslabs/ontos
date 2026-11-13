"""ODCS values kept in text columns with their JSON type.

An SLA property's ``value`` and ``valueExt`` and a custom property's ``value``
can be any JSON value (``true``, ``42``, ``"42"``, an object ...), and the
columns are text. Plain text is stored as is, so the rows stay readable (and
rows written before keep their meaning); anything else, and a string that
would read back as another type (``"42"``, ``"true"``), is stored as JSON.
"""
import json
import math
from typing import Any, Optional


def _no_constant(name: str):
    raise ValueError(name)


def strict_loads(text: str) -> Any:
    """``json.loads`` without the non-standard ``NaN`` / ``Infinity``, which
    aren't JSON (an API answer with them fails): such text stays text."""
    return json.loads(text, parse_constant=_no_constant)


def typed_text(value: Any) -> Optional[str]:
    """The text to store for ``value``."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            strict_loads(value)
        except ValueError:
            return value  # plain text
        return json.dumps(value)  # text that reads as JSON: keep it a string
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return json.dumps(value)


def typed_value(text: Optional[str]) -> Any:
    """The value stored by ``typed_text`` (JSON decoded, plain text as is)."""
    if text is None:
        return None
    try:
        return strict_loads(text)
    except (TypeError, ValueError):
        return text


def page_text(text: Optional[str]) -> Optional[str]:
    """A stored value as the contract page shows and edits it: text values as
    the text (not JSON-quoted), other values as their JSON text."""
    value = typed_value(text)
    return value if isinstance(value, str) else text
