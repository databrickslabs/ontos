"""Pure value-type engine for Compliance Templates.

Holds all validation/coercion and "is-set" semantics for the supported field
value types. No database or HTTP dependencies — this module is deliberately
pure so it can be exhaustively unit-tested (mirrors the compliance-DSL
evaluator).

Value types (see PRD *Value types*):

- ``string``     — any text; empty/whitespace-only counts as unset.
- ``numeric``    — int or float; parsed from numeric strings.
- ``enum``       — a single value drawn from the field's controlled vocabulary.
- ``multi_enum`` — a list (subset) of the controlled vocabulary; unset when empty.
- ``date``       — an ISO-8601 date (``YYYY-MM-DD``); time component tolerated.
- ``range``      — an owner-entered interval ``{"low": n, "high": n}`` with
  ``low <= high``; unset unless BOTH bounds are present.
- ``boolean``    — true/false; explicit ``false`` counts as SET.

Coercion normalizes each accepted input to a canonical stored shape:

- numeric  -> int when integral, else float
- date     -> ``YYYY-MM-DD`` string
- range    -> ``{"low": <num>, "high": <num>}``
- boolean  -> bool
- string / enum -> str
- multi_enum -> list[str]
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Optional


class ComplianceValueType(str, Enum):
    """Canonical value-type identifiers, matching the Pydantic enum."""
    STRING = "string"
    NUMERIC = "numeric"
    ENUM = "enum"
    MULTI_ENUM = "multi_enum"
    DATE = "date"
    RANGE = "range"
    BOOLEAN = "boolean"


class ValueTypeError(ValueError):
    """Raised when a value cannot be validated/coerced against its field type."""


# Accepted string spellings for booleans (case-insensitive).
_TRUE_STRINGS = {"true", "1", "yes", "y", "on"}
_FALSE_STRINGS = {"false", "0", "no", "n", "off"}


def _coerce_numeric(value: Any) -> float | int:
    if isinstance(value, bool):
        # bool is a subclass of int; reject to avoid True -> 1 surprises.
        raise ValueTypeError("Expected a numeric value, got a boolean.")
    if isinstance(value, (int, float)):
        num: float = float(value)
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            raise ValueTypeError("Expected a numeric value, got an empty string.")
        try:
            num = float(s)
        except ValueError:
            raise ValueTypeError(f"'{value}' is not a valid number.")
    else:
        raise ValueTypeError(f"Expected a numeric value, got {type(value).__name__}.")
    # Normalize integral floats to int (2.0 -> 2).
    if num.is_integer():
        return int(num)
    return num


def _coerce_boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in _TRUE_STRINGS:
            return True
        if s in _FALSE_STRINGS:
            return False
    raise ValueTypeError(f"'{value}' is not a valid boolean.")


def _coerce_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        s = value.strip()
        if not s:
            raise ValueTypeError("Expected a date, got an empty string.")
        try:
            # Accept full ISO datetimes but store only the date component.
            return datetime.fromisoformat(s).date().isoformat()
        except ValueError:
            try:
                return date.fromisoformat(s).isoformat()
            except ValueError:
                raise ValueTypeError(f"'{value}' is not a valid ISO date (YYYY-MM-DD).")
    raise ValueTypeError(f"Expected a date, got {type(value).__name__}.")


def _coerce_range(value: Any) -> dict[str, float | int]:
    if not isinstance(value, dict):
        raise ValueTypeError("Range must be an object with 'low' and 'high'.")
    if "low" not in value or "high" not in value:
        raise ValueTypeError("Range must include both 'low' and 'high'.")
    low = _coerce_numeric(value["low"])
    high = _coerce_numeric(value["high"])
    if low > high:
        raise ValueTypeError(f"Range low ({low}) must be <= high ({high}).")
    return {"low": low, "high": high}


def _coerce_enum(value: Any, possible_values: Optional[list[str]]) -> str:
    if not isinstance(value, str):
        raise ValueTypeError(f"Enum value must be a string, got {type(value).__name__}.")
    s = value.strip()
    if not s:
        raise ValueTypeError("Enum value cannot be empty.")
    if not possible_values:
        raise ValueTypeError("Enum field has no controlled vocabulary defined.")
    if s not in possible_values:
        raise ValueTypeError(f"'{s}' is not in the allowed values: {possible_values}.")
    return s


def _coerce_multi_enum(value: Any, possible_values: Optional[list[str]]) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise ValueTypeError("MultiEnum value must be a list.")
    if not possible_values:
        raise ValueTypeError("MultiEnum field has no controlled vocabulary defined.")
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueTypeError(f"MultiEnum items must be strings, got {type(item).__name__}.")
        s = item.strip()
        if s not in possible_values:
            raise ValueTypeError(f"'{s}' is not in the allowed values: {possible_values}.")
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result


def coerce_value(
    value_type: str | ComplianceValueType,
    value: Any,
    possible_values: Optional[list[str]] = None,
) -> Any:
    """Validate and coerce ``value`` for the given field type.

    Returns the canonical stored representation. Raises :class:`ValueTypeError`
    for ill-typed or out-of-vocabulary input. ``None`` passes through as-is
    (an unset value is always permitted at write time — mandatory enforcement
    is a separate concern handled by the completeness validator).
    """
    if value is None:
        return None

    vt = ComplianceValueType(value_type) if not isinstance(value_type, ComplianceValueType) else value_type

    if vt == ComplianceValueType.STRING:
        if not isinstance(value, str):
            raise ValueTypeError(f"Expected a string, got {type(value).__name__}.")
        return value
    if vt == ComplianceValueType.NUMERIC:
        return _coerce_numeric(value)
    if vt == ComplianceValueType.BOOLEAN:
        return _coerce_boolean(value)
    if vt == ComplianceValueType.DATE:
        return _coerce_date(value)
    if vt == ComplianceValueType.RANGE:
        return _coerce_range(value)
    if vt == ComplianceValueType.ENUM:
        return _coerce_enum(value, possible_values)
    if vt == ComplianceValueType.MULTI_ENUM:
        return _coerce_multi_enum(value, possible_values)

    raise ValueTypeError(f"Unknown value type '{value_type}'.")


def is_set(value_type: str | ComplianceValueType, value: Any) -> bool:
    """Return True if ``value`` counts as "set" for completeness purposes.

    Semantics (PRD): Boolean is satisfied by explicit true OR false;
    String/Enum/Date by a non-empty value; MultiEnum by at least one selection;
    Range by both bounds present; Numeric by any number.
    """
    if value is None:
        return False

    vt = ComplianceValueType(value_type) if not isinstance(value_type, ComplianceValueType) else value_type

    if vt == ComplianceValueType.BOOLEAN:
        # Both true and false count as set once a bool is present.
        return isinstance(value, bool)
    if vt == ComplianceValueType.STRING:
        return isinstance(value, str) and value.strip() != ""
    if vt == ComplianceValueType.ENUM:
        return isinstance(value, str) and value.strip() != ""
    if vt == ComplianceValueType.DATE:
        return isinstance(value, str) and value.strip() != ""
    if vt == ComplianceValueType.NUMERIC:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if vt == ComplianceValueType.MULTI_ENUM:
        return isinstance(value, (list, tuple)) and len(value) > 0
    if vt == ComplianceValueType.RANGE:
        return (
            isinstance(value, dict)
            and value.get("low") is not None
            and value.get("high") is not None
        )
    return False
