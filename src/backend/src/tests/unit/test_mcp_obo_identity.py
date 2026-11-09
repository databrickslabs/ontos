"""Unit tests for MCP tool-context identity selection (OBO vs service principal).

The MCP handler runs UC-touching tools on-behalf-of the forwarded user when the
request carries an ``x-forwarded-access-token`` (i.e. it came through the app
proxy / native integration), and otherwise as the app service principal. These
tests exercise that selection without the HTTP layer.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import src.routes.mcp_routes as mcp_routes
from src.routes.mcp_routes import MCP_AUTH_FAILED, MCPError, MCPHandler

SP_SENTINEL = object()
OBO_SENTINEL = object()


def _handler(headers: dict, audit_manager=None) -> MCPHandler:
    app = SimpleNamespace(state=SimpleNamespace(workspace_client=SP_SENTINEL))
    request = SimpleNamespace(headers=headers, app=app,
                               client=SimpleNamespace(host="127.0.0.1"))
    return MCPHandler(
        db=None,
        settings=MagicMock(),
        token_info=MagicMock(name="token", created_by="caller@x", scopes=[]),
        request=request,
        audit_manager=audit_manager,
        session_id="session-1",
    )


def test_forwarded_token_selects_obo(monkeypatch):
    monkeypatch.setattr(mcp_routes, "get_obo_workspace_client", lambda req, settings: OBO_SENTINEL)
    h = _handler({"x-forwarded-access-token": "dapi-user-token"})
    ctx = h._create_tool_context()
    assert ctx.workspace_client is OBO_SENTINEL
    assert h._identity_mode == "obo"


def test_no_forwarded_token_uses_service_principal(monkeypatch):
    # If OBO were (wrongly) consulted, this would blow up the test.
    monkeypatch.setattr(mcp_routes, "get_obo_workspace_client",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("OBO must not be called")))
    h = _handler({})
    ctx = h._create_tool_context()
    assert ctx.workspace_client is SP_SENTINEL
    assert h._identity_mode == "service_principal"


def test_obo_failure_raises_mcp_error_no_fallback(monkeypatch):
    """A forwarded token that fails OBO setup must raise, NOT silently fall
    back to the service principal. Otherwise the caller's SQL runs with SP
    grants they can't see — reviewer concern on #937."""
    def _boom(req, settings):
        raise RuntimeError("token rejected")
    monkeypatch.setattr(mcp_routes, "get_obo_workspace_client", _boom)
    h = _handler({"x-forwarded-access-token": "bad-token"})
    with pytest.raises(MCPError) as exc_info:
        h._create_tool_context()
    assert exc_info.value.code == MCP_AUTH_FAILED
    assert "forwarded" in exc_info.value.message.lower()
    # Identity never flips to service_principal; the raise aborts the request.
    assert h._identity_mode != "service_principal"


def test_obo_failure_audits_identity_rejection(monkeypatch):
    """A rejected forwarded token must be audited the way SCOPE_VIOLATION is
    — otherwise a bad-token path leaves nothing but a log warning (#937
    reviewer note). The raise happens AFTER the audit is written."""
    def _boom(req, settings):
        raise RuntimeError("token verification failed")
    monkeypatch.setattr(mcp_routes, "get_obo_workspace_client", _boom)

    audit_manager = MagicMock()
    h = _handler({"x-forwarded-access-token": "bad-token"}, audit_manager=audit_manager)
    with pytest.raises(MCPError):
        h._create_tool_context()

    assert audit_manager.log_action.called, "identity rejection must be audited"
    call = audit_manager.log_action.call_args
    kwargs = call.kwargs
    assert kwargs["action"] == "IDENTITY_REJECTED"
    assert kwargs["success"] is False
    assert kwargs["details"]["reason"] == "obo_setup_failed"
    assert "token verification failed" in kwargs["details"]["error"]
