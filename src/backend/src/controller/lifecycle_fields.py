"""Deprecation lifecycle fields on data products and data contracts.

Moving to ``deprecated`` requires a reason; the sunset date can't be in the
past (in UTC), and the replacement must be another existing entity of the same
type that is neither deprecated nor retired, and whose replacement chain
doesn't lead back to the entity. Moving from ``deprecated`` back to ``active``
clears ``deprecated_at`` and ``sunset_date``; the change log keeps the previous
values. See the lifecycle tag automation and deprecation PRD.
"""
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from src.common.logging import get_logger

logger = get_logger(__name__)

_REPLACEMENT_COLUMN = {
    'data_product': 'replacement_product_id',
    'data_contract': 'replacement_contract_id',
}


@dataclass
class DeprecationDetails:
    """What the caller provides when deprecating an entity."""
    reason: Optional[str] = None
    sunset_date: Optional[date] = None
    replacement_id: Optional[str] = None


def _entity_model(entity_type: str):
    if entity_type == 'data_product':
        from src.db_models.data_products import DataProductDb
        return DataProductDb
    from src.db_models.data_contracts import DataContractDb
    return DataContractDb


def requested_status_change_justification(
    db: Session, entity_type: str, entity_id: str, target_status: Optional[str] = None
) -> Optional[str]:
    """Justification of the latest status change request (to ``target_status``,
    when given), used as the deprecation reason when that request is approved."""
    from src.controller.change_log_manager import change_log_manager

    try:
        changes = change_log_manager.list_changes_for_entity(
            db, entity_type=entity_type, entity_id=entity_id
        )
    except Exception as e:
        logger.warning("Could not read status change requests for %s %s: %s",
                       entity_type, entity_id, e)
        return None
    for change in changes:  # newest first
        if change.action != 'status_change_requested':
            continue
        try:
            details = json.loads(change.details_json or '{}') or {}
        except ValueError:
            continue
        requested = (details.get('target_status') or '').lower()
        if target_status and requested and requested != target_status.lower():
            continue
        return details.get('justification')
    return None


def utc_today() -> date:
    """Today in UTC, the date sunset dates are checked against (the UI uses it too)."""
    return datetime.now(timezone.utc).date()


def _check_replacement(
    db: Session, entity_type: str, entity_id: str, replacement_id: str, *, imported: bool = False,
) -> None:
    """Raise ValueError if ``replacement_id`` can't replace ``entity_id``.

    The replacement must exist and must not lead back to the entity through the
    replacement links of deprecated or retired entities (a cycle). A deprecated
    or retired replacement is refused too, except for an ``imported`` entity: an
    export can hold one legitimately (A deprecated toward B, then B deprecated).
    """
    if replacement_id == entity_id:
        raise ValueError("An entity can't be its own replacement")
    model = _entity_model(entity_type)
    replacement = db.get(model, replacement_id)
    if not replacement:
        raise ValueError(f"Replacement {replacement_id} not found")
    column = _REPLACEMENT_COLUMN[entity_type]
    # Follow the links in effect: those of deprecated or retired entities
    chain = [entity_id, replacement_id]
    current = replacement
    while current is not None and (current.status or '').lower() in ('deprecated', 'retired'):
        next_id = getattr(current, column, None)
        if not next_id:
            break
        if next_id == entity_id:
            raise ValueError(
                f"Replacement {replacement_id} leads back to this entity: "
                + ' -> '.join(chain + [entity_id])
            )
        if next_id in chain:
            break  # a cycle among other entities, not through this one
        chain.append(next_id)
        current = db.get(model, next_id)
    if imported:
        return
    status = (replacement.status or '').lower()
    if status == 'retired':
        raise ValueError(f"Replacement {replacement_id} is retired")
    if status == 'deprecated':
        message = f"Replacement {replacement_id} is deprecated"
        if current is not None and current is not replacement and (
            (current.status or '').lower() not in ('deprecated', 'retired')
        ):
            message += f"; it is replaced by {' -> '.join(chain[2:])}"
        raise ValueError(message)


def check_lifecycle_fields(
    db: Session,
    entity_type: str,
    entity_id: str,
    new_status: str,
    details: Optional[DeprecationDetails],
) -> None:
    """Raise ValueError if the deprecation details don't allow ``new_status``.

    Called before the transition's gates run, so nothing is written yet.
    """
    if new_status != 'deprecated':
        return
    details = details or DeprecationDetails()
    if not (details.reason or '').strip():
        raise ValueError("A deprecation reason is required to deprecate")
    if details.sunset_date and details.sunset_date < utc_today():
        raise ValueError(f"The sunset date {details.sunset_date} is in the past")
    if details.replacement_id:
        _check_replacement(db, entity_type, entity_id, details.replacement_id)


