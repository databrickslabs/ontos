"""The history of an asset's description, kept in the change log.

Every change of the description of a Table, View or Column asset is one
``description_changed`` entry in ``entity_change_log`` with the description
before and after and where the change came from. The entry is flushed in the
caller's transaction (never committed here, never swallowed), so a change and
its entry are stored together or not at all.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Iterator, Optional

from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.controller.change_log_manager import change_log_manager
from src.db_models.assets import AssetDb

logger = get_logger(__name__)

ENTITY_TYPE = 'asset'
ACTION_DESCRIPTION_CHANGED = 'description_changed'

# Where a description change came from (``details.source``). Not an enum: a flow
# that comes later (e.g. an applied LLM suggestion, ``llm``) adds its own value.
SOURCE_MANUAL = 'manual'  # an edit in the UI or the API
SOURCE_UC_IMPORT = 'uc_import'  # the description Unity Catalog had when the asset was imported
SOURCE_BULK_IMPORT = 'bulk_import'  # a CSV / XLSX import
SOURCE_UC_RESET = 'uc_reset'  # "use the Unity Catalog comment"
SOURCE_RESTORE = 'restore'  # an earlier description restored

# The source a change made in the current context is logged with (``description_source``)
_current_source: ContextVar[str] = ContextVar('asset_description_source', default=SOURCE_MANUAL)


@contextmanager
def description_source(source: str) -> Iterator[None]:
    """Log the description changes made inside the ``with`` block with this ``source``.

    ``AssetsManager.create_asset`` / ``update_asset`` take no source argument: a flow other
    than a plain edit (an import, a reset, a restore) says what it is here.
    """
    token = _current_source.set(source)
    try:
        yield
    finally:
        _current_source.reset(token)


def current_description_source() -> str:
    return _current_source.get()


# Asset types whose description is tracked (lower case)
_TRACKED_TYPES = frozenset({'table', 'view', 'column'})


def is_tracked_type(type_name: Optional[str]) -> bool:
    return (type_name or '').strip().lower() in _TRACKED_TYPES


def description_changed(before: Optional[str], after: Optional[str]) -> bool:
    """Whether two descriptions differ (an empty one and none are the same)."""
    return (before or None) != (after or None)


def record_description_change(
    db: Session, asset: AssetDb, *, before: Optional[str], after: Optional[str],
    source: str, username: Optional[str], extra: Optional[Dict[str, Any]] = None,
) -> bool:
    """Log that the description of ``asset`` went from ``before`` to ``after``.

    Does nothing (False) for an asset type that isn't tracked or when the text did
    not change. Flushes the entry without committing; an error is raised, not logged.
    """
    type_name = getattr(asset.asset_type, 'name', None)
    if not is_tracked_type(type_name) or not description_changed(before, after):
        return False
    details: Dict[str, Any] = {
        'name': asset.name,
        'object_type': (type_name or '').strip().lower(),
        'location': asset.location,
        'before': before or None,
        'after': after or None,
        'source': source,
    }
    if extra:
        details.update(extra)
    change_log_manager.log_change_with_details(
        db, entity_type=ENTITY_TYPE, entity_id=str(asset.id),
        action=ACTION_DESCRIPTION_CHANGED, username=username, details=details, commit=False,
    )
    return True
