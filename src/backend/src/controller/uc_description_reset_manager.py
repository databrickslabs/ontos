"""Use the Unity Catalog comment as the description of a table, view or column asset.

The reverse of the write-back (#1477): Unity Catalog is read as the user (on-behalf-of
client only, no fallback to the app), and its comment becomes the Ontos description,
through ``AssetsManager`` (search index, history entry, validations). Nothing is
written to Unity Catalog, so it works with the write-back setting off too.

An empty Unity Catalog comment never empties the Ontos description: the asset is kept
and the result carries the coded warning ``uc_description_empty``.
"""
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from src.common.api_errors import CodedValueError
from src.common.errors import NotFoundError
from src.common.logging import get_logger
from src.common.uc_comments import (
    CommentWriteError, NOT_FOUND, PERMISSION_DENIED, SINGLE_READ_TIMEOUT_SECONDS,
    TableComments, normalize_comment, read_comment, read_table_comments,
)
from src.controller.asset_description_history import SOURCE_UC_RESET, description_source
from src.controller.assets_manager import AssetsManager
from src.controller.uc_description_baseline import set_baseline
from src.controller.uc_description_sync_manager import (
    METRIC_VIEW_TABLE_TYPE, UcDescriptionSyncManager, uc_comment_target,
)
from src.db_models.assets import AssetDb
from src.models.asset_description import DescriptionResetResult, UcCommentPreview
from src.models.assets import METRIC_VIEW_ASSET_TYPE, AssetUpdate, CodedWarning

logger = get_logger(__name__)

# Warning of a reset that changed nothing: Unity Catalog has no comment on the object
CODE_UC_EMPTY = 'uc_description_empty'

NOT_SENT = object()


class ResetError(CodedValueError):
    """A reset that is refused; ``http_status`` is the status the route answers with."""

    http_status = 400

    def __init__(self, message: str, target: str = '', **params: Any):
        super().__init__(message, object=target, **params)


class NotApplicableError(ResetError):
    """The asset is not a Unity Catalog table, view or column."""

    code = 'uc_reset_not_applicable'
    http_status = 400


class MetricViewError(ResetError):
    """A metric view: its description comes from its definition, not from a comment."""

    code = 'uc_reset_metric_view'
    http_status = 409


class PermissionDeniedError(ResetError):
    """The user may not read the object in Unity Catalog (no SELECT on the table)."""

    code = 'uc_reset_permission_denied'
    http_status = 403


class ObjectNotFoundError(ResetError):
    """The table (or the column) is gone from Unity Catalog, or invisible to the user."""

    code = 'uc_reset_object_not_found'
    http_status = 404


class UnavailableError(ResetError):
    """Unity Catalog could not be read (failed or too slow)."""

    code = 'uc_reset_unavailable'
    http_status = 502


class UcCommentChangedError(ResetError):
    """Unity Catalog has another comment now than the one the user confirmed."""

    code = 'uc_reset_uc_changed'
    http_status = 409


@dataclass
class ResetOutcome:
    result: DescriptionResetResult
    audit: Dict[str, Any]


def _label(target: Tuple[str, Optional[str]]) -> str:
    table_fqn, column_name = target
    return f'{table_fqn}.{column_name}' if column_name else table_fqn


