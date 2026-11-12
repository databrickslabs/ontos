"""Write the description of a table, view or column asset to Unity Catalog (#1477).

With the ``UC_DESCRIPTION_WRITEBACK_ENABLED`` setting on, saving the
description of a Databricks Table, View or Column asset in Ontos also sets
its Unity Catalog comment, as the user (on-behalf-of client only), so Unity
Catalog permissions decide. A failed write never fails the save: it becomes a
coded warning, and the asset keeps the reason in an internal property (shown
as "not in sync with Unity Catalog") until a later write succeeds.
"""
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from src.common.api_errors import CodedValueError
from src.common.config import Settings
from src.common.logging import get_logger
from src.common.uc_comments import (
    CommentWriteError, NOT_FOUND, PERMISSION_DENIED, set_comment,
)
from src.db_models.assets import AssetDb
from src.models.assets import (
    DESCRIPTION_SYNC_PROPERTY, CodedWarning, DescriptionSyncState, description_sync_state,
)

logger = get_logger(__name__)

# Ontos asset types whose description is a Unity Catalog table comment
_TABLE_TYPES = frozenset({'Table', 'View'})
_COLUMN_TYPE = 'Column'

# Warning codes (the UI translates them; params: ``object``)
CODE_PERMISSION_DENIED = 'uc_description_permission_denied'
CODE_NOT_FOUND = 'uc_description_object_not_found'
CODE_USER_TOKEN_REQUIRED = 'uc_description_user_token_required'
CODE_NO_WAREHOUSE = 'uc_description_no_warehouse'
CODE_WRITE_FAILED = 'uc_description_write_failed'

_MESSAGES = {
    CODE_PERMISSION_DENIED: (
        "Unity Catalog refused to change the description of {object} "
        "(MODIFY permission or ownership needed)."
    ),
    CODE_NOT_FOUND: "{object} was not found in Unity Catalog.",
    CODE_USER_TOKEN_REQUIRED: (
        "The request had no Databricks user token, so the description of {object} "
        "was not written to Unity Catalog."
    ),
    CODE_NO_WAREHOUSE: (
        "No SQL warehouse is configured, so the description of {object} "
        "was not written to Unity Catalog."
    ),
    CODE_WRITE_FAILED: "Writing the description of {object} to Unity Catalog failed.",
}

_REASON_CODES = {PERMISSION_DENIED: CODE_PERMISSION_DENIED, NOT_FOUND: CODE_NOT_FOUND}


def uc_comment_target(asset: AssetDb) -> Optional[Tuple[str, Optional[str]]]:
    """``(table_fqn, column_name)`` of the Unity Catalog object behind ``asset``, or None.

    Only Databricks assets: a Table or View located at ``catalog.schema.name``,
    or a Column located at ``catalog.schema.table.column``.
    """
    if (asset.platform or '').strip().lower() != 'databricks':
        return None
    type_name = getattr(asset.asset_type, 'name', None)
    location = (asset.location or '').strip()
    if type_name in _TABLE_TYPES:
        parts = location.split('.')
        if len(parts) == 3 and all(parts):
            return location, None
    elif type_name == _COLUMN_TYPE:
        parts = location.split('.', 3)
        if len(parts) == 4 and all(parts):
            return '.'.join(parts[:3]), parts[3]
    return None


def _warning(code: str, target: str) -> CodedWarning:
    return CodedWarning(code=code, message=_MESSAGES[code].format(object=target),
                        params={'object': target})


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
    ) -> Tuple[Optional[CodedWarning], Optional[DescriptionSyncState]]:
        """Write a saved description to Unity Catalog; ``(warning, sync state)``.

        Writes when the setting is on, the asset is a Unity Catalog table, view
        or column, and the update sent a description that differs from
        ``previous_description`` (or the asset is already out of sync, so
        saving again retries). With the setting off, a save drops the mark. ``user_client`` builds the user's workspace
        client; a ``CodedValueError`` from it (no user token) is a warning.
        The sync state is the one stored on the asset afterwards.
        """
        asset = db.get(AssetDb, asset_id)
        if asset is None:
            return None, None
        current_state = self._stored_state(asset)
        if not self.enabled:
            # Nothing is written to Unity Catalog, so an older mark is dropped on save
            if current_state is not None:
                self._store_state(db, asset, None)
            return None, None
        if not description_sent:
            return None, current_state
        target = uc_comment_target(asset)
        if target is None:
            return None, current_state
        if asset.description == previous_description and current_state is None:
            return None, None

        table_fqn, column_name = target
        label = f'{table_fqn}.{column_name}' if column_name else table_fqn
        warning = self._write(asset, table_fqn, column_name, label, user_client)
        state = self._store_state(db, asset, warning)
        return warning, state

    def _write(
        self, asset: AssetDb, table_fqn: str, column_name: Optional[str], label: str,
        user_client: Callable[[], Any],
    ) -> Optional[CodedWarning]:
        warehouse_id = getattr(self._settings, 'DATABRICKS_WAREHOUSE_ID', None)
        if not warehouse_id:
            return _warning(CODE_NO_WAREHOUSE, label)
        try:
            ws = user_client()
        except CodedValueError as e:
            logger.info("No user client to write the description of %s: %s", label, e.code)
            code = CODE_USER_TOKEN_REQUIRED if e.code == 'user_token_required' \
                else CODE_WRITE_FAILED
            return _warning(code, label)
        try:
            set_comment(ws, warehouse_id, table_fqn, column_name, asset.description)
        except CommentWriteError as e:
            logger.warning("Writing the description of %s (asset %s) to Unity Catalog failed: "
                           "%s: %s", label, asset.id, e.reason, e)
            return _warning(_REASON_CODES.get(e.reason, CODE_WRITE_FAILED), label)
        logger.info("Wrote the description of asset %s to Unity Catalog (%s)", asset.id, label)
        return None

    @staticmethod
    def _stored_state(asset: AssetDb) -> Optional[DescriptionSyncState]:
        return description_sync_state(asset.properties)

    @staticmethod
    def _store_state(
        db: Session, asset: AssetDb, warning: Optional[CodedWarning],
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
            properties[DESCRIPTION_SYNC_PROPERTY] = state.model_dump(mode='json')
        if properties != (asset.properties or {}):
            # A new dict, so the JSON column is seen as changed
            asset.properties = properties or None
            db.flush()
        return state
