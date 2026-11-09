"""Startup problems reach /api/health as codes, never as exception text (#613 follow-up, #601)."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.common.health_status import HEALTH_MESSAGES, health_issue
from src.common.middleware import MaintenanceMiddleware
from src.controller.approvals_manager import ApprovalsManager
from src.utils import startup_tasks
from src.utils.startup_tasks import StartupSeedError, initialize_managers

SECRET = "token=dapi-SECRET host=https://internal.example /Users/someone/.databrickscfg"
LOCALES = Path(__file__).resolve().parents[4] / "frontend" / "src" / "i18n" / "locales"


def _run_initialize_managers(settings_manager_error):
    app = SimpleNamespace(state=SimpleNamespace(health={"warnings": []}))
    with patch.object(startup_tasks, "get_workspace_client", side_effect=RuntimeError(SECRET)), \
         patch.object(startup_tasks, "get_session_factory", return_value=MagicMock()), \
         patch.object(startup_tasks, "get_registry", return_value=MagicMock()), \
         patch.object(startup_tasks, "SettingsManager", side_effect=settings_manager_error):
        initialize_managers(app)
    return app


def _assert_no_secret(health):
    assert "SECRET" not in json.dumps(health)


def test_workspace_and_manager_failures_are_codes_without_exception_text():
    app = _run_initialize_managers(RuntimeError(f"connect failed: {SECRET}"))
    health = app.state.health

    assert health["ws_ok"] is False
    assert [w["code"] for w in health["warning_details"]] == [
        "workspace_client_unavailable",
        "manager_init_failed",
    ]
    assert health["warnings"] == [
        HEALTH_MESSAGES["workspace_client_unavailable"],
        HEALTH_MESSAGES["manager_init_failed"],
    ]
    _assert_no_secret(health)


def test_seeding_failure_is_a_code_without_exception_text():
    app = _run_initialize_managers(StartupSeedError(f"Default role/team seeding failed: {SECRET}"))
    health = app.state.health

    assert health["seed_ok"] is False
    assert health["seed_error_code"] == "seeding_failed"
    assert health["seed_error"] == HEALTH_MESSAGES["seeding_failed"]
    assert "seeding_failed" in [w["code"] for w in health["warning_details"]]
    _assert_no_secret(health)


def test_approvals_manager_is_stored_at_startup():
    app = _run_initialize_managers(RuntimeError("stop after the stateless managers"))
    assert isinstance(app.state.approvals_manager, ApprovalsManager)


@pytest.mark.parametrize(
    "health,code",
    [
        ({"db_ok": False, "seed_ok": True, "db_error": SECRET}, "database_unavailable"),
        ({"db_ok": True, "seed_ok": False, "seed_error": SECRET}, "seeding_failed"),
    ],
)
def test_maintenance_json_carries_the_code_not_the_stored_text(health, code):
    app = FastAPI()
    app.add_middleware(MaintenanceMiddleware)
    app.state.health = health

    @app.get("/api/things")
    def things():
        return []

    response = TestClient(app).get("/api/things", headers={"accept": "application/json"})

    assert response.status_code == 503
    assert response.json() == {"error": "maintenance", "detail": health_issue(code)}


def test_retry_reports_a_database_failure_as_a_code():
    from src import app as app_module

    saved = getattr(app_module.app.state, "health", None)
    app_module.app.state.health = {"db_ok": False, "ws_ok": False, "seed_ok": True, "warnings": []}
    try:
        with patch.object(
            app_module, "initialize_database", side_effect=RuntimeError(f"psycopg2: {SECRET}")
        ):
            response = TestClient(app_module.app).post("/api/health/retry")
        health = app_module.app.state.health
        assert response.status_code == 503
        assert response.json()["detail"] == health_issue("database_unavailable")
        assert health["db_error_code"] == "database_unavailable"
        _assert_no_secret(health)
    finally:
        app_module.app.state.health = saved


@pytest.mark.parametrize("locale", ["de", "en", "es", "fr", "it", "ja", "nl", "pt"])
def test_every_code_is_translated(locale):
    issues = json.loads((LOCALES / locale / "navigation.json").read_text())["health"]["issues"]
    assert set(issues) == set(HEALTH_MESSAGES)
    if locale == "en":
        assert issues == HEALTH_MESSAGES
