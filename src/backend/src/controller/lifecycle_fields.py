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

from src.common.api_errors import CodedValueError
from src.common.logging import get_logger

logger = get_logger(__name__)

_REPLACEMENT_COLUMN = {
    'data_product': 'replacement_product_id',
    'data_contract': 'replacement_contract_id',
}


class LifecycleFieldError(CodedValueError):
    """A deprecation the details don't allow; the UI translates ``code``
    (``common:deprecation.errors.<code>``), the message is the fallback."""

    def __init__(self, message: str, code: str, **params: Any):
        super().__init__(message, **params)
        self.code = code


class ImportedLifecycleError(ValueError):
    """Lifecycle properties of an imported entity that can't be stored.

    The message is written by the app (no SQL or internal text), so a batch
    import shows it for the entity that failed; the UI translates ``code``
    (``common:deprecation.import.<code>``) with ``params``.
    """

    def __init__(self, message: str, code: str, **params: Any):
        super().__init__(message)
        self.code = code
        self.params = params


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
        raise LifecycleFieldError("An entity can't be its own replacement", 'replacement_is_self')
    model = _entity_model(entity_type)
    replacement = db.get(model, replacement_id)
    if not replacement:
        raise LifecycleFieldError(
            f"Replacement {replacement_id} not found", 'replacement_not_found',
            replacementId=replacement_id,
        )
    column = _REPLACEMENT_COLUMN[entity_type]
    # Follow the links in effect: those of deprecated or retired entities
    chain = [entity_id, replacement_id]
    current = replacement
    while current is not None and (current.status or '').lower() in ('deprecated', 'retired'):
        next_id = getattr(current, column, None)
        if not next_id:
            break
        if next_id == entity_id:
            path = ' -> '.join(chain + [entity_id])
            raise LifecycleFieldError(
                f"Replacement {replacement_id} leads back to this entity: {path}",
                'replacement_leads_back', replacementId=replacement_id, chain=path,
            )
        if next_id in chain:
            break  # a cycle among other entities, not through this one
        chain.append(next_id)
        current = db.get(model, next_id)
    if imported:
        return
    status = (replacement.status or '').lower()
    if status == 'retired':
        raise LifecycleFieldError(
            f"Replacement {replacement_id} is retired", 'replacement_retired',
            replacementId=replacement_id,
        )
    if status == 'deprecated':
        message = f"Replacement {replacement_id} is deprecated"
        if current is not None and current is not replacement and (
            (current.status or '').lower() not in ('deprecated', 'retired')
        ):
            replaced_by = ' -> '.join(chain[2:])
            raise LifecycleFieldError(
                f"{message}; it is replaced by {replaced_by}", 'replacement_deprecated_replaced',
                replacementId=replacement_id, replacedBy=replaced_by,
            )
        raise LifecycleFieldError(message, 'replacement_deprecated', replacementId=replacement_id)


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
        raise LifecycleFieldError(
            "A deprecation reason is required to deprecate", 'deprecation_reason_required',
        )
    if details.sunset_date and details.sunset_date < utc_today():
        raise LifecycleFieldError(
            f"The sunset date {details.sunset_date} is in the past", 'sunset_date_in_past',
            sunsetDate=details.sunset_date.isoformat(),
        )
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


def _source_key(entity_id: Any) -> str:
    return str(entity_id).strip().lower()


@dataclass
class ImportNote:
    """What an import tells about an entity it created (a dropped link)."""
    message: str
    code: str
    params: Dict[str, Any]