def apply_lifecycle_fields(
    entity_db,
    entity_type: str,
    current_status: str,
    new_status: str,
    details: Optional[DeprecationDetails],
) -> Dict[str, Any]:
    """Set the lifecycle fields for a checked transition (no commit).

    Returns what changed, for the change log (empty when nothing did).
    """
    replacement_column = _REPLACEMENT_COLUMN[entity_type]
    if new_status == 'deprecated':
        details = details or DeprecationDetails()
        entity_db.deprecation_reason = details.reason.strip()
        entity_db.sunset_date = details.sunset_date
        setattr(entity_db, replacement_column, details.replacement_id or None)
        entity_db.deprecated_at = datetime.now(timezone.utc)
        return {
            'deprecation_reason': entity_db.deprecation_reason,
            'sunset_date': details.sunset_date.isoformat() if details.sunset_date else None,
            replacement_column: details.replacement_id or None,
        }
    if current_status == 'deprecated' and new_status == 'active':
        previous = {
            'previous_sunset_date': (
                entity_db.sunset_date.isoformat() if entity_db.sunset_date else None
            ),
            'previous_deprecated_at': (
                entity_db.deprecated_at.isoformat() if entity_db.deprecated_at else None
            ),
        }
        entity_db.sunset_date = None
        entity_db.deprecated_at = None
        return previous
    return {}


# ODPS / ODCS round-trip: the fields travel as reserved customProperties, like
# ontosEntityId / ontosOriginalId.
_PROPERTY_COLUMNS = {
    'ontosDeprecationReason': 'deprecation_reason',
    'ontosSunsetDate': 'sunset_date',
    'ontosReplacedBy': None,  # replacement_product_id / replacement_contract_id
    'ontosDeprecatedAt': 'deprecated_at',
}


def lifecycle_custom_properties(entity, entity_type: str) -> Dict[str, str]:
    """The entity's lifecycle fields as ``{property: value}`` for an export.

    Only set fields, and only while the entity is deprecated or retired: after
    a reactivation the kept reason / replacement describe a past deprecation.
    """
    if (getattr(entity, 'status', None) or '').lower() not in ('deprecated', 'retired'):
        return {}
    props = {}
    for prop, column in _PROPERTY_COLUMNS.items():
        value = getattr(entity, column or _REPLACEMENT_COLUMN[entity_type], None)
        if value:
            props[prop] = value.isoformat() if hasattr(value, 'isoformat') else str(value)
    return props


def pop_lifecycle_custom_properties(custom_props) -> Dict[str, Any]:
    """Remove the lifecycle properties from an imported ``customProperties``
    (ODCS / ODPS list form or legacy dict form) and return them."""
    found: Dict[str, Any] = {}
    if isinstance(custom_props, list):
        for item in list(custom_props):
            if isinstance(item, dict) and item.get('property') in _PROPERTY_COLUMNS:
                found[item['property']] = item.get('value')
                custom_props.remove(item)
    elif isinstance(custom_props, dict):
        for prop in list(custom_props):
            if prop in _PROPERTY_COLUMNS:
                found[prop] = custom_props.pop(prop)
    return found


def imported_lifecycle_columns(
    db: Session, entity_type: str, entity_id: str, props: Dict[str, Any],
) -> Dict[str, Any]:
    """Column values for the lifecycle properties of an imported entity.

    Raises ValueError (naming the property) for a date that doesn't parse and
    for a replacement that is the entity itself, doesn't exist, or leads back
    to the entity. An import describes the entity as it was exported, so a
    past sunset date, a deprecated or retired replacement and a deprecated
    entity without a reason (exported before these fields existed) are kept.
    """
    columns: Dict[str, Any] = {}
    for prop, value in props.items():
        if value in (None, ''):
            continue
        column = _PROPERTY_COLUMNS[prop] or _REPLACEMENT_COLUMN[entity_type]
        try:
            if column == 'sunset_date':
                value = date.fromisoformat(str(value)[:10])
            elif column == 'deprecated_at':
                value = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            else:
                value = str(value)
        except ValueError:
            raise ValueError(f"Invalid {prop} {value!r}: expected an ISO date") from None
        columns[column] = value
    replacement_id = columns.get(_REPLACEMENT_COLUMN[entity_type])
    if replacement_id:
        try:
            _check_replacement(db, entity_type, entity_id, replacement_id, imported=True)
        except ValueError as e:
            raise ValueError(f"Invalid ontosReplacedBy: {e}") from None
    return columns


def set_lifecycle_columns(entity_db, columns: Dict[str, Any]) -> None:
    """Set the lifecycle columns checked by ``imported_lifecycle_columns``."""
    for column, value in columns.items():
        setattr(entity_db, column, value)
