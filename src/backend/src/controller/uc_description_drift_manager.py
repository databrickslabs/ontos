"""Compare the descriptions of a table, view or column with Unity Catalog, and reset several.

One ``tables.get`` as the user (on-behalf-of client only) gives the comment of the table and of
every column, so comparing a table with all its Column assets, or resetting the selected ones,
costs one read. Drift is read on demand, never by a job: ``changed_in_uc`` is true when the
comment differs from the baseline Ontos recorded (see ``uc_description_baseline``).

Metric views are refused, as in the write-back: their description comes from the definition.
"""
from typing import Any, Callable, List, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.common.errors import NotFoundError
from src.common.logging import get_logger
from src.common.uc_comments import TableComments, normalize_comment, split_column_location
from src.controller.uc_description_baseline import baseline_of, changed_since
from src.controller.uc_description_reset_manager import (
    NOT_SENT, ObjectNotFoundError, ResetError, UcDescriptionResetManager,
)
from src.db_models.assets import AssetDb, AssetTypeDb
from src.models.asset_description import (
    MAX_COMPARED_COLUMNS, CodedError, DescriptionDrift, DescriptionDriftField,
    ResetFieldRequest, ResetFieldResult, ResetSelectedResult,
)

logger = get_logger(__name__)


class ResetFailedError(ResetError):
    """A reset that failed unexpectedly: nothing of it was kept."""

    code = 'uc_reset_failed'
    http_status = 500


class FieldNotInTableError(ResetError):
    """A field to reset is neither the table nor one of its columns."""

    code = 'uc_reset_field_not_in_table'
    http_status = 400


def _object_type(asset: AssetDb) -> str:
    return (getattr(asset.asset_type, 'name', '') or '').strip().lower()


