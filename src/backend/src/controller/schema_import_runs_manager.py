"""
Schema Import Runs Manager

Runs the Schema Importer's ``execute_import`` in an in-app background thread so
large-estate imports don't block the request/UI. Mirrors the Ontology
Generator's async pattern (OntologyGeneratorManager): a DB-persisted run row
tracks status + live progress, the work runs in a daemon thread on a fresh
session, and a JOB_PROGRESS notification is created on start and updated to a
terminal state on completion. Clients poll GET /api/schema-import/runs/{id}.

A Databricks-Job execution backend is intentionally out of scope here (see the
follow-up issue); this uses the same in-app thread mechanism the codebase
already relies on for long-running UC work.
"""

import threading
import time
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from src.common.config import Settings
from src.common.logging import get_logger
from src.models.notifications import Notification, NotificationType, NotificationUpdate
from src.models.schema_import import ImportRequest, ImportResult
from src.db_models.schema_import_runs import SchemaImportRunDb
from src.repositories.schema_import_runs_repository import schema_import_runs_repo

logger = get_logger(__name__)

MAX_CONCURRENT_RUNS_PER_USER = 3


class SchemaImportRunsManager:
    """Manages async (background-thread) Schema Importer runs."""

    def __init__(self, settings: Settings, assets_manager, notifications_manager):
        self._settings = settings
        self._assets_manager = assets_manager
        self._notifications_manager = notifications_manager
        self._cancel_events: dict = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Read accessors (delegate to repo)
    # ------------------------------------------------------------------

    def get_run(self, db: Session, run_id: str) -> Optional[SchemaImportRunDb]:
        return schema_import_runs_repo.get(db, run_id)

    def get_run_for_user(self, db: Session, run_id: str, user_id: str) -> Optional[SchemaImportRunDb]:
        return schema_import_runs_repo.get_for_user(db, run_id, user_id)

    def list_runs_for_user(self, db: Session, user_id: str, *, limit: int = 50) -> List[SchemaImportRunDb]:
        return schema_import_runs_repo.list_for_user(db, user_id, limit=limit)

    # ------------------------------------------------------------------
    # Start / cancel
    # ------------------------------------------------------------------

    def start_run(
        self,
        db: Session,
        request: ImportRequest,
        user_id: str,
        user_token: Optional[str] = None,
    ) -> str:
        """Create a persisted run and execute the import in a background thread.

        Returns the run_id immediately. Raises ValueError if the user is at the
        concurrent-run cap.
        """
        running = schema_import_runs_repo.count_running_for_user(db, user_id)
        if running >= MAX_CONCURRENT_RUNS_PER_USER:
            raise ValueError(
                f"Concurrent import limit reached ({MAX_CONCURRENT_RUNS_PER_USER}). "
                "Wait for a running import to finish or cancel one."
            )

        run_id = str(uuid.uuid4())
        schema_import_runs_repo.create(
            db,
            run_id=run_id,
            user_id=user_id,
            connection_id=str(request.connection_id),
            request=request.model_dump(mode="json"),
        )

        # Create a progress notification for the requesting user.
        notification_id = self._create_progress_notification(db, run_id, user_id)
        run = schema_import_runs_repo.get(db, run_id)
        if run:
            run.notification_id = notification_id
        db.commit()

        cancel_event = threading.Event()
        with self._lock:
            self._cancel_events[run_id] = cancel_event

        thread = threading.Thread(
            target=self._run_import,
            args=(run_id, request.model_dump(mode="json"), user_id, user_token, notification_id, cancel_event),
            daemon=True,
        )
        thread.start()
        logger.info("Started background schema import run %s for user %s", run_id, user_id)
        return run_id

    def cancel_run(self, run_id: str) -> bool:
        """Signal a running import to stop. Returns True if the run was active
        in this process (its cancel event was set)."""
        with self._lock:
            event = self._cancel_events.get(run_id)
        if event:
            event.set()
            return True
        return False

    # ------------------------------------------------------------------
    # Background thread body
    # ------------------------------------------------------------------

    def _run_import(
        self,
        run_id: str,
        request_dict: dict,
        user_id: str,
        user_token: Optional[str],
        notification_id: Optional[str],
        cancel_event: threading.Event,
    ) -> None:
        from src.common.database import get_session_factory
        from src.controller.connections_manager import ConnectionsManager
        from src.controller.schema_import_manager import SchemaImportManager

        SessionLocal = get_session_factory()
        db = SessionLocal()

        # Throttle progress persistence so a big import doesn't hammer the DB /
        # notification store — persist at most ~once per second (plus the final one).
        last_persist = [0.0]

        def on_progress(processed: int, total: int, result: ImportResult) -> None:
            now = time.monotonic()
            is_last = total > 0 and processed >= total
            if not is_last and (now - last_persist[0]) < 1.0:
                return
            last_persist[0] = now
            try:
                schema_import_runs_repo.update_progress(
                    db, run_id,
                    processed_items=processed,
                    total_items=total,
                    created_count=result.created,
                    skipped_count=result.skipped,
                    error_count=result.errors,
                    progress_message=f"Imported {processed}/{total} items",
                )
                db.commit()
                self._update_progress_notification(
                    db, notification_id, run_id, processed, total, status="running",
                )
            except Exception:
                db.rollback()

        try:
            request = ImportRequest(**request_dict)
            ws = self._build_workspace_client(user_token)
            connections_mgr = ConnectionsManager(db=db, workspace_client=ws)
            importer = SchemaImportManager(
                connections_manager=connections_mgr,
                assets_manager=self._assets_manager,
            )

            schema_import_runs_repo.update_status(
                db, run_id, "running", progress_message="Starting import…",
            )
            db.commit()

            result = importer.execute_import(
                db=db,
                request=request,
                current_user_id=user_id,
                progress_callback=on_progress,
                cancel_event=cancel_event,
            )

            if cancel_event.is_set():
                schema_import_runs_repo.update_status(
                    db, run_id, "cancelled",
                    progress_message="Cancelled",
                    completed_at=datetime.now(timezone.utc),
                )
                schema_import_runs_repo.update_progress(
                    db, run_id,
                    created_count=result.created,
                    skipped_count=result.skipped,
                    error_count=result.errors,
                )
                db.commit()
                self._finalize_notification(db, notification_id, run_id, "cancelled", result)
                return

            schema_import_runs_repo.set_result(
                db, run_id, result.model_dump(mode="json"),
                status="completed",
                created_count=result.created,
                skipped_count=result.skipped,
                error_count=result.errors,
            )
            db.commit()
            self._finalize_notification(db, notification_id, run_id, "completed", result)

        except Exception as exc:
            logger.exception("Background schema import run %s failed", run_id)
            try:
                schema_import_runs_repo.update_status(
                    db, run_id, "failed",
                    error=str(exc),
                    completed_at=datetime.now(timezone.utc),
                )
                db.commit()
                self._finalize_notification(db, notification_id, run_id, "failed", None, error=str(exc))
            except Exception:
                db.rollback()
        finally:
            db.close()
            with self._lock:
                self._cancel_events.pop(run_id, None)

    # ------------------------------------------------------------------
    # Workspace client (background thread has no request → no OBO middleware)
    # ------------------------------------------------------------------

    def _build_workspace_client(self, user_token: Optional[str]):
        """Build a workspace client for the background thread.

        Prefer the caller's forwarded OBO token (preserves their UC permissions,
        matching the synchronous import path); fall back to the app service
        principal when no token was forwarded (e.g. local dev).
        """
        from src.common.workspace_client import get_workspace_client
        if user_token:
            try:
                from databricks.sdk import WorkspaceClient
                return WorkspaceClient(
                    host=self._settings.DATABRICKS_HOST,
                    token=user_token,
                    product="ontos",
                )
            except Exception as exc:
                logger.warning("OBO workspace client failed (%s); falling back to service principal", exc)
        try:
            return get_workspace_client(self._settings)
        except Exception as exc:
            logger.warning("Service-principal workspace client unavailable: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def _create_progress_notification(self, db: Session, run_id: str, user_id: str) -> Optional[str]:
        if not self._notifications_manager:
            return None
        try:
            notification = Notification(
                id=f"schema-import-{run_id}",
                type=NotificationType.JOB_PROGRESS,
                title="Schema import running",
                subtitle="Infer from Unity Catalog",
                message="Importing selected objects in the background…",
                link="/schema-import",
                recipient=user_id,
                data={"run_id": run_id, "progress": 0, "status": "running"},
                created_at=datetime.now(timezone.utc),
            )
            self._notifications_manager.create_notification(notification, db=db)
            return notification.id
        except Exception as exc:
            logger.warning("Could not create schema-import progress notification: %s", exc)
            return None

    def _update_progress_notification(
        self, db: Session, notification_id: Optional[str], run_id: str,
        processed: int, total: int, status: str,
    ) -> None:
        if not (self._notifications_manager and notification_id):
            return
        progress = int((processed / total) * 100) if total else 0
        try:
            self._notifications_manager.update_notification(
                notification_id,
                NotificationUpdate(
                    message=f"Imported {processed}/{total} objects…",
                    data={"run_id": run_id, "progress": progress, "status": status},
                    updated_at=datetime.now(timezone.utc),
                ),
                db=db,
            )
        except Exception as exc:
            logger.debug("Progress notification update failed: %s", exc)

    def _finalize_notification(
        self, db: Session, notification_id: Optional[str], run_id: str,
        status: str, result: Optional[ImportResult], error: Optional[str] = None,
    ) -> None:
        if not (self._notifications_manager and notification_id):
            return
        if status == "completed" and result is not None:
            title = "Schema import complete"
            message = (
                f"Created {result.created}, skipped {result.skipped}"
                + (f", {result.errors} error(s)" if result.errors else "")
                + "."
            )
        elif status == "cancelled":
            title = "Schema import cancelled"
            message = "The import was cancelled."
        else:
            title = "Schema import failed"
            message = error or "The import failed. See the run details."
        try:
            self._notifications_manager.update_notification(
                notification_id,
                NotificationUpdate(
                    title=title,
                    message=message,
                    data={"run_id": run_id, "progress": 100, "status": status},
                    updated_at=datetime.now(timezone.utc),
                ),
                db=db,
            )
        except Exception as exc:
            logger.debug("Terminal notification update failed: %s", exc)
