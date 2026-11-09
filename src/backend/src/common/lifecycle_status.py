"""Lifecycle status checks shared by the create and update paths of products and contracts.

A status change runs through ``transition_status`` (the ``change-status`` and
``request-status-change`` routes), which checks the transition and runs the
``before_status_change`` gates. An update (``PUT``) may only repeat the stored
status, and a new entity starts in one of the lifecycle statuses.
``certified`` is not a status: certification is ``certification_level``, set
by the certify action.
"""
from typing import Any, Dict, Iterable, Optional, Tuple

from src.common.api_errors import CodedValueError
from src.models.lifecycle import DATA_CONTRACT_TRANSITIONS, DATA_PRODUCT_TRANSITIONS

PRODUCT_STATUSES = tuple(DATA_PRODUCT_TRANSITIONS)
CONTRACT_STATUSES = tuple(DATA_CONTRACT_TRANSITIONS)


class StatusChangeRequiresTransitionError(CodedValueError):
    """An update tried to change the status, which only a transition may do."""

    code = 'status_change_requires_transition'

    def __init__(self, from_status: str, to_status: str):
        super().__init__(
            f"An update can't change the status from '{from_status}' to '{to_status}'. "
            "Use the change-status or request-status-change action, which checks the "
            "transition and runs the status change workflows.",
            fromStatus=from_status,
            toStatus=to_status,
        )


class InvalidStatusError(CodedValueError):
    """A status that isn't one of the entity's lifecycle statuses."""

    code = 'invalid_status'

    def __init__(self, status: str, allowed: Iterable[str]):
        allowed = list(allowed)
        super().__init__(
            f"'{status}' is not a lifecycle status. Use one of: {', '.join(allowed)}.",
            status=status,
            allowed=allowed,
        )


class CertifiedIsNotAStatusError(CodedValueError):
    """``certified`` sent as a status; certification is a separate field."""

    code = 'certified_is_not_a_status'

    def __init__(self):
        super().__init__(
            "'certified' is not a status: certification is set with the certify action, "
            "on an active entity."
        )


def _normalized(status: Optional[str]) -> Optional[str]:
    if status is None:
        return None
    value = getattr(status, 'value', status)
    return str(value).strip().lower() or None


def check_status_unchanged(stored: Optional[str], requested: Optional[str]) -> None:
    """Refuse an update whose status differs from the stored one.

    A missing status, or the stored one (in any case), is accepted.
    """
    requested_norm = _normalized(requested)
    if requested_norm is None:
        return
    stored_norm = _normalized(stored) or 'draft'
    if requested_norm != stored_norm:
        raise StatusChangeRequiresTransitionError(stored_norm, requested_norm)


def normalize_new_status(status: Optional[str], allowed: Iterable[str], default: str = 'draft') -> str:
    """The lowercase status of a new entity, or an error for one that isn't a lifecycle status."""
    allowed = tuple(allowed)
    normalized = _normalized(status)
    if normalized is None:
        return default
    if normalized == 'certified':
        raise CertifiedIsNotAStatusError()
    if normalized not in allowed:
        raise InvalidStatusError(normalized, allowed)
    return normalized


IMPORTED_STATUS_MAPPED = 'imported_status_mapped'
IMPORTED_LEGACY_STATUS = 'imported_legacy_status'
IMPORTED_CERTIFIED_AS_ACTIVE = 'imported_certified_as_active'

# Older status names an export can carry, mapped as migration
# b5_lifecycle_status_cleanup maps them in the database.
_LEGACY_IMPORT_STATUSES = {'archived': 'retired'}


def import_status(
    status: Optional[str], allowed: Iterable[str], default: str = 'draft',
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """The status an imported entity starts in, and a note when it isn't the file's.

    ODCS and ODPS define ``status`` as free text, so a valid document from
    another tool can carry a status Ontos doesn't have (``production``,
    ``in development``). Such a status is imported as ``default`` and the
    returned note (``code``, ``params``, English ``message``) says so.

    Older Ontos status names are mapped as migration
    ``b5_lifecycle_status_cleanup`` maps them in the database: ``archived``
    becomes ``retired``, and ``certified`` becomes ``active``. Certification
    is ``certification_level``, which an import never sets, so the note on a
    ``certified`` entity says the certification wasn't imported.
    """
    allowed = tuple(allowed)
    normalized = _normalized(status)
    if normalized is None:
        return default, None
    if normalized in allowed:
        return normalized, None
    original = str(getattr(status, 'value', status)).strip()
    if normalized == 'certified' and 'active' in allowed:
        return 'active', {
            'code': IMPORTED_CERTIFIED_AS_ACTIVE,
            'params': {'status': original, 'mappedTo': 'active'},
            'message': (
                f"'{original}' is not a status any more, so it was imported as 'active'. "
                "Certification isn't imported: certify the entity in Ontos."
            ),
        }
    legacy = _LEGACY_IMPORT_STATUSES.get(normalized)
    if legacy and legacy in allowed:
        return legacy, {
            'code': IMPORTED_LEGACY_STATUS,
            'params': {'status': original, 'mappedTo': legacy},
            'message': (
                f"'{original}' is an older status name, so it was imported as '{legacy}'."
            ),
        }
    return default, {
        'code': IMPORTED_STATUS_MAPPED,
        'params': {'status': original, 'mappedTo': default},
        'message': (
            f"'{original}' is not a lifecycle status, so it was imported as '{default}'."
        ),
    }