class UcDescriptionDriftManager:
    def __init__(self, reset_manager: UcDescriptionResetManager):
        self._reset = reset_manager

    def compare(
        self, db: Session, asset_id: UUID, *, user_client: Callable[[], Any],
    ) -> DescriptionDrift:
        """The asset (a Column: itself; a table or view: itself and its Column assets) next to
        what Unity Catalog holds, from one read."""
        asset = self._reset.get_asset(db, asset_id)
        table_fqn, column_name = self._reset.target_of(asset)
        comments = self._reset.read_table(user_client, table_fqn)
        fields = [self._field(asset, table_fqn, column_name, comments)]
        truncated = False
        if column_name is None:
            columns = self._columns(db, asset, table_fqn)
            truncated = len(columns) > MAX_COMPARED_COLUMNS
            for column in columns[:MAX_COMPARED_COLUMNS]:
                name = (column.location or '')[len(table_fqn) + 1:]
                fields.append(self._field(column, table_fqn, name, comments))
        return DescriptionDrift(
            asset_id=asset.id, target=fields[0].target, table_type=comments.table_type,
            fields=fields, truncated=truncated)

    def reset_many(
        self, db: Session, asset_id: UUID, requests: List[ResetFieldRequest], *,
        user_client: Callable[[], Any], username: str,
    ) -> ResetSelectedResult:
        """Reset the selected fields of a table (itself and its Column assets) to their
        Unity Catalog comments, from one read. A field that fails (the comment changed since
        it was shown, the column is gone) is reported and the others go on.

        One transaction for the request: the fields are flushed, the tables' column snapshots
        are updated once at the end, and the route commits once. Any other failure rolls back
        every field and is a coded ``uc_reset_failed``, never a half-applied reset. The search
        index is not touched here: the route upserts the changed assets once, after its commit."""
        root = self._reset.get_asset(db, asset_id)
        table_fqn, root_column = self._reset.target_of(root)
        comments = self._reset.read_table(user_client, table_fqn)
        results: List[ResetFieldResult] = []
        changed: List[AssetDb] = []
        try:
            for request in requests:
                results.append(self._reset_one(
                    db, root, table_fqn, root_column, request, comments, username, changed))
            self._update_snapshots(db, changed)
        except Exception as e:
            logger.exception("Resetting the descriptions under asset %s failed; rolled back",
                             root.id)
            db.rollback()
            raise ResetFailedError(
                "The descriptions could not be reset; none was changed.", table_fqn) from e
        return ResetSelectedResult(
            results=results, changed=sum(1 for r in results if r.changed),
            failed=sum(1 for r in results if r.error is not None))

    def _reset_one(
        self, db: Session, root: AssetDb, table_fqn: str, root_column: Optional[str],
        request: ResetFieldRequest, comments: TableComments, username: str,
        changed: List[AssetDb],
    ) -> ResetFieldResult:
        try:
            asset = self._reset.lock(db, request.asset_id)
            if asset.id != root.id and not (
                    root_column is None and self._is_column_of(asset, table_fqn)):
                raise FieldNotInTableError(
                    f"{asset.location} is not part of {table_fqn}.", asset.location or '')
            fqn, column = self._reset.target_of(asset)
            label = f'{fqn}.{column}' if column else fqn
            if column is None:
                uc_comment = comments.comment
            elif column in comments.columns:
                uc_comment = comments.columns[column]
            else:
                raise ObjectNotFoundError(f"{label} was not found in Unity Catalog.", label)
            expected = (
                request.expected_uc_comment
                if 'expected_uc_comment' in request.model_fields_set else NOT_SENT)
            outcome = self._reset.apply_comment(
                db, asset, label, uc_comment, username=username, expected_uc_comment=expected,
                snapshot=False, reindex=False)
            if outcome.result.changed:
                changed.append(asset)
            return ResetFieldResult(
                asset_id=request.asset_id, target=label, changed=outcome.result.changed,
                warnings=outcome.result.warnings)
        except NotFoundError as e:
            return ResetFieldResult(asset_id=request.asset_id, error=CodedError(
                code='asset_not_found', message=str(e), params={}))
        except ResetError as e:
            return ResetFieldResult(asset_id=request.asset_id, error=CodedError(
                code=e.code, message=str(e), params=e.params))

    @staticmethod
    def _update_snapshots(db: Session, changed: List[AssetDb]) -> None:
        """Copy the new descriptions of the reset Column assets into their tables'
        ``properties.schema`` (one query per table, not per column)."""
        by_table = {}
        for asset in changed:
            if _object_type(asset) != 'column':
                continue
            split = split_column_location(asset.location or '')
            if split is not None:
                by_table.setdefault((split[0], asset.platform), {})[split[1]] = asset
        for (location, platform), columns in by_table.items():
            for table in db.query(AssetDb).filter(
                    AssetDb.location == location, AssetDb.platform == platform).all():
                schema = (table.properties or {}).get('schema')
                entries = schema.get('columns') if isinstance(schema, dict) else None
                if not isinstance(entries, list):
                    continue
                new_entries = [
                    {**e, 'description': columns[e['name']].description}
                    if isinstance(e, dict) and e.get('name') in columns
                    and e.get('description') != columns[e['name']].description else e
                    for e in entries]
                if new_entries != entries:
                    # New dicts, so the JSON column is seen as changed
                    table.properties = {
                        **table.properties, 'schema': {**schema, 'columns': new_entries}}
        db.flush()

    @staticmethod
    def _is_column_of(asset: AssetDb, table_fqn: str) -> bool:
        return (
            _object_type(asset) == 'column' and (asset.platform or '').lower() == 'databricks'
            and (asset.location or '').startswith(table_fqn + '.')
        )

    @staticmethod
    def _columns(db: Session, table: AssetDb, table_fqn: str) -> List[AssetDb]:
        return (
            db.query(AssetDb).join(AssetTypeDb, AssetTypeDb.id == AssetDb.asset_type_id)
            .filter(
                func.lower(AssetTypeDb.name) == 'column',
                func.lower(AssetDb.platform) == 'databricks',
                AssetDb.location.startswith(table_fqn + '.', autoescape=True),
                AssetDb.id != table.id,
            ).order_by(AssetDb.location).limit(MAX_COMPARED_COLUMNS + 1).all()
        )

    @staticmethod
    def _field(
        asset: AssetDb, table_fqn: str, column_name: Optional[str], comments: TableComments,
    ) -> DescriptionDriftField:
        missing = column_name is not None and column_name not in comments.columns
        uc_comment = (
            comments.comment if column_name is None else comments.columns.get(column_name))
        baseline = baseline_of(asset.properties)
        description = asset.description or None
        differs = (not missing) and normalize_comment(description) != normalize_comment(
            uc_comment)
        return DescriptionDriftField(
            asset_id=asset.id, name=column_name or asset.name, object_type=_object_type(asset),
            target=f'{table_fqn}.{column_name}' if column_name else table_fqn,
            description=description, uc_comment=uc_comment,
            baseline_known=baseline is not None,
            baseline_text=baseline.get('text') if baseline else None,
            differs=differs,
            # Not once the Ontos text is the comment: a user who edited it to match has settled
            # it, and nothing is left to compare or reset. The baseline stays, so the next
            # real change in Unity Catalog differs again and is flagged.
            changed_in_uc=(not missing) and differs and changed_since(baseline, uc_comment),
            missing_in_uc=missing,
        )
