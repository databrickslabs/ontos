"""
Deep field-by-field comparison helpers for round-trip verification.

Usage:
    assert_fields_match(sent_payload, api_response, ignore=["id", "created_at"])
"""
from typing import Any, Dict, List, Optional, Set


def _normalise(value: Any) -> Any:
    """Normalise a value for comparison (strip whitespace, sort lists, etc.)."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        # Sort lists of primitives; leave lists of dicts in order
        if value and isinstance(value[0], (str, int, float, bool)):
            return sorted(value)
        return [_normalise(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalise(v) for k, v in value.items()}
    return value


def _flatten(obj: Any, prefix: str = "") -> Dict[str, Any]:
    """Flatten a nested dict into dot-separated paths."""
    items: Dict[str, Any] = {}
    if isinstance(obj, dict):
        for key, val in obj.items():
            new_key = f"{prefix}.{key}" if prefix else key
            if isinstance(val, dict):
                items.update(_flatten(val, new_key))
            elif isinstance(val, list) and val and isinstance(val[0], dict):
                for i, item in enumerate(val):
                    items.update(_flatten(item, f"{new_key}[{i}]"))
            else:
                items[new_key] = _normalise(val)
    return items


def assert_fields_match(
    sent: Dict[str, Any],
    received: Dict[str, Any],
    ignore: Optional[Set[str]] = None,
    context: str = "",
):
    """
    Assert that every field in *sent* appears in *received* with the same value.

    - Performs deep recursive comparison on nested dicts and lists.
    - Ignores server-generated fields (id, timestamps, etc.) via *ignore*.
    - Produces a clear diff message listing every mismatched field.

    Args:
        sent:     The payload that was sent to the API.
        received: The response body from the API (GET after create/update).
        ignore:   Set of top-level or dot-path field names to skip.
        context:  Optional label for error messages (e.g. "after CREATE").
    """
    if ignore is None:
        ignore = set()

    # Always ignore common server-generated fields
    auto_ignore = {
        "id", "created_at", "updated_at", "created_by", "updated_by",
        "createdAt", "updatedAt", "createdBy", "updatedBy",
    }
    skip = ignore | auto_ignore

    flat_sent = _flatten(sent)
    flat_recv = _flatten(received)

    mismatches: List[str] = []
    missing: List[str] = []

    for path, expected in flat_sent.items():
        # Check if any prefix of the path is in skip set
        top_level = path.split(".")[0].split("[")[0]
        if top_level in skip or path in skip:
            continue

        # Skip None/null values we sent — the API may omit them
        if expected is None:
            continue

        if path not in flat_recv:
            # Try camelCase ↔ snake_case conversion
            alt_path = _try_alternate_key(path, flat_recv)
            if alt_path is None:
                missing.append(f"  {path}: sent={_repr(expected)}, not in response")
                continue
            actual = flat_recv[alt_path]
        else:
            actual = flat_recv[path]

        actual = _normalise(actual)

        if not _values_equal(expected, actual):
            mismatches.append(
                f"  {path}: sent={_repr(expected)}, got={_repr(actual)}"
            )

    label = f" ({context})" if context else ""
    errors = []
    if mismatches:
        errors.append(f"Field value mismatches{label}:\n" + "\n".join(mismatches))
    if missing:
        errors.append(f"Fields missing from response{label}:\n" + "\n".join(missing))

    if errors:
        raise AssertionError("\n\n".join(errors))


def _values_equal(expected: Any, actual: Any) -> bool:
    """Compare two values with type-flexible equality."""
    if expected == actual:
        return True
    # Compare as strings (handles int/float/bool serialisation differences)
    if str(expected) == str(actual):
        return True
    # Empty list ↔ None
    if expected in ([], None) and actual in ([], None):
        return True
    # Empty dict ↔ None
    if expected in ({}, None) and actual in ({}, None):
        return True
    return False


def _try_alternate_key(path: str, flat: Dict[str, Any]) -> Optional[str]:
    """Try camelCase ↔ snake_case variants of the key."""
    # snake_case → camelCase
    parts = path.split(".")
    alt_parts = []
    for p in parts:
        # Strip array indices for transformation
        base, *rest = p.split("[")
        words = base.split("_")
        camel = words[0] + "".join(w.capitalize() for w in words[1:])
        alt_parts.append(camel + ("[" + "[".join(rest) if rest else ""))

    alt_path = ".".join(alt_parts)
    if alt_path in flat:
        return alt_path

    # camelCase → snake_case
    import re
    alt_parts2 = []
    for p in parts:
        base, *rest = p.split("[")
        snake = re.sub(r"([A-Z])", r"_\1", base).lower().lstrip("_")
        alt_parts2.append(snake + ("[" + "[".join(rest) if rest else ""))

    alt_path2 = ".".join(alt_parts2)
    if alt_path2 in flat:
        return alt_path2

    return None


def _repr(val: Any) -> str:
    """Compact repr for error messages."""
    s = repr(val)
    return s if len(s) <= 80 else s[:77] + "..."
