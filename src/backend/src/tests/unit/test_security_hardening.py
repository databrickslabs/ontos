"""Regression tests for chat tool permission checks and PROD test-identity guard."""
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from src.common.config import Settings
from src.tools.base import BaseTool, ToolContext, ToolResult
from src.tools.registry import ToolRegistry


class _Tool(BaseTool):
    def __init__(self, scope):
        self.name = f"tool_{scope}"
        self.required_scope = scope
        self.ran = False

    async def execute(self, ctx, **kwargs):
        self.ran = True
        return ToolResult(success=True, data={"ok": True})


async def _run(scope, user=None, request=None):
    tool = _Tool(scope)
    registry = ToolRegistry()
    registry.register(tool)
    ctx = ToolContext(db=MagicMock(), settings=MagicMock(), user=user, request=request)
    result = await registry.execute(tool.name, ctx)
    return tool, result


ENFORCE = 'src.common.authorization.enforce_feature_permission'


@pytest.mark.asyncio
async def test_write_tool_denied_when_user_lacks_permission():
    deny = AsyncMock(side_effect=HTTPException(status_code=403))
    with patch(ENFORCE, deny):
        tool, result = await _run("data-products:write", user=MagicMock(), request=MagicMock())
    assert not tool.ran and not result.success
    feature, level = deny.call_args.args[:2]
    assert feature == "data-products" and level.value == "Read/Write"


@pytest.mark.asyncio
async def test_tool_runs_when_permission_granted():
    allow = AsyncMock(return_value=None)
    with patch(ENFORCE, allow):
        tool, result = await _run("contracts:read", user=MagicMock(), request=MagicMock())
    assert tool.ran and result.success
    feature, level = allow.call_args.args[:2]
    assert feature == "data-contracts" and level.value == "Read-only"


@pytest.mark.asyncio
async def test_gated_tool_denied_without_user_context():
    tool, result = await _run("tags:write")
    assert not tool.ran and not result.success


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["*", "unknown:read"])
async def test_unknown_or_admin_scope_fails_closed(scope):
    tool, result = await _run(scope, user=MagicMock(), request=MagicMock())
    assert not tool.ran and not result.success


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [None, "analytics:read", "search:read"])
async def test_ungated_scopes_run_without_feature_check(scope):
    tool, result = await _run(scope)
    assert tool.ran and result.success


def _settings(**overrides):
    return Settings(_env_file=None, APP_AUDIT_LOG_DIR="/tmp", **overrides)


@pytest.mark.parametrize("overrides", [
    {"TEST_USER_TOKEN": "secret"},
    {"MOCK_USER_DETAILS": True},
])
def test_test_identity_rejected_in_prod(overrides):
    with pytest.raises(ValidationError, match="must not be set when ENV=PROD"):
        _settings(ENV="PROD", **overrides)


def test_test_identity_allowed_outside_prod():
    assert _settings(ENV="DEV", TEST_USER_TOKEN="secret", MOCK_USER_DETAILS=True).TEST_USER_TOKEN == "secret"
