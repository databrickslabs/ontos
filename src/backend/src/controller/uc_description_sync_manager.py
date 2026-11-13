"""Write the description of a table, view or column asset to Unity Catalog (#1477).

With the ``UC_DESCRIPTION_WRITEBACK_ENABLED`` setting on, saving the
description of a Databricks Table, View or Column asset in Ontos also sets
its Unity Catalog comment, as the user (on-behalf-of client only), so Unity
Catalog permissions decide.

A comment is replaced only when it is still the one Ontos already agreed to:
empty, equal to the new description, or equal to the description before the
save. Any other comment (e.g. one written by a customer in Unity Catalog) is
kept, and the save gets a coded warning. A failed write never fails the save:
the asset keeps the reason in an internal property (shown as "not in sync
with Unity Catalog") until a later write succeeds.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from src.common.api_errors import CodedValueError
from src.common.config import Settings
from src.common.logging import get_logger
from src.common.uc_comments import (
    CommentWriteError, NOT_FOUND, PERMISSION_DENIED, UNSUPPORTED_TEXT,
    read_comment, set_comment, split_column_location,
)
from src.db_models.assets import AssetDb
from src.models.assets import (
    DESCRIPTION_SYNC_PROPERTY, CodedWarning, DescriptionSyncState, description_sync_state,
)

logger = get_logger(__name__)

# Ontos asset types whose description is a Unity Catalog table comment
_TABLE_TYPES = frozenset({'table', 'view'})  # lower case: a CSV's asset_type may differ in case
_COLUMN_TYPE = 'column'
# Unity Catalog table type of a metric view: its comment is not written (#1263)
METRIC_VIEW_TABLE_TYPE = 'METRIC_VIEW'

# Warning codes (the UI translates them; params: ``object``)
CODE_PERMISSION_DENIED = 'uc_description_permission_denied'
CODE_NOT_FOUND = 'uc_description_object_not_found'
CODE_USER_TOKEN_REQUIRED = 'uc_description_user_token_required'
CODE_NO_WAREHOUSE = 'uc_description_no_warehouse'
CODE_WRITE_FAILED = 'uc_description_write_failed'
CODE_UNSUPPORTED_TEXT = 'uc_description_unsupported_text'
# Unity Catalog already has another comment on the object, which the save keeps
CODE_EXISTING_COMMENT = 'uc_description_existing_comment'
# Bulk import: a row over the import's write limit (params: object, limit), a row
# after the import's time budget for Unity Catalog writes (params: object), and the
# writes of a whole import not run (no params)
CODE_IMPORT_WRITE_LIMIT = 'uc_description_import_write_limit'
CODE_IMPORT_TIME_BUDGET = 'uc_description_import_time_budget'
CODE_IMPORT_WRITES_FAILED = 'uc_description_import_writes_failed'
# Import preview only: the row's description is written to Unity Catalog on import
CODE_IMPORT_WRITES_UC = 'uc_description_import_writes_uc'

_MESSAGES = {
    CODE_PERMISSION_DENIED: (
        "Unity Catalog refused to change the description of {object} "
        "(MODIFY permission or ownership needed)."
    ),
    CODE_NOT_FOUND: (
        "{object} was not found in Unity Catalog, or you don't have access to it, "
        "so its description was not written there."
    ),
    CODE_USER_TOKEN_REQUIRED: (
        "The request had no Databricks user token, so the description of {object} "
        "was not written to Unity Catalog."
    ),
    CODE_NO_WAREHOUSE: (
        "No SQL warehouse is configured, so the description of {object} "
        "was not written to Unity Catalog."
    ),
    CODE_WRITE_FAILED: "Writing the description of {object} to Unity Catalog failed.",
    CODE_UNSUPPORTED_TEXT: (
        "The description of {object} has a character Unity Catalog can't store, "
        "so it was not written there."
    ),
    CODE_EXISTING_COMMENT: (
        "Unity Catalog already has another comment on {object}, so the description was not "
        "written there. Set the description to that comment, or change the comment in Unity "
        "Catalog, and save again."
    ),
    CODE_IMPORT_WRITE_LIMIT: (
        "This import reached its limit of {limit} descriptions written to Unity Catalog, "
        "so the description of {object} was not written there."
    ),
    CODE_IMPORT_TIME_BUDGET: (
        "This import ran out of time for Unity Catalog writes, so the description of {object} "
        "was not written there."
    ),
    CODE_IMPORT_WRITES_FAILED: (
        "The assets were imported, but their descriptions could not be written to "
        "Unity Catalog."
    ),
    CODE_IMPORT_WRITES_UC: (
        "The description of {object} will be written to Unity Catalog. If it already has a "
        "different comment there, that comment is kept and the row gets a warning."
    ),
}

# Codes of the ``CodedValueError`` a user client factory raises -> warning codes
_CLIENT_ERROR_CODES = {
    'user_token_required': CODE_USER_TOKEN_REQUIRED,
    CODE_IMPORT_WRITE_LIMIT: CODE_IMPORT_WRITE_LIMIT,
    CODE_IMPORT_TIME_BUDGET: CODE_IMPORT_TIME_BUDGET,
}


class ImportWriteLimitError(CodedValueError):
    """A bulk import already wrote as many descriptions as its limit allows."""

    code = CODE_IMPORT_WRITE_LIMIT


class ImportTimeBudgetError(CodedValueError):
    """A bulk import used up its time for Unity Catalog writes."""

    code = CODE_IMPORT_TIME_BUDGET

_REASON_CODES = {
    PERMISSION_DENIED: CODE_PERMISSION_DENIED,
    NOT_FOUND: CODE_NOT_FOUND,
    UNSUPPORTED_TEXT: CODE_UNSUPPORTED_TEXT,
}


def uc_comment_target_for(
    platform: Optional[str], type_name: Optional[str], location: Optional[str],
) -> Optional[Tuple[str, Optional[str]]]:
    """``(table_fqn, column_name)`` of the Unity Catalog object for an asset's fields, or None.

    Only Databricks assets: a Table or View located at ``catalog.schema.name``,
    or a Column located at ``catalog.schema.table.column``.
    """
    if (platform or '').strip().lower() != 'databricks':
        return None
    location = (location or '').strip()
    type_name = (type_name or '').strip().lower()
    if type_name in _TABLE_TYPES:
        parts = location.split('.')
        if len(parts) == 3 and all(parts):
            return location, None
    elif type_name == _COLUMN_TYPE:
        return split_column_location(location)
    return None


def uc_comment_target(asset: AssetDb) -> Optional[Tuple[str, Optional[str]]]:
    """``uc_comment_target_for`` of a saved asset."""
    return uc_comment_target_for(
        asset.platform, getattr(asset.asset_type, 'name', None), asset.location)


def _warning(code: str, target: str, **params: Any) -> CodedWarning:
    params = {'object': target, **params}
    return CodedWarning(code=code, message=_MESSAGES[code].format(**params), params=params)


def write_failed_warning(target: str) -> CodedWarning:
    return _warning(CODE_WRITE_FAILED, target)


def import_writes_failed_warning() -> CodedWarning:
    return CodedWarning(code=CODE_IMPORT_WRITES_FAILED,
                        message=_MESSAGES[CODE_IMPORT_WRITES_FAILED])


def import_writes_uc_warning(target: str) -> CodedWarning:
    return _warning(CODE_IMPORT_WRITES_UC, target)


@dataclass
class SyncOutcome:
    """What a save did about Unity Catalog.

    ``warning``: why the description is not in Unity Catalog (None when it is, or none was tried).
    ``state``: the mark stored on the asset afterwards.
    ``in_sync``: Unity Catalog holds the saved description now (written, or already equal).
    ``audit``: ``before`` / ``after`` Unity Catalog comments and the ``outcome``
    (written, unchanged, refused, failed) when Unity Catalog was read.
    """
    warning: Optional[CodedWarning] = None
    state: Optional[DescriptionSyncState] = None
    in_sync: bool = False
    audit: Optional[Dict[str, Any]] = None


class UcDescriptionSyncManager:
    def __init__(self, settings: Settings):
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return bool(getattr(self._settings, 'UC_DESCRIPTION_WRITEBACK_ENABLED', False))

    def sync_after_update(
        self,
        db: Session,
        asset_id: Any,
        *,
        description_sent: bool,
        previous_description: Optional[str],
        user_client: Callable[[], Any],
    ) -> SyncOutcome:
        """Bring a saved description to Unity Catalog; returns the ``SyncOutcome``.

        Runs on the committed save. The asset row is locked (``FOR UPDATE``) until
        the caller commits, so two saves of one asset write Unity Catalog one
        after the other, and the last write is the last committed description.
        Does not commit: the caller commits (with the column snapshot, if any).

        Writes when the setting is on, the asset is a Unity Catalog table, view
        or column (not a metric view), and the description changed from
        ``previous_description`` (or the asset is already out of sync, so saving
        again retries). With the setting off, a save drops the mark.
        ``user_client`` builds the user's workspace client; a ``CodedValueError``
        from it (no user token, time budget) is a warning.
        """
        asset = (
            db.query(AssetDb).filter(AssetDb.id == asset_id)
            .with_for_update().populate_existing().one_or_none()
        )
        if asset is None:
            return SyncOutcome()
        current_state = self._stored_state(asset)
        if not self.enabled:
            # Nothing is written to Unity Catalog, so an older mark is dropped on save
            if current_state is not None:
                self._store_state(db, asset, None)
            return SyncOutcome()
        if not description_sent:
            return SyncOutcome(state=current_state)
        target = uc_comment_target(asset)
        if target is None:
            return SyncOutcome(state=current_state)
        text = asset.description or None
        if text == (previous_description or None) and current_state is None:
            return SyncOutcome()

        table_fqn, column_name = target
        label = f'{table_fqn}.{column_name}' if column_name else table_fqn
        if text and '\x00' in text:
            warning = _warning(CODE_UNSUPPORTED_TEXT, label)
            return SyncOutcome(warning, self._store_state(db, asset, warning))
        warehouse_id = getattr(self._settings, 'DATABRICKS_WAREHOUSE_ID', None)
        if not warehouse_id:
            warning = _warning(CODE_NO_WAREHOUSE, label)
            return SyncOutcome(warning, self._store_state(db, asset, warning))
        try:
            ws = user_client()
        except CodedValueError as e:
            logger.info("No user client to write the description of %s: %s", label, e.code)
            code = _CLIENT_ERROR_CODES.get(e.code, CODE_WRITE_FAILED)
            params = e.params if code == CODE_IMPORT_WRITE_LIMIT else {}
            warning = _warning(code, label, **params)
            return SyncOutcome(warning, self._store_state(db, asset, warning))

        try:
            table_type, uc_comment = read_comment(ws, table_fqn, column_name)
        except CommentWriteError as e:
            logger.warning("Reading the comment of %s to write asset %s failed: %s",
                           label, asset.id, e.reason)
            warning = _warning(_REASON_CODES.get(e.reason, CODE_WRITE_FAILED), label)
            audit = {'before': None, 'after': text, 'outcome': 'failed'}
            return SyncOutcome(warning, self._store_state(db, asset, warning), audit=audit)
        if table_type == METRIC_VIEW_TABLE_TYPE:
            logger.info("Not writing the description of asset %s: %s is a metric view",
                        asset.id, label)
            return SyncOutcome(state=current_state)

        audit = {'before': uc_comment, 'after': text, 'outcome': None}
        # The comment Ontos agreed to on an earlier failed write (still in Unity Catalog)
        stored = (asset.properties or {}).get(DESCRIPTION_SYNC_PROPERTY)
        agreed = stored.get('agreed') if isinstance(stored, dict) else None
        if uc_comment == text:
            audit['outcome'] = 'unchanged'
            return SyncOutcome(None, self._store_state(db, asset, None), in_sync=True, audit=audit)
        if (uc_comment is not None and uc_comment != (previous_description or None)
                and uc_comment != agreed):
            # Not the comment Ontos agreed to before: a comment someone else wrote is kept
            logger.info("Kept the Unity Catalog comment of %s: it differs from the Ontos one "
                        "(asset %s)", label, asset.id)
            warning = _warning(CODE_EXISTING_COMMENT, label)
            audit.update(after=uc_comment, outcome='refused')
            return SyncOutcome(warning, self._store_state(db, asset, warning), audit=audit)

        try:
            set_comment(ws, warehouse_id, table_fqn, column_name, text)
        except CommentWriteError as e:
            logger.warning("Writing the description of asset %s to Unity Catalog failed: %s",
                           asset.id, e.reason)
            warning = _warning(_REASON_CODES.get(e.reason, CODE_WRITE_FAILED), label)
            audit.update(after=uc_comment, outcome='failed')
            # The comment still there was agreed to (it passed the guard), so a retry may replace it
            return SyncOutcome(warning, self._store_state(db, asset, warning, agreed=uc_comment),
                               audit=audit)
        logger.info("Wrote the description of asset %s to Unity Catalog (%s)", asset.id, label)
        audit['outcome'] = 'written'
        return SyncOutcome(None, self._store_state(db, asset, None), in_sync=True, audit=audit)

    @staticmethod
    def _stored_state(asset: AssetDb) -> Optional[DescriptionSyncState]:
        return description_sync_state(asset.properties)

    @staticmethod
    def _store_state(
        db: Session, asset: AssetDb, warning: Optional[CodedWarning],
        agreed: Optional[str] = None,
    ) -> Optional[DescriptionSyncState]:
        properties: Dict[str, Any] = dict(asset.properties or {})
        state = None
        if warning is None:
            properties.pop(DESCRIPTION_SYNC_PROPERTY, None)
        else:
            state = DescriptionSyncState(
                code=warning.code, message=warning.message, params=warning.params,
                at=datetime.now(timezone.utc),
            )
            stored = state.model_dump(mode='json')
            if agreed is not None:
                # Internal: not part of the API state (description_sync_state ignores it)
                stored['agreed'] = agreed
            properties[DESCRIPTION_SYNC_PROPERTY] = stored
        if properties != (asset.properties or {}):
            # A new dict, so the JSON column is seen as changed
            asset.properties = properties or None
            db.flush()
        return state
