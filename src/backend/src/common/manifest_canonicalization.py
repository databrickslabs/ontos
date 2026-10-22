"""
Canonical JSON serialization (RFC 8785 subset) for data product manifests.

Implements a strict subset of RFC 8785 that excludes floating-point numbers,
ensuring that identical content always produces identical bytes regardless of
implementation language or environment.

Reference:
  - RFC 8785: JSON Canonicalization Scheme (JCS)
  - Decision 1: Canonical JSON (strict subset of RFC 8785) in
    docs/decisions/manifest-canonicalization-hashing-signing.md
"""

import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union
from uuid import UUID


class CanonicalizationError(ValueError):
    """Raised when content cannot be canonicalized (e.g., floats detected)."""

    def __init__(self, code: str, message: str, path: str = ""):
        self.code = code
        self.message = message
        self.path = path
        full_msg = f"{code}: {message}"
        if path:
            full_msg += f" (at {path})"
        super().__init__(full_msg)


def _is_float(value: Any) -> bool:
    """Check if a value is a float (including integral floats like 1.0)."""
    if isinstance(value, float):
        return True
    if isinstance(value, Decimal):
        # Decimals are allowed and will be converted to strings by the builder
        return False
    return False


# ADR: "Only integers with absolute value below 2^53" (the I-JSON safe range).
_MAX_ABS_INTEGER = 2**53


def _check_integer_range(value: int, path: str) -> None:
    """Raise CanonicalizationError if value is outside the I-JSON integer range."""
    if abs(value) >= _MAX_ABS_INTEGER:
        raise CanonicalizationError(
            "integer_out_of_range",
            f"Integer {value} is outside the range allowed in canonical JSON "
            f"(absolute value must be below 2^53)",
            path,
        )


def _check_string(value: str, path: str) -> None:
    """Raise CanonicalizationError if value has a lone surrogate (ADR: rejected)."""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise CanonicalizationError(
            "invalid_string",
            "String contains lone surrogates",
            path,
        ) from None


def _check_key(key: Any, path: str) -> None:
    """Object keys must be strings (ADR: "Keys are strings"), checked like values."""
    if not isinstance(key, str):
        raise CanonicalizationError(
            "unsupported_type",
            f"Object key of type {type(key).__name__} not supported in canonical JSON",
            path,
        )
    _check_string(key, path)


