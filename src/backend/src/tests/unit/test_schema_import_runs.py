"""Unit tests for the async Schema Importer run state + manager.

Covers the persisted run repository and the SchemaImportRunsManager's
synchronous surface (start_run bookkeeping, concurrency cap, cancel). The
background thread body itself is patched out so these tests stay deterministic
and never spawn real threads.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from src.models.schema_import import ImportDepth, ImportRequest
from src.repositories.schema_import_runs_repository import schema_import_runs_repo
from src.controller.schema_import_runs_manager import (
    SchemaImportRunsManager,
    MAX_CONCURRENT_RUNS_PER_USER,
)


def _import_request() -> ImportRequest:
    return ImportRequest(
        connection_id=uuid4(),
        selected_paths=["cat.sch.table_a"],
        depth=ImportDepth.SELECTED_ONLY,
    )


class TestSchemaImportRunsRepository:

    def test_create_and_get(self, db_session):
        run = schema_import_runs_repo.create(
            db_session, run_id="r1", user_id="alice@example.com",
            connection_id="c1", request={"selected_paths": ["a"]},
        )
        db_session.commit()
        assert run.status == "pending"
        fetched = schema_import_runs_repo.get(db_session, "r1")
        assert fetched is not None
        assert fetched.user_id == "alice@example.com"

    def test_get_for_user_scopes_by_owner(self, db_session):
        schema_import_runs_repo.create(db_session, run_id="r2", user_id="alice@example.com")
        db_session.commit()
        assert schema_import_runs_repo.get_for_user(db_session, "r2", "alice@example.com") is not None
        assert schema_import_runs_repo.get_for_user(db_session, "r2", "bob@example.com") is None

    def test_update_progress_and_status(self, db_session):
        schema_import_runs_repo.create(db_session, run_id="r3", user_id="u")
        db_session.commit()
        schema_import_runs_repo.update_progress(
            db_session, "r3", processed_items=5, total_items=10,
            created_count=4, skipped_count=1, error_count=0,
            progress_message="Imported 5/10 items",
        )
        schema_import_runs_repo.update_status(db_session, "r3", "running")
        db_session.commit()
        run = schema_import_runs_repo.get(db_session, "r3")
        assert run.processed_items == 5
        assert run.total_items == 10
        assert run.created_count == 4
        assert run.status == "running"

    def test_set_result_marks_completed(self, db_session):
        schema_import_runs_repo.create(db_session, run_id="r4", user_id="u")
        db_session.commit()
        schema_import_runs_repo.set_result(
            db_session, "r4", {"created": 3, "skipped": 0, "errors": 0},
            created_count=3, skipped_count=0, error_count=0,
        )
        db_session.commit()
        run = schema_import_runs_repo.get(db_session, "r4")
        assert run.status == "completed"
        assert run.completed_at is not None
        assert run.result["created"] == 3

    def test_count_running_for_user(self, db_session):
        schema_import_runs_repo.create(db_session, run_id="a", user_id="u")
        schema_import_runs_repo.update_status(db_session, "a", "running")
        schema_import_runs_repo.create(db_session, run_id="b", user_id="u")  # stays pending
        schema_import_runs_repo.create(db_session, run_id="c", user_id="u")
        schema_import_runs_repo.update_status(db_session, "c", "completed")
        db_session.commit()
        # pending + running both count as "running" (in-flight)
        assert schema_import_runs_repo.count_running_for_user(db_session, "u") == 2


class TestSchemaImportRunsManager:

    def _manager(self):
        notifications = MagicMock()
        notifications.create_notification.return_value = None
        return SchemaImportRunsManager(
            settings=MagicMock(),
            assets_manager=MagicMock(),
            notifications_manager=notifications,
        ), notifications

    def test_start_run_persists_pending_run_without_running_thread(self, db_session):
        manager, notifications = self._manager()
        req = _import_request()

        # Patch the thread so the background body never executes.
        with patch("src.controller.schema_import_runs_manager.threading.Thread") as MockThread:
            run_id = manager.start_run(db_session, req, user_id="alice@example.com", user_token=None)
            MockThread.assert_called_once()
            MockThread.return_value.start.assert_called_once()

        run = schema_import_runs_repo.get(db_session, run_id)
        assert run is not None
        assert run.status == "pending"
        assert run.user_id == "alice@example.com"
        assert run.connection_id == str(req.connection_id)
        # A progress notification was created and its id stored on the run.
        notifications.create_notification.assert_called_once()
        assert run.notification_id == f"schema-import-{run_id}"
        # Cancel event registered for the live run.
        assert run_id in manager._cancel_events

    def test_start_run_enforces_concurrency_cap(self, db_session):
        manager, _ = self._manager()
        for i in range(MAX_CONCURRENT_RUNS_PER_USER):
            schema_import_runs_repo.create(db_session, run_id=f"run{i}", user_id="alice@example.com")
            schema_import_runs_repo.update_status(db_session, f"run{i}", "running")
        db_session.commit()

        with patch("src.controller.schema_import_runs_manager.threading.Thread"), \
                pytest.raises(ValueError, match="Concurrent import limit"):
            manager.start_run(db_session, _import_request(), user_id="alice@example.com")

    def test_cancel_run_unknown_returns_false(self, db_session):
        manager, _ = self._manager()
        assert manager.cancel_run("nope") is False

    def test_cancel_run_sets_event(self, db_session):
        manager, _ = self._manager()
        with patch("src.controller.schema_import_runs_manager.threading.Thread"):
            run_id = manager.start_run(db_session, _import_request(), user_id="alice@example.com")
        assert manager.cancel_run(run_id) is True
        assert manager._cancel_events[run_id].is_set()
