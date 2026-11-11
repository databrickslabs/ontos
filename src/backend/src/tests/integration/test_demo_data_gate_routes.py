"""Route-level tests for the demo-data gate (settings-general ADMIN or DEMO_SETUP_TOKEN)."""
import pytest
from fastapi.testclient import TestClient

from src.app import app
from src.common import config as _config
from src.common.authorization import DEMO_SETUP_TOKEN_HEADER, get_user_details_from_sdk
from src.common.manager_dependencies import get_audit_manager
from src.models.users import UserInfo

DUMMY_TOKEN = "dummy-setup-token"
# A bogus preset makes the load route answer 400 right after the gate, without touching data.
LOAD = "/api/settings/demo-data/load?preset=bogus"
CLEAR = "/api/settings/demo-data?dry_run=true"


@pytest.fixture(autouse=True)
def _stub_audit(monkeypatch):
    from unittest.mock import MagicMock

    app.dependency_overrides[get_audit_manager] = lambda: MagicMock()
    yield
    app.dependency_overrides.pop(get_audit_manager, None)


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