def _check_no_floats(obj: Any, path: str = "$") -> None:
    """
    Recursively check that obj contains no floats and no out-of-range integers.

    Raises CanonicalizationError if a float is found, an integer whose absolute
    value is 2^53 or more, a non-string object key, or a string (key or value)
    with a lone surrogate. The error carries the JSON path of the value.
    """
    if isinstance(obj, int) and not isinstance(obj, bool):
        _check_integer_range(obj, path)
    elif _is_float(obj):
        raise CanonicalizationError(
            "float_not_allowed",
            f"Float value {obj} encountered",
            path,
        )
    elif isinstance(obj, str):
        _check_string(obj, path)
    elif isinstance(obj, dict):
        for key, value in obj.items():
            _check_key(key, path)
            _check_no_floats(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            _check_no_floats(value, f"{path}[{idx}]")


def validate_canonical(obj: Any, path: str = "$") -> None:
    """
    Check obj against the value rules of canonicalize() without serializing it.

    Raises CanonicalizationError (floats, out-of-range integers, non-string keys,
    lone surrogates) with the JSON path of the value, prefixed by ``path``.
    """
    _check_no_floats(obj, path)


def _sort_keys_by_utf16(obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sort dictionary keys by UTF-16 code units (RFC 8785 §3.2.3).

    Python's default sort is by Unicode code point, which differs for characters
    outside the Basic Multilingual Plane (above U+FFFF) or in the private use
    area (U+E000–U+FFFF).
    """
    try:
        sorted_keys = sorted(obj.keys(), key=lambda k: k.encode("utf-16-be"))
    except UnicodeEncodeError:
        # Lone surrogates cannot be encoded; reject them
        raise CanonicalizationError(
            "invalid_string",
            "String contains lone surrogates",
            "$",
        )
    return {k: obj[k] for k in sorted_keys}


def _canonical_string(s: str) -> List[str]:
    r"""
    Escape a string exactly as ECMAScript JSON.stringify (pieces, without quotes).

    Used for object keys and string values alike. A lone surrogate raises
    CanonicalizationError (``invalid_string``).

    Per RFC 8785:
    - \" for quotation mark (U+0022)
    - \\ for reverse solidus (U+005C)
    - \b for backspace (U+0008)
    - \f for form feed (U+000C)
    - \n for line feed (U+000A)
    - \r for carriage return (U+000D)
    - \t for tab (U+0009)
    - \uXXXX (lowercase hex) for U+0000 to U+001F
    - U+2028 (line separator) and U+2029 (paragraph separator) as-is (JSON allows them)
    - All other code points literal
    """
    result = []
    for ch in s:
        code = ord(ch)
        if ch == '"':
            result.append('\\"')
        elif ch == "\\":
            result.append("\\\\")
        elif ch == "\b":
            result.append("\\b")
        elif ch == "\f":
            result.append("\\f")
        elif ch == "\n":
            result.append("\\n")
        elif ch == "\r":
            result.append("\\r")
        elif ch == "\t":
            result.append("\\t")
        elif code < 0x0020:
            # Control characters U+0000 to U+001F
            result.append(f"\\u{code:04x}")
        elif 0xD800 <= code <= 0xDFFF:
            # Python strings hold code points, so any surrogate here is a lone one
            raise CanonicalizationError(
                "invalid_string",
                "String contains lone surrogates",
                "$",
            )
        else:
            # U+0020 and above, including U+2028 and U+2029
            result.append(ch)
    return result


def _quoted(s: str) -> str:
    """A JSON string literal: quotes around the escaped text (keys and values)."""
    return '"' + "".join(_canonical_string(s)) + '"'


class CanonicalJSONEncoder(json.JSONEncoder):
    """
    Custom JSON encoder that produces RFC 8785 canonical JSON (subset).

    Enforces:
    - No floats (raises CanonicalizationError)
    - Object keys sorted by UTF-16
    - No whitespace
    - Exact string escaping per RFC 8785
    """

    def encode(self, o: Any) -> str:
        """Encode to canonical JSON string."""
        return self._encode_value(o)

    def _encode_value(self, obj: Any) -> str:
        """Encode a single value canonically."""
        if obj is None:
            return "null"
        elif obj is True:
            return "true"
        elif obj is False:
            return "false"
        elif isinstance(obj, str):
            return _quoted(obj)
        elif isinstance(obj, int):
            # canonicalize() checks the whole tree first, with real paths; this
            # guards direct use of the encoder.
            _check_integer_range(obj, "$")
            return str(obj)
        elif isinstance(obj, dict):
            for key in obj:
                _check_key(key, "$")
            sorted_dict = _sort_keys_by_utf16(obj)
            # Keys are escaped exactly like string values (ADR, Decision 1)
            items = [
                f"{_quoted(k)}:{self._encode_value(v)}"
                for k, v in sorted_dict.items()
            ]
            return "{" + ",".join(items) + "}"
        elif isinstance(obj, list):
            items = [self._encode_value(v) for v in obj]
            return "[" + ",".join(items) + "]"
        else:
            raise CanonicalizationError(
                "unsupported_type",
                f"Type {type(obj).__name__} not supported in canonical JSON",
                "$",
            )


def canonicalize(obj: Any) -> bytes:
    """
    Serialize obj to canonical JSON (RFC 8785 subset) as UTF-8 bytes.

    Args:
        obj: The object to serialize. Must not contain floats, lone surrogates,
             or unsupported types.

    Returns:
        UTF-8 encoded canonical JSON bytes (no BOM).

    Raises:
        CanonicalizationError: If obj contains floats, invalid strings, or
                              unsupported types.
    """
    # Check for floats before encoding
    _check_no_floats(obj, "$")

    # Encode to canonical form
    encoder = CanonicalJSONEncoder()
    canonical_str = encoder.encode(obj)

    # Return as UTF-8 bytes (no BOM)
    return canonical_str.encode("utf-8")


def canonicalize_to_string(obj: Any) -> str:
    """
    Serialize obj to canonical JSON (RFC 8785 subset) as a string.

    Args:
        obj: The object to serialize. Must not contain floats, lone surrogates,
             or unsupported types.

    Returns:
        Canonical JSON string.

    Raises:
        CanonicalizationError: If obj contains floats, invalid strings, or
                              unsupported types.
    """
    # Check for floats before encoding
    _check_no_floats(obj, "$")

    # Encode to canonical form
    encoder = CanonicalJSONEncoder()
    return encoder.encode(obj)