class UcDescriptionResetManager:
    def __init__(self, assets_manager: AssetsManager, sync_manager: UcDescriptionSyncManager):
        self._assets = assets_manager
        self._sync = sync_manager

    def preview(
        self, db: Session, asset_id: UUID, *, user_client: Callable[[], Any],
    ) -> UcCommentPreview:
        """The Ontos description and the Unity Catalog comment of an asset, for the diff."""
        asset = self.get_asset(db, asset_id)
        target = self.target_of(asset)
        table_type, uc_comment = self._read(user_client, target)
        return UcCommentPreview(
            asset_id=asset.id, target=_label(target),
            object_type=(getattr(asset.asset_type, 'name', '') or '').lower(),
            description=asset.description or None, uc_comment=uc_comment, table_type=table_type,
            in_sync=normalize_comment(asset.description) == normalize_comment(uc_comment),
        )

    def reset(
        self, db: Session, asset_id: UUID, *, user_client: Callable[[], Any], username: str,
        expected_uc_comment: Any = NOT_SENT,
    ) -> ResetOutcome:
        """Replace the description of the asset with its Unity Catalog comment.

        Does not commit (``AssetsManager.update_asset`` only flushes, with the history entry);
        the caller commits. ``expected_uc_comment``: the comment the user saw;
        another one now is ``UcCommentChangedError``.
        """
        # Read Unity Catalog first (up to 10 s), lock afterwards: the row is not held during
        # the read, and the asset is read again under the lock
        target = self.target_of(self.get_asset(db, asset_id))
        _table_type, uc_comment = self._read(user_client, target)
        asset = self.lock(db, asset_id)
        if self.target_of(asset) != target:
            raise UcCommentChangedError(
                f"{_label(target)} changed while Unity Catalog was read.", _label(target))
        return self.apply_comment(
            db, asset, _label(target), uc_comment, username=username,
            expected_uc_comment=expected_uc_comment)

    @staticmethod
    def lock(db: Session, asset_id: UUID) -> AssetDb:
        """The asset, its row locked until the caller commits."""
        asset = (
            db.query(AssetDb).filter(AssetDb.id == asset_id)
            .with_for_update().populate_existing().one_or_none()
        )
        if asset is None:
            raise NotFoundError(f"Asset '{asset_id}' not found.")
        return asset

    def apply_comment(
        self, db: Session, asset: AssetDb, label: str, uc_comment: Optional[str], *,
        username: str, expected_uc_comment: Any = NOT_SENT, snapshot: bool = True,
        reindex: bool = True,
    ) -> ResetOutcome:
        """Replace the description of the (locked) asset with ``uc_comment``, read as the user.

        ``snapshot=False``: the caller updates the tables' column snapshots itself, once for
        all the assets it resets (see ``UcDescriptionDriftManager.reset_many``).
        ``reindex=False``: likewise the search index, which the caller upserts once after its
        commit.

        Records the comment as the asset's Unity Catalog baseline (drift). An empty comment
        changes nothing and warns; a description that already equals it only clears the
        "not in sync" mark.
        """
        asset_id = asset.id
        if expected_uc_comment is not NOT_SENT and (
                normalize_comment(expected_uc_comment) != normalize_comment(uc_comment)):
            raise UcCommentChangedError(
                f"The Unity Catalog comment of {label} changed since you looked at it.", label)

        previous = asset.description or None
        audit: Dict[str, Any] = {
            'target': label, 'before': previous, 'uc_comment': uc_comment, 'outcome': None,
        }
        warnings = []

        def result(changed: bool) -> DescriptionResetResult:
            return DescriptionResetResult(
                asset_id=asset_id, target=label, changed=changed, previous_description=previous,
                description=asset.description or None, warnings=warnings)

        if uc_comment is None:
            # Nothing to bring: the Ontos description is kept
            audit['outcome'] = 'uc_empty'
            set_baseline(db, asset, None)
            if previous is not None:
                warnings.append(CodedWarning(
                    code=CODE_UC_EMPTY, params={'object': label},
                    message=f"Unity Catalog has no comment on {label}, so its description in "
                            "Ontos was kept."))
            return ResetOutcome(result(False), audit)
        if normalize_comment(previous) == normalize_comment(uc_comment):
            # Already the same text; an earlier "not in sync" mark is obsolete
            audit['outcome'] = 'unchanged'
            self._sync.clear_state(db, asset)
            set_baseline(db, asset, uc_comment)
            return ResetOutcome(result(False), audit)

        # The mark and the baseline go with the change (one commit, in update_asset)
        self._sync.clear_state(db, asset)
        set_baseline(db, asset, uc_comment)
        with description_source(SOURCE_UC_RESET):
            self._assets.update_asset(
                db, asset_id=asset_id, asset_in=AssetUpdate(description=uc_comment),
                current_user_id=username, commit=False,
                reindex=reindex)
        asset = db.get(AssetDb, asset_id)
        if snapshot:
            AssetsManager.update_table_column_snapshot(db, asset)
        audit['outcome'] = 'reset'
        logger.info("Reset the description of asset %s to its Unity Catalog comment", asset_id)
        return ResetOutcome(result(True), audit)

    @staticmethod
    def get_asset(db: Session, asset_id: UUID) -> AssetDb:
        asset = db.get(AssetDb, asset_id)
        if asset is None:
            raise NotFoundError(f"Asset '{asset_id}' not found.")
        return asset

    @staticmethod
    def target_of(asset: AssetDb) -> Tuple[str, Optional[str]]:
        type_name = getattr(asset.asset_type, 'name', None)
        label = asset.location or str(asset.id)
        if type_name == METRIC_VIEW_ASSET_TYPE:
            raise MetricViewError(
                f"{label} is a metric view: its description comes from its definition.", label)
        target = uc_comment_target(asset)
        if target is None:
            raise NotApplicableError(
                f"{label} is not a Unity Catalog table, view or column.", label)
        return target

    @staticmethod
    def read_table(user_client: Callable[[], Any], table_fqn: str) -> TableComments:
        """The comments of a table and all its columns, read as the user in one call."""
        ws = user_client()  # a CodedValueError (no user token, no client) reaches the caller
        try:
            comments = read_table_comments(
                ws, table_fqn, timeout_seconds=SINGLE_READ_TIMEOUT_SECONDS)
        except CommentWriteError as e:
            logger.warning("Reading the Unity Catalog comments of %s failed: %s",
                           table_fqn, e.reason)
            if e.reason == PERMISSION_DENIED:
                raise PermissionDeniedError(
                    f"You can't read {table_fqn} in Unity Catalog (SELECT permission needed).",
                    table_fqn) from e
            if e.reason == NOT_FOUND:
                raise ObjectNotFoundError(
                    f"{table_fqn} was not found in Unity Catalog, or you don't have access "
                    "to it.", table_fqn) from e
            raise UnavailableError(
                f"Unity Catalog could not be read for {table_fqn}.", table_fqn) from e
        if comments.table_type == METRIC_VIEW_TABLE_TYPE:
            raise MetricViewError(
                f"{table_fqn} is a metric view: its description comes from its definition.",
                table_fqn)
        return comments

    @staticmethod
    def _read(user_client: Callable[[], Any], target: Tuple[str, Optional[str]]) -> Tuple[
            Optional[str], Optional[str]]:
        """``(table_type, comment)`` read as the user; a metric view is refused."""
        label = _label(target)
        ws = user_client()  # a CodedValueError (no user token, no client) reaches the caller
        try:
            table_type, comment = read_comment(
                ws, target[0], target[1], timeout_seconds=SINGLE_READ_TIMEOUT_SECONDS)
        except CommentWriteError as e:
            logger.warning("Reading the Unity Catalog comment of %s failed: %s", label, e.reason)
            if e.reason == PERMISSION_DENIED:
                raise PermissionDeniedError(
                    f"You can't read {label} in Unity Catalog (SELECT permission needed).",
                    label) from e
            if e.reason == NOT_FOUND:
                raise ObjectNotFoundError(
                    f"{label} was not found in Unity Catalog, or you don't have access to it.",
                    label) from e
            raise UnavailableError(
                f"Unity Catalog could not be read for {label}.", label) from e
        if table_type == METRIC_VIEW_TABLE_TYPE:
            raise MetricViewError(
                f"{label} is a metric view: its description comes from its definition.", label)
        return table_type, comment
