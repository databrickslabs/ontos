"""ODCS values kept in text columns with their JSON type.

An SLA property's ``value`` and ``valueExt`` and a custom property's ``value``
can be any JSON value (``true``, ``42``, ``"42"``, an object ...), and the
columns are text. Plain text is stored as is, so the rows stay readable (and
rows written before keep their meaning); anything else, and a string that
would read back as another type (``"42"``, ``"true"``), is stored as JSON.
"""
import json
from typing import Any, Optional


def typed_text(value: Any) -> Optional[str]:
    """The text to store for ``value``."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            json.loads(value)
        except ValueError:
            return value  # plain text
        return json.dumps(value)  # text that reads as JSON: keep it a string
    return json.dumps(value)


def typed_value(text: Optional[str]) -> Any:
    """The value stored by ``typed_text`` (JSON decoded, plain text as is)."""
    if text is None:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text
