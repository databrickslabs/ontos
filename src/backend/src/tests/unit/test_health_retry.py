"""POST /api/health/retry while the app is running (#613).

The workspace banner's Retry button calls this endpoint on a running app. It must
not start a second job poller per click, must not block other requests while it
works, and must re-initialize the managers only once the workspace is back.
"""

import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from src import app as app_module


class _FakeJobsManager:
    """A job manager whose poller is a real thread, like JobsManager's."""

    def __init__(self):
        self._stop = threading.Event()
        self._thread = None

    def start_background_polling(self, interval_seconds: int = 300):
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._stop.wait, name="FakeJobsManagerPoller", daemon=True
        )
        self._thread.start()

    def stop_background_polling(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)


def _alive_pollers() -> int:
    return sum(
        1 for t in threading.enumerate() if t.name == "FakeJobsManagerPoller" and t.is_alive()
    )


def _fake_initialize_managers(app):
    """Replace the managers like initialize_managers does: a new job manager with its poller."""
    app.state.settings_manager = object()
    app.state.jobs_manager = _FakeJobsManager()
    app.state.jobs_manager.start_background_polling()
    app.state.health["ws_ok"] = True


@pytest.fixture
def running_app_without_workspace():
    """The app after a startup where only the workspace client failed."""
    state = app_module.app.state
    saved = {
        name: getattr(state, name, None) for name in ("health", "settings_manager", "jobs_manager")
    }
    state.health = {
        "db_ok": True,
        "ws_ok": False,
        "seed_ok": True,
        "warnings": ["The Databricks workspace client could not be created."],
        "warning_details": [{"code": "workspace_client_unavailable", "message": "", "params": {}}],
    }
    state.settings_manager = object()
    state.jobs_manager = _FakeJobsManager()
    state.jobs_manager.start_background_polling()
    yield state
    if state.jobs_manager:
        state.jobs_manager.stop_background_polling()
    for name, value in saved.items():
        setattr(state, name, value)


def test_retries_while_the_workspace_is_down_reinitialize_nothing(running_app_without_workspace):
    client = TestClient(app_module.app)
    with patch.object(
        app_module, "get_workspace_client", side_effect=ValueError("no such profile")
    ), patch.object(app_module, "initialize_managers") as init, patch.object(
        app_module, "initialize_database"
    ) as init_db:
        for _ in range(3):
            response = client.post("/api/health/retry")
            assert response.status_code == 200
            assert response.json()["health"]["ws_ok"] is False

    init.assert_not_called()
    init_db.assert_not_called()
    assert _alive_pollers() == 1


def test_two_retries_leave_one_poller_once_the_workspace_is_back(running_app_without_workspace):
    client = TestClient(app_module.app)
    old_jobs_manager = running_app_without_workspace.jobs_manager
    with patch.object(app_module, "get_workspace_client", return_value=object()), patch.object(
        app_module, "initialize_managers", side_effect=_fake_initialize_managers
    ) as init, patch.object(app_module, "_seed_default_workflows"), patch.object(
        app_module, "initialize_database"
    ) as init_db:
        first = client.post("/api/health/retry")
        second = client.post("/api/health/retry")

    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["health"]["ws_ok"] is True
    # The managers were rebuilt once, with the old poller stopped first.
    assert init.call_count == 1
    init_db.assert_not_called()
    assert old_jobs_manager._thread is not None and not old_jobs_manager._thread.is_alive()
    assert running_app_without_workspace.jobs_manager is not old_jobs_manager
    assert _alive_pollers() == 1


