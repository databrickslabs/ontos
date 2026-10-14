"""Deprecation lifecycle fields on data products and data contracts.

Moving to ``deprecated`` requires a reason; the sunset date can't be in the
past, and the replacement must be another existing, non-retired entity of the
same type. Moving from ``deprecated`` back to ``active`` clears
``deprecated_at`` and ``sunset_date``; the change log keeps the previous
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
    if details.sunset_date and details.sunset_date < date.today():
        raise ValueError(f"The sunset date {details.sunset_date} is in the past")
    if details.replacement_id:
        if details.replacement_id == entity_id:
            raise ValueError("An entity can't be its own replacement")
        replacement = db.get(_entity_model(entity_type), details.replacement_id)
        if not replacement:
            raise ValueError(f"Replacement {details.replacement_id} not found")
        if (replacement.status or '').lower() == 'retired':
            raise ValueError(f"Replacement {details.replacement_id} is retired")


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


def set_lifecycle_columns(entity_db, entity_type: str, props: Dict[str, Any]) -> None:
    """Set the lifecycle columns from imported properties; unparseable dates are skipped."""
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
            logger.warning("Skipping invalid %s %r on import", prop, value)
            continue
        setattr(entity_db, column, value)
