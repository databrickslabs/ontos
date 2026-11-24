"""Route-level tests for the demo-data gate (settings-general ADMIN or DEMO_SETUP_TOKEN)."""
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.app import app
from src.common import config as _config
from src.common.authorization import DEMO_SETUP_TOKEN_HEADER, get_user_details_from_sdk
from src.common.manager_dependencies import get_audit_manager
from src.models.users import UserInfo

DUMMY_TOKEN = "dummy-setup-token-of-thirty-two-chars"
SHORT_TOKEN = "short-setup-token"
# A bogus preset makes the load route answer 400 right after the gate, without touching data.
LOAD = "/api/settings/demo-data/load?preset=bogus"
CLEAR = "/api/settings/demo-data?dry_run=true"


@pytest.fixture(autouse=True)
def audit():
    audit_manager = MagicMock()
    app.dependency_overrides[get_audit_manager] = lambda: audit_manager
    yield audit_manager
    app.dependency_overrides.pop(get_audit_manager, None)


@pytest.fixture
def empty_demo_pack(monkeypatch):
    """The load route reads an empty pack: it answers 200 and is audited, loading nothing."""
    real_read_text = Path.read_text

    def _read_text(self, *args, **kwargs):
        if self.name.startswith("demo_data_") and self.suffix == ".sql":
            return ""
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _read_text)


@pytest.fixture
def set_token(test_settings):
    previous = _config._settings
    _config._settings = test_settings

    def _set(value):
        test_settings.DEMO_SETUP_TOKEN = value

    yield _set
    _config._settings = previous


@pytest.fixture
def as_non_admin(client: TestClient):
    async def _override():
        return UserInfo(
            username="plain", email="plain@example.com", user="plain", ip="127.0.0.1",
            groups=["nobody"],
        )

    previous = app.dependency_overrides.get(get_user_details_from_sdk)
    app.dependency_overrides[get_user_details_from_sdk] = _override
    yield client
    if previous is not None:
        app.dependency_overrides[get_user_details_from_sdk] = previous


def test_non_admin_gets_403_on_both_routes(as_non_admin, set_token):
    set_token(None)
    assert as_non_admin.post(LOAD).status_code == 403
    assert as_non_admin.delete(CLEAR).status_code == 403


def test_admin_passes_the_gate(client, set_token):
    set_token(None)
    assert client.post(LOAD).status_code == 400  # past the gate, rejected by preset validation
    assert client.delete(CLEAR).status_code == 200


def test_valid_token_passes_for_non_admin(as_non_admin, set_token):
    set_token(DUMMY_TOKEN)
    headers = {DEMO_SETUP_TOKEN_HEADER: DUMMY_TOKEN}
    assert as_non_admin.post(LOAD, headers=headers).status_code == 400
    assert as_non_admin.delete(CLEAR, headers=headers).status_code == 200


def test_wrong_token_gets_403(as_non_admin, set_token):
    set_token(DUMMY_TOKEN)
    headers = {DEMO_SETUP_TOKEN_HEADER: "wrong"}
    assert as_non_admin.post(LOAD, headers=headers).status_code == 403
    assert as_non_admin.delete(CLEAR, headers=headers).status_code == 403


def test_token_refused_when_setting_unset(as_non_admin, set_token):
    set_token(None)
    headers = {DEMO_SETUP_TOKEN_HEADER: DUMMY_TOKEN}
    assert as_non_admin.post(LOAD, headers=headers).status_code == 403
    assert as_non_admin.delete(CLEAR, headers=headers).status_code == 403


def _audit_vias(audit):
    return {
        call.kwargs["action"]: call.kwargs["details"].get("via")
        for call in audit.log_action_background.call_args_list
    }


def test_audit_records_setup_token_access(as_non_admin, set_token, audit, empty_demo_pack):
    set_token(DUMMY_TOKEN)
    headers = {DEMO_SETUP_TOKEN_HEADER: DUMMY_TOKEN}
    assert as_non_admin.post("/api/settings/demo-data/load", headers=headers).status_code == 200
    assert as_non_admin.delete(CLEAR, headers=headers).status_code == 200
    assert _audit_vias(audit) == {"LOAD_DEMO_DATA": "setup_token", "CLEAR_DEMO_DATA": "setup_token"}
    for call in audit.log_action_background.call_args_list:
        assert DUMMY_TOKEN not in repr(call)


def test_audit_records_admin_access(client, set_token, audit, empty_demo_pack):
    set_token(DUMMY_TOKEN)
    assert client.post("/api/settings/demo-data/load").status_code == 200
    assert client.delete(CLEAR).status_code == 200
    assert _audit_vias(audit) == {"LOAD_DEMO_DATA": "admin", "CLEAR_DEMO_DATA": "admin"}


def test_short_token_is_not_configured_and_logged(as_non_admin, test_settings, caplog):
    from src.common.config import MIN_DEMO_SETUP_TOKEN_LENGTH, Settings

    caplog.set_level(logging.ERROR)
    values = {**test_settings.model_dump(), "DEMO_SETUP_TOKEN": SHORT_TOKEN}
    short_settings = Settings(**values)
    assert short_settings.DEMO_SETUP_TOKEN is None
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert any(
        "DEMO_SETUP_TOKEN" in m and str(MIN_DEMO_SETUP_TOKEN_LENGTH) in m for m in errors
    )
    assert all(SHORT_TOKEN not in m for m in caplog.messages)

    previous = _config._settings
    _config._settings = short_settings
    try:
        headers = {DEMO_SETUP_TOKEN_HEADER: SHORT_TOKEN}
        assert as_non_admin.post(LOAD, headers=headers).status_code == 403
        assert as_non_admin.delete(CLEAR, headers=headers).status_code == 403
    finally:
        _config._settings = previous


def test_short_token_assigned_later_is_refused(as_non_admin, set_token):
    set_token(SHORT_TOKEN)
    headers = {DEMO_SETUP_TOKEN_HEADER: SHORT_TOKEN}
    assert as_non_admin.post(LOAD, headers=headers).status_code == 403
    assert as_non_admin.delete(CLEAR, headers=headers).status_code == 403
