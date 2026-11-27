"""Pure reconciler for Compliance Templates — materialization on edit.

Given an active template's fields and the set of field_ids that already have
stored rows for an entity, the reconciler decides: for each field with NO
existing row AND a non-empty default, propose writing a default row. Existing
rows are NEVER touched. Idempotent: running again over the post-reconcile
field-id set yields no new actions.

This module is deliberately pure (no DB/HTTP) so it can be exhaustively
unit-tested and reused in multiple wiring contexts.

See PRD #676: *Materialization, reconciliation, freezing*.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from src.common.compliance_value_types import is_set


@dataclass(frozen=True)
class FieldDesc:
    """Minimal field description the reconciler needs (decoupled from ORM/Pydantic)."""
    field_id: UUID
    value_type: str
    default_value: Any = None


@dataclass(frozen=True)
class ReconcileAction:
    """A single reconcile action: insert a default value for a field."""
    field_id: UUID
    value: Any


def reconcile(
    fields: list[FieldDesc],
    existing_field_ids: set[UUID],
) -> list[ReconcileAction]:
    """Propose default rows for fields lacking stored values.

    Args:
        fields: All fields in the active template.
        existing_field_ids: Set of field_ids that already have stored value rows
                           for the entity. Fields in this set are NEVER touched.

    Returns:
        A list of ReconcileActions. Each action represents a default value that
        should be inserted as a new row (only for fields not in existing_field_ids).
        Existing rows are NEVER in the action set (reconcile never modifies them).

    Semantics:
        - For each field: if it has NO existing row AND a non-empty default,
          propose a row insert.
        - Mandatory fields with no default are left pending (no row proposed).
        - Idempotent: running reconcile again over the post-reconcile field-id
          set yields zero actions.
    """
    actions: list[ReconcileAction] = []

    for field in fields:
        # Skip fields that already have a stored row — existing rows are frozen.
        if field.field_id in existing_field_ids:
            continue

        # Check if the field has a non-empty default.
        if is_set(field.value_type, field.default_value):
            actions.append(
                ReconcileAction(field_id=field.field_id, value=field.default_value)
            )

    return actions
