"""Unit tests for the demo-data route gate (settings ADMIN or DEMO_SETUP_TOKEN)."""
import inspect
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from src.common.authorization import (
    DEMO_SETUP_TOKEN_HEADER,
    is_valid_demo_setup_token,
    require_demo_admin_or_setup_token,
)
from src.common.features import FeatureAccessLevel

DUMMY_TOKEN = "dummy-setup-token-of-thirty-two-chars"
SHORT_TOKEN = "short-setup-token"


async def _call(*, token=None, configured=None, level=FeatureAccessLevel.NONE):
    request = MagicMock()
    request.app.state.settings_manager = None
    settings = MagicMock()
    settings.DEMO_SETUP_TOKEN = configured
    user = MagicMock(user="u", email="u@example.com", groups=["g"])
    auth_manager = MagicMock()
    auth_manager.get_user_effective_permissions.return_value = {"settings-general": level}
    auth_manager.has_permission.side_effect = (
        lambda perms, feat, req: perms.get(feat) == FeatureAccessLevel.ADMIN
    )
    with patch(
        "src.common.authorization.lookup_user_team_roles", MagicMock(return_value=[])
    ):
        return await require_demo_admin_or_setup_token(request, token, settings, user, auth_manager)


@pytest.mark.asyncio
async def test_admin_allowed_without_token():
    assert await _call(level=FeatureAccessLevel.ADMIN) == "admin"


@pytest.mark.asyncio
async def test_non_admin_denied():
    with pytest.raises(HTTPException) as exc:
        await _call(level=FeatureAccessLevel.READ_WRITE)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_valid_token_allows_non_admin():
    assert await _call(token=DUMMY_TOKEN, configured=DUMMY_TOKEN) == "setup_token"


@pytest.mark.asyncio
async def test_wrong_token_denied_for_non_admin():
    with pytest.raises(HTTPException) as exc:
        await _call(token="wrong", configured=DUMMY_TOKEN)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_token_refused_when_setting_unset():
    with pytest.raises(HTTPException) as exc:
        await _call(token=DUMMY_TOKEN, configured=None)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_wrong_token_does_not_block_admin():
    result = await _call(token="wrong", configured=DUMMY_TOKEN, level=FeatureAccessLevel.ADMIN)
    assert result == "admin"


def test_token_comparison_edge_cases():
    assert is_valid_demo_setup_token(DUMMY_TOKEN, DUMMY_TOKEN)
    assert not is_valid_demo_setup_token("", "")
    assert not is_valid_demo_setup_token(None, DUMMY_TOKEN)
    assert not is_valid_demo_setup_token(DUMMY_TOKEN, "")
    assert not is_valid_demo_setup_token("café", DUMMY_TOKEN)
    assert not is_valid_demo_setup_token(SHORT_TOKEN, SHORT_TOKEN)


@pytest.mark.asyncio
async def test_short_configured_token_denied_for_non_admin():
    with pytest.raises(HTTPException) as exc:
        await _call(token=SHORT_TOKEN, configured=SHORT_TOKEN)
    assert exc.value.status_code == 403


def _settings(token):
    from src.common.config import Settings

    return Settings(
        DATABRICKS_HOST="https://test-databricks.com",
        DATABRICKS_WAREHOUSE_ID="w",
        DATABRICKS_CATALOG="c",
        DATABRICKS_SCHEMA="s",
        DATABRICKS_VOLUME="v",
        ENV="TEST",
        DEMO_SETUP_TOKEN=token,
    )


def test_short_token_setting_is_dropped_with_an_error(caplog):
    import logging

    from src.common.config import MIN_DEMO_SETUP_TOKEN_LENGTH

    assert MIN_DEMO_SETUP_TOKEN_LENGTH == 32
    caplog.set_level(logging.ERROR)
    assert _settings(SHORT_TOKEN).DEMO_SETUP_TOKEN is None
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("DEMO_SETUP_TOKEN" in m and "32" in m for m in errors)
    assert all(SHORT_TOKEN not in m for m in caplog.messages)


def test_token_of_minimum_length_is_kept(caplog):
    import logging

    caplog.set_level(logging.ERROR)
    token = "x" * 32
    assert _settings(token).DEMO_SETUP_TOKEN == token
    assert _settings(None).DEMO_SETUP_TOKEN is None
    assert not [r for r in caplog.records if "DEMO_SETUP_TOKEN" in r.getMessage()]


def test_both_routes_use_the_gate_and_header_is_a_security_scheme():
    from src.app import app
    from src.routes import settings_routes

    for fn in (settings_routes.load_demo_data, settings_routes.clear_demo_data):
        deps = [
            p.default.dependency
            for p in inspect.signature(fn).parameters.values()
            if hasattr(p.default, "dependency")
        ]
        assert require_demo_admin_or_setup_token in deps
    schemes = app.openapi()["components"]["securitySchemes"]
    assert any(s.get("name") == DEMO_SETUP_TOKEN_HEADER for s in schemes.values())
