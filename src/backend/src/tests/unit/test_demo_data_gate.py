"""Unit tests for the demo-data route gate (settings ADMIN or DEMO_SETUP_TOKEN)."""
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from src.common.authorization import (
    DEMO_SETUP_TOKEN_HEADER,
    is_valid_demo_setup_token,
    require_demo_admin_or_setup_token,
)
from src.common.features import FeatureAccessLevel

DUMMY_TOKEN = "dummy-setup-token"


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
        "src.common.authorization.get_user_team_role_overrides", AsyncMock(return_value=None)
    ):
        return await require_demo_admin_or_setup_token(request, token, settings, user, auth_manager)


@pytest.mark.asyncio
async def test_admin_allowed_without_token():
    assert await _call(level=FeatureAccessLevel.ADMIN) is None


@pytest.mark.asyncio
async def test_non_admin_denied():
    with pytest.raises(HTTPException) as exc:
        await _call(level=FeatureAccessLevel.READ_WRITE)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_valid_token_allows_non_admin():
    assert await _call(token=DUMMY_TOKEN, configured=DUMMY_TOKEN) is None


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
    assert result is None


def test_token_comparison_edge_cases():
    assert is_valid_demo_setup_token(DUMMY_TOKEN, DUMMY_TOKEN)
    assert not is_valid_demo_setup_token("", "")
    assert not is_valid_demo_setup_token(None, DUMMY_TOKEN)
    assert not is_valid_demo_setup_token(DUMMY_TOKEN, "")
    assert not is_valid_demo_setup_token("café", DUMMY_TOKEN)


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