class ImportLinks:
    """Replacement links between the entities of one import.

    Ids are regenerated unless adopted, so a replacement is looked up first
    among the entities this import created, by the id the file gives them. A
    replacement imported later in the same import is linked once the whole
    import exists (``finish``); one that isn't in the target at all is not
    linked, and the entity gets a note instead of failing.
    """

    def __init__(self, entity_type: str):
        self.entity_type = entity_type
        self._created: Dict[str, str] = {}
        self._pending: Dict[str, str] = {}

    def record(self, source_id: Optional[str], created_id: str) -> None:
        """Remember that the entity the file calls ``source_id`` is ``created_id``."""
        if source_id:
            self._created[_source_key(source_id)] = created_id

    def resolve(self, replacement_id: str) -> str:
        return self._created.get(_source_key(replacement_id), replacement_id)

    def defer(self, entity_id: str, replacement_id: str) -> None:
        self._pending[entity_id] = replacement_id

    def finish(self, db: Session, username: Optional[str] = None) -> Dict[str, ImportNote]:
        """Link the replacements imported after the entity naming them, with a
        change log entry for each.

        Returns a note for each entity whose replacement isn't linked.
        """
        from src.controller.change_log_manager import change_log_manager

        notes: Dict[str, ImportNote] = {}
        model = _entity_model(self.entity_type)
        column = _REPLACEMENT_COLUMN[self.entity_type]
        for entity_id, replacement_id in self._pending.items():
            target = self._created.get(_source_key(replacement_id))
            entity = db.get(model, entity_id)
            if entity is None:
                continue
            if target:
                try:
                    _check_replacement(db, self.entity_type, entity_id, target, imported=True)
                except LifecycleFieldError as e:
                    code = ('imported_replacement_leads_back' if e.code == 'replacement_leads_back'
                            else 'imported_replacement_dropped')
                    notes[entity_id] = ImportNote(
                        f"ontosReplacedBy {replacement_id} not linked: {e}", code,
                        {**e.params, 'replacementId': replacement_id},
                    )
                    continue
                setattr(entity, column, target)
                db.flush()
                change_log_manager.log_change_with_details(
                    db, entity_type=self.entity_type, entity_id=entity_id, action='UPDATE',
                    username=username,
                    details={column: target, 'summary': 'Replacement linked by the import'},
                )
                continue
            notes[entity_id] = ImportNote(
                f"ontosReplacedBy {replacement_id} not linked: no such entity here",
                'imported_replacement_dropped', {'replacementId': replacement_id},
            )
        db.flush()
        return notes


def add_import_notes(result, notes: Dict[str, ImportNote]) -> None:
    """Put the notes of ``ImportLinks.finish`` on the created items of an import."""
    for item in result.items:
        note = notes.get(item.entity_id) if item.entity_id else None
        if note:
            item.message, item.code, item.params = note.message, note.code, note.params


def imported_lifecycle_columns(
    db: Session, entity_type: str, entity_id: str, props: Dict[str, Any],
    links: Optional[ImportLinks] = None, source_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Column values for the lifecycle properties of an imported entity.

    Raises ImportedLifecycleError (naming the property) for a date that doesn't
    parse and for a replacement that is the entity itself or leads back to it.
    An import describes the entity as it was exported, so a past sunset date,
    a deprecated or retired replacement and a deprecated entity without a
    reason (exported before these fields existed) are kept. With ``links``, a
    replacement is looked up among the entities of the same import first, and
    one that isn't there yet is left to ``links.finish``.
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
            raise ImportedLifecycleError(
                f"Invalid {prop} {value!r}: expected an ISO date", 'imported_date_invalid',
                property=prop, value=str(value),
            ) from None
        columns[column] = value
    replacement_column = _REPLACEMENT_COLUMN[entity_type]
    replacement_id = columns.get(replacement_column)
    if replacement_id:
        if source_id and _source_key(replacement_id) == _source_key(source_id):
            replacement_id = entity_id
        elif links is not None:
            replacement_id = links.resolve(replacement_id)
        try:
            _check_replacement(db, entity_type, entity_id, replacement_id, imported=True)
            columns[replacement_column] = replacement_id
        except LifecycleFieldError as e:
            if e.code == 'replacement_not_found' and links is not None:
                del columns[replacement_column]
                links.defer(entity_id, str(props['ontosReplacedBy']).strip())
            else:
                raise ImportedLifecycleError(
                    f"Invalid ontosReplacedBy: {e}", e.code, **e.params,
                ) from None
    return columns


def set_lifecycle_columns(entity_db, columns: Dict[str, Any]) -> None:
    """Set the lifecycle columns checked by ``imported_lifecycle_columns``."""
    for column, value in columns.items():
        setattr(entity_db, column, value)
