"""Pure completeness validator for Compliance Templates.

Given a template's fields and an entity's stored values, decides whether all
mandatory fields are satisfied and returns a result object with human-readable
failure messages. Pure (no DB/HTTP) so it can be exhaustively unit-tested and
reused by both the advisory-on-edit indicator and the blocking-at-publish check.

Effective-value semantics (PRD): a field's effective value is its stored value
if present, else the field's current default. A mandatory field is satisfied if
a valid value exists OR the field has a non-empty default.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any, Optional

from src.common.compliance_value_types import is_set


@dataclass(frozen=True)
class FieldSpec:
    """Minimal field description the validator needs (decoupled from ORM/Pydantic)."""
    field_id: str
    label: str
    value_type: str
    is_mandatory: bool
    default_value: Any = None


@dataclass
class CompletenessResult:
    """Result of a completeness check.

    ``passed`` is True when every mandatory field is satisfied. ``missing`` lists
    the labels of unsatisfied mandatory fields; ``messages`` holds the
    human-readable failure lines (empty when passed).
    """
    passed: bool
    missing: list[str] = dataclass_field(default_factory=list)
    messages: list[str] = dataclass_field(default_factory=list)


def _effective_is_set(spec: FieldSpec, stored: Any, has_stored: bool) -> bool:
    """True if the field's effective value (stored else default) counts as set."""
    if has_stored and is_set(spec.value_type, stored):
        return True
    # Fall back to the field's current default.
    return is_set(spec.value_type, spec.default_value)


def check_completeness(
    fields: list[FieldSpec],
    stored_values: Optional[dict[str, Any]] = None,
) -> CompletenessResult:
    """Check that all mandatory fields are satisfied.

    ``stored_values`` maps ``field_id`` -> stored value. A field id absent from
    the map is treated as having no stored value (falls back to its default).
    """
    values = stored_values or {}
    missing: list[str] = []
    messages: list[str] = []

    for spec in fields:
        if not spec.is_mandatory:
            continue
        has_stored = spec.field_id in values
        stored = values.get(spec.field_id)
        if not _effective_is_set(spec, stored, has_stored):
            missing.append(spec.label)
            messages.append(f"'{spec.label}' is required but has no value.")

    return CompletenessResult(passed=not missing, missing=missing, messages=messages)
