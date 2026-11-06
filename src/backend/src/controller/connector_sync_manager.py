"""
Connector syncs

A connector sync is a saved Schema Importer selection that the ``connector_sync``
Databricks job imports again on a schedule (#1312 slice 5). Each run walks the
selection completely in sync mode: new items are created, changed ones refreshed,
and every asset still in the source is reported as seen. Assets in scope that a
complete run did not see count a miss; after ``retire_after_misses`` misses they
are retired (never deleted). They come back when the source has them again.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import or_
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from src.common.logging import get_logger
from src.db_models.assets import AssetDb
from src.db_models.connector_syncs import ConnectorSyncDb
from src.models.assets import AssetStatus
from src.models.notifications import Notification, NotificationType
from src.models.schema_import import ImportMode, ImportRequest, ImportResult
from src.repositories.schema_import_runs_repository import schema_import_runs_repo

logger = get_logger(__name__)

SYNC_USER = "system:connector-sync"
MISSED_PROPERTY = "sync_missed"
RETIRED_BY_SYNC_PROPERTY = "retired_by_sync"

STATUS_COMPLETED = "completed"
STATUS_INCOMPLETE = "incomplete"
STATUS_FAILED = "failed"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _under(location: Optional[str], paths: Iterable[str]) -> bool:
    return bool(location) and any(location == p or location.startswith(f"{p}.") for p in paths)


class ConnectorSyncManager:
    """CRUD for connector syncs, plus running one sync and retiring what the source dropped."""

    # -- CRUD ------------------------------------------------------------------

    def list(self, db: Session, connection_id: Optional[UUID] = None) -> List[ConnectorSyncDb]:
        query = db.query(ConnectorSyncDb)
        if connection_id is not None:
            query = query.filter(ConnectorSyncDb.connection_id == connection_id)
        return query.order_by(ConnectorSyncDb.name).all()

    def get(self, db: Session, sync_id: str) -> Optional[ConnectorSyncDb]:
        return db.get(ConnectorSyncDb, sync_id)

    def create(
        self, db: Session, *, name: str, connection_id: UUID, request: Dict[str, Any],
        interval_minutes: int, retire_after_misses: int, enabled: bool, created_by: Optional[str],
    ) -> ConnectorSyncDb:
        sync = ConnectorSyncDb(
            id=str(uuid4()), name=name, connection_id=connection_id, request=self._selection(request),
            interval_minutes=interval_minutes, retire_after_misses=retire_after_misses, enabled=enabled,
            created_by=created_by, next_due_at=_now() if enabled else None,
        )
        db.add(sync)
        db.flush()
        return sync

    def update(self, db: Session, sync: ConnectorSyncDb, **changes: Any) -> ConnectorSyncDb:
        for key in ("name", "interval_minutes", "retire_after_misses"):
            if changes.get(key) is not None:
                setattr(sync, key, changes[key])
        if changes.get("request") is not None:
            sync.request = self._selection(changes["request"])
        if changes.get("enabled") is not None and changes["enabled"] != sync.enabled:
            sync.enabled = changes["enabled"]
            # Re-enabled: due now; disabled: never due
            sync.next_due_at = _now() if sync.enabled else None
        db.flush()
        return sync

    def delete(self, db: Session, sync: ConnectorSyncDb) -> None:
        db.delete(sync)
        db.flush()

    @staticmethod
    def _selection(request: Dict[str, Any]) -> Dict[str, Any]:
        """The parts of an ImportRequest a sync keeps (validated through ImportRequest)."""
        parsed = ImportRequest(connection_id=uuid4(), **{
            k: request[k] for k in ("selected_paths", "depth", "excluded_paths") if k in request
        })
        return {
            "selected_paths": parsed.selected_paths,
            "depth": parsed.depth.value,
            "excluded_paths": parsed.excluded_paths,
        }

    # -- Scheduling --------------------------------------------------------------

    def due(self, db: Session, now: Optional[datetime] = None) -> List[ConnectorSyncDb]:
        now = now or _now()
        return (
            db.query(ConnectorSyncDb)
            .filter(ConnectorSyncDb.enabled.is_(True))
            .filter(or_(ConnectorSyncDb.next_due_at.is_(None), ConnectorSyncDb.next_due_at <= now))
            .order_by(ConnectorSyncDb.next_due_at)
            .all()
        )

    # -- Running -------------------------------------------------------------------

    def run(
        self, db: Session, sync: ConnectorSyncDb, importer: Any, *, trigger: str = "schedule",
    ) -> Dict[str, Any]:
        """Run one sync: import in sync mode, retire what a complete walk missed, record the run.

        Returns the run summary. Raises nothing: a failure is recorded on the run
        and the sync, so the job can go on with the next sync.
        """
        run_id = str(uuid4())
        request = ImportRequest(connection_id=sync.connection_id, mode=ImportMode.SYNC, **sync.request)
        schema_import_runs_repo.create(
            db, run_id=run_id, user_id=sync.created_by or SYNC_USER, connection_id=str(sync.connection_id),
            request=request.model_dump(mode="json"), sync_id=sync.id, trigger=trigger,
        )
        schema_import_runs_repo.update_status(db, run_id, "running", progress_message=f"Sync '{sync.name}'")
        started = _now()
        summary: Dict[str, Any] = {"run_id": run_id, "sync_id": sync.id}
        try:
            # The importer commits as it goes (like an interactive import): what it
            # created before a failure stays, and the next run picks up from there
            result: ImportResult = importer.execute_import(db, request, current_user_id=SYNC_USER)
            connector_type = self._connector_type(db, sync)
            retirement = self.apply_retirement(db, sync, connector_type, result)
        except Exception as exc:
            logger.error(f"Connector sync '{sync.name}' ({sync.id}) failed: {exc}", exc_info=True)
            if not db.is_active:
                db.rollback()
            schema_import_runs_repo.update_status(
                db, run_id, "failed", error=f"{type(exc).__name__}: {exc}"[:2000], completed_at=_now(),
            )
            self._finish(db, sync, run_id, started, STATUS_FAILED)
            self._notify(db, sync, NotificationType.ERROR, "Connector sync failed",
                         f"Sync '{sync.name}' failed: {type(exc).__name__}", run_id)
            return {**summary, "status": STATUS_FAILED, "error": str(exc)}

        status = STATUS_INCOMPLETE if result.incomplete_reasons else STATUS_COMPLETED
        payload = result.model_dump(mode="json", exclude={"seen_asset_ids"})
        payload["retirement"] = retirement
        schema_import_runs_repo.set_result(
            db, run_id, payload, status="completed",
            created_count=result.created, skipped_count=result.skipped, error_count=result.errors,
        )
        self._finish(db, sync, run_id, started, status)
        if retirement["retired"]:
            self._notify(db, sync, NotificationType.WARNING, "Assets retired by a connector sync",
                         f"Sync '{sync.name}' retired {retirement['retired']} asset(s) no longer in the source",
                         run_id)
        return {
            **summary, "status": status, "created": result.created, "refreshed": result.refreshed,
            "errors": result.errors, "incomplete_reasons": result.incomplete_reasons, **retirement,
        }

    def _finish(self, db: Session, sync: ConnectorSyncDb, run_id: str, started: datetime, status: str) -> None:
        sync.last_run_id = run_id
        sync.last_run_at = started
        sync.last_status = status
        if status == STATUS_COMPLETED:
            sync.last_complete_sync_at = started
        sync.next_due_at = started + timedelta(minutes=sync.interval_minutes)
        db.flush()

    @staticmethod
    def _connector_type(db: Session, sync: ConnectorSyncDb) -> str:
        from src.db_models.connections import ConnectionDb
        connection = db.get(ConnectionDb, sync.connection_id)
        if connection is None:
            raise ValueError(f"Connection {sync.connection_id} no longer exists")
        return connection.connector_type

    # -- Retirement ------------------------------------------------------------------

    def apply_retirement(
        self, db: Session, sync: ConnectorSyncDb, connector_type: str, result: ImportResult,
    ) -> Dict[str, Any]:
        """Count misses of in-scope assets a complete walk did not see; retire after N.

        In scope: imported through this sync's connection, at or below a selected
        path and not excluded. An incomplete walk changes nothing (it may have
        missed assets that are still there). Assets someone retired by hand stay
        retired; the ones a sync retired come back when the source has them again.
        """
        counts = {"retired": 0, "reactivated": 0, "missed": 0, "counted": not result.incomplete_reasons}
        if result.incomplete_reasons:
            return counts

        selected = sync.request.get("selected_paths") or []
        excluded = sync.request.get("excluded_paths") or []
        seen = {str(i) for i in result.seen_asset_ids}
        connection = str(sync.connection_id)

        location_filters = [AssetDb.location == p for p in selected] + [
            AssetDb.location.startswith(f"{p}.", autoescape=True) for p in selected
        ]
        candidates = (
            db.query(AssetDb)
            .filter(AssetDb.platform == connector_type, or_(*location_filters))
            .all()
        ) if location_filters else []

        for asset in candidates:
            props = dict(asset.properties or {})
            if props.get("connection_id") != connection or _under(asset.location, excluded):
                continue
            by_sync = bool(props.get(RETIRED_BY_SYNC_PROPERTY))
            if asset.status == AssetStatus.RETIRED.value and not by_sync:
                continue
            if str(asset.id) in seen:
                if not props.get(MISSED_PROPERTY) and not by_sync:
                    continue
                props.pop(MISSED_PROPERTY, None)
                if by_sync:
                    props.pop(RETIRED_BY_SYNC_PROPERTY, None)
                    asset.status = AssetStatus.ACTIVE.value
                    counts["reactivated"] += 1
                    self._log(db, asset, "REACTIVATED_BY_SYNC", sync)
                self._save(db, asset, props)
                continue
            if by_sync:
                continue
            missed = int(props.get(MISSED_PROPERTY) or 0) + 1
            props[MISSED_PROPERTY] = missed
            counts["missed"] += 1
            if missed >= sync.retire_after_misses:
                props[RETIRED_BY_SYNC_PROPERTY] = True
                asset.status = AssetStatus.RETIRED.value
                counts["retired"] += 1
                self._log(db, asset, "RETIRED_BY_SYNC", sync, missed=missed)
            self._save(db, asset, props)
        db.flush()
        return counts

    @staticmethod
    def _save(db: Session, asset: AssetDb, props: Dict[str, Any]) -> None:
        asset.properties = props
        flag_modified(asset, "properties")

    @staticmethod
    def _log(db: Session, asset: AssetDb, action: str, sync: ConnectorSyncDb, **details: Any) -> None:
        from src.controller.change_log_manager import change_log_manager
        try:
            change_log_manager.log_change_with_details(
                db, entity_type="asset", entity_id=str(asset.id), action=action, username=SYNC_USER,
                details={"sync_id": sync.id, "sync_name": sync.name, **details}, commit=False,
            )
        except Exception as exc:
            logger.warning(f"Could not log {action} for asset {asset.id}: {exc}")

    @staticmethod
    def _notify(
        db: Session, sync: ConnectorSyncDb, kind: NotificationType, title: str, message: str, run_id: str,
    ) -> None:
        if not sync.created_by:
            return
        from src.repositories.notification_repository import notification_repo
        try:
            notification_repo.create(db=db, obj_in=Notification(
                id=str(uuid4()), type=kind, title=title, message=message,
                link=f"/schema-importer?runId={run_id}", recipient=sync.created_by,
                data={"run_id": run_id, "sync_id": sync.id}, created_at=_now(),
            ))
        except Exception as exc:
            logger.warning(f"Could not notify {sync.created_by} about sync {sync.id}: {exc}")


connector_sync_manager = ConnectorSyncManager()