@pytest.mark.asyncio
async def test_health_answers_while_a_retry_runs(running_app_without_workspace):
    def slow_workspace_client(settings=None):
        time.sleep(1.0)
        raise ValueError("unreachable host")

    transport = httpx.ASGITransport(app=app_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with patch.object(
            app_module, "get_workspace_client", side_effect=slow_workspace_client
        ), patch.object(app_module, "initialize_database"), patch.object(
            # Before the fix, the retry re-ran the whole startup on the event loop.
            app_module, "initialize_managers", side_effect=lambda app: time.sleep(1.0)
        ), patch.object(app_module, "_seed_default_workflows"):
            started = time.monotonic()
            retry = asyncio.create_task(client.post("/api/health/retry"))
            await asyncio.sleep(0.1)
            health = await client.get("/api/health")
            # Measured from the retry's start: a retry blocking the event loop
            # would hold this request for the whole second.
            elapsed = time.monotonic() - started
            retry_response = await retry

    assert health.status_code == 200
    assert elapsed < 0.6
    assert retry_response.status_code == 200


@pytest.mark.asyncio
async def test_concurrent_retries_initialize_the_managers_once(running_app_without_workspace):
    calls = SimpleNamespace(count=0)

    def counting_initialize(app):
        calls.count += 1
        time.sleep(0.3)
        _fake_initialize_managers(app)

    transport = httpx.ASGITransport(app=app_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with patch.object(app_module, "get_workspace_client", return_value=object()), patch.object(
            app_module, "initialize_managers", side_effect=counting_initialize
        ), patch.object(app_module, "_seed_default_workflows"), patch.object(
            app_module, "initialize_database"
        ):
            responses = await asyncio.gather(
                client.post("/api/health/retry"), client.post("/api/health/retry")
            )

    assert [r.status_code for r in responses] == [200, 200]
    assert calls.count == 1
    assert _alive_pollers() == 1


def test_a_database_outage_still_runs_the_full_startup():
    state = app_module.app.state
    saved = {name: getattr(state, name, None) for name in ("health", "settings_manager")}
    state.health = {"db_ok": False, "ws_ok": False, "seed_ok": True, "warnings": []}
    state.settings_manager = None
    try:
        with patch.object(app_module, "initialize_database") as init_db, patch.object(
            app_module, "initialize_managers", side_effect=lambda app: app.state.health.update(ws_ok=True)
        ) as init, patch.object(app_module, "_seed_default_workflows"):
            response = TestClient(app_module.app).post("/api/health/retry")
        assert response.status_code == 200
        init_db.assert_called_once()
        init.assert_called_once()
        assert state.health["db_ok"] is True
    finally:
        for name, value in saved.items():
            setattr(state, name, value)


class _FakeSession:
    def __init__(self):
        self.rolled_back = False
        self.closed = False

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_a_recovery_retry_closes_the_replaced_managers_session(running_app_without_workspace):
    old_session = _FakeSession()
    new_session = _FakeSession()
    running_app_without_workspace.manager_db_session = old_session

    def initialize_with_a_new_session(app):
        _fake_initialize_managers(app)
        app.state.manager_db_session = new_session

    try:
        with patch.object(app_module, "get_workspace_client", return_value=object()), patch.object(
            app_module, "initialize_managers", side_effect=initialize_with_a_new_session
        ), patch.object(app_module, "_seed_default_workflows"), patch.object(
            app_module, "initialize_database"
        ):
            response = TestClient(app_module.app).post("/api/health/retry")

        assert response.status_code == 200
        # Before the fix the old session stayed open ("idle in transaction").
        assert old_session.rolled_back and old_session.closed
        assert not new_session.closed
    finally:
        running_app_without_workspace.manager_db_session = None


def test_a_partial_re_initialization_keeps_the_old_session(running_app_without_workspace):
    old_session = _FakeSession()
    running_app_without_workspace.manager_db_session = old_session

    def failing_initialize(app):
        app.state.manager_db_session = _FakeSession()
        app.state.health["ws_ok"] = True
        app.state.health["warning_details"].append(
            {"code": "manager_init_failed", "message": "", "params": {}}
        )

    try:
        with patch.object(app_module, "get_workspace_client", return_value=object()), patch.object(
            app_module, "initialize_managers", side_effect=failing_initialize
        ), patch.object(app_module, "_seed_default_workflows"), patch.object(
            app_module, "initialize_database"
        ):
            TestClient(app_module.app).post("/api/health/retry")

        # Some old managers may still use it.
        assert not old_session.closed
    finally:
        running_app_without_workspace.manager_db_session = None
