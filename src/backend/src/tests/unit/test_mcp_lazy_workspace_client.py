"""The MCP handler builds the Unity Catalog workspace client only when a tool reads it (#1002).

The forwarded user is verified once per request before any tool runs (the
identity checks live in test_tool_write_levels); what is lazy is the UC client,
OBO or app service principal.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import src.routes.mcp_routes as mcp_routes
import src.tools.caller as tool_caller
from src.common.features import FeatureAccessLevel
from src.models.users import UserInfo
from src.routes.mcp_routes import MCP_AUTH_FAILED, MCPError, MCPHandler
from src.tools.base import ToolContext, ToolResult

SP_CLIENT = object()
OBO_CLIENT = object()
TOKEN = {"x-forwarded-access-token": "user-token"}
SUE = UserInfo(email="sue@example.com", username="sue@example.com", user="Sue", ip=None,
               groups=["g"])
NON_UC_TOOL = "get_domain"
UC_TOOL = "list_catalogs"


def _run(coro):
    return asyncio.run(coro)


def _handler(headers, audit=None, me_error=None):
    users_manager = MagicMock()
    if me_error is not None:
        users_manager.get_current_user.side_effect = me_error
    else:
        users_manager.get_current_user.return_value = SUE
    app = SimpleNamespace(state=SimpleNamespace(workspace_client=SP_CLIENT,
                                                users_manager=users_manager))
    request = SimpleNamespace(headers=headers, app=app, state=SimpleNamespace(),
                              client=SimpleNamespace(host="127.0.0.1"))
    return MCPHandler(
        db=None, settings=MagicMock(),
        token_info=SimpleNamespace(id="t1", name="tok", created_by="a@x", scopes=["*"]),
        request=request, audit_manager=audit or MagicMock(), session_id="s1",
    )


def _fake_tool(handler, name, reads):
    """Replace a tool's execute; ``reads`` is how many times it reads the client."""
    seen = []

    async def _fake(ctx, **kwargs):
        for _ in range(reads):
            seen.append(ctx.workspace_client)
        return ToolResult(success=True, data={"ran": name})

    handler._tool_registry.get(name).execute = _fake
    return seen


def _audits(audit, action):
    return [c.kwargs for c in audit.log_action.call_args_list if c.kwargs["action"] == action]


@pytest.fixture
def obo(monkeypatch):
    built = []

    def _build(*a, **k):
        built.append(1)
        return OBO_CLIENT

    monkeypatch.setattr(mcp_routes, "get_obo_workspace_client", _build)

    async def _levels(email, groups, request):
        return {"data-domains": FeatureAccessLevel.READ_WRITE}

    monkeypatch.setattr(tool_caller, "resolve_effective_permissions", _levels)
    return built


def _call(h, name):
    return _run(h._handle_tools_call({"name": name, "arguments": {}}))


def test_a_tool_that_ignores_the_client_never_builds_it(obo, monkeypatch):
    h = _handler({})
    factory_calls = []
    monkeypatch.setattr(h, "_resolve_workspace_client",
                        lambda: factory_calls.append(1) or SP_CLIENT)
    _fake_tool(h, NON_UC_TOOL, reads=0)
    assert _call(h, NON_UC_TOOL)["isError"] is False
    assert factory_calls == []
    entry = _audits(h._audit_manager, "TOOL_CALL")[0]["details"]
    assert entry["identity_mode"] is None


def test_a_forwarded_token_tool_that_ignores_the_client_builds_only_the_verification(obo):
    h = _handler(TOKEN)
    _fake_tool(h, NON_UC_TOOL, reads=0)
    assert _call(h, NON_UC_TOOL)["isError"] is False
    # One OBO client: the identity verification. None for the UC client.
    assert obo == [1]
    assert _audits(h._audit_manager, "TOOL_CALL")[0]["details"]["identity_mode"] is None


def test_a_uc_tool_builds_the_service_principal_client_once(obo, monkeypatch):
    h = _handler({})
    resolve = h._resolve_workspace_client
    factory_calls = []
    monkeypatch.setattr(h, "_resolve_workspace_client",
                        lambda: factory_calls.append(1) or resolve())
    seen = _fake_tool(h, UC_TOOL, reads=3)
    assert _call(h, UC_TOOL)["isError"] is False
    assert seen == [SP_CLIENT] * 3 and factory_calls == [1]
    details = _audits(h._audit_manager, "TOOL_CALL")[0]["details"]
    assert details["identity_mode"] == "service_principal"


def test_a_uc_tool_builds_the_obo_client_once_besides_the_verification(obo):
    h = _handler(TOKEN)
    seen = _fake_tool(h, UC_TOOL, reads=3)
    assert _call(h, UC_TOOL)["isError"] is False
    assert seen == [OBO_CLIENT] * 3
    assert obo == [1, 1]  # verification + the UC client
    assert _audits(h._audit_manager, "TOOL_CALL")[0]["details"]["identity_mode"] == "obo"


def test_an_obo_client_that_cannot_be_built_rejects_without_service_principal_fallback(
    obo, monkeypatch
):
    h = _handler(TOKEN)
    state = {"n": 0}

    def _build(*a, **k):
        state["n"] += 1
        if state["n"] == 1:  # the identity verification succeeds
            return OBO_CLIENT
        raise RuntimeError("token rejected")

    monkeypatch.setattr(mcp_routes, "get_obo_workspace_client", _build)
    seen = _fake_tool(h, UC_TOOL, reads=2)
    with pytest.raises(MCPError) as exc_info:
        _call(h, UC_TOOL)
    assert exc_info.value.code == MCP_AUTH_FAILED
    assert exc_info.value.message == mcp_routes.IDENTITY_REJECTED_MESSAGE
    assert seen == []  # the tool never got a client, in particular not the SP's
    rejected = _audits(h._audit_manager, "IDENTITY_REJECTED")
    assert len(rejected) == 1 and rejected[0]["details"]["reason"] == "obo_setup_failed"
    assert state["n"] == 2  # no second attempt
    assert _audits(h._audit_manager, "TOOL_CALL")[0]["details"]["identity_mode"] is None


def test_a_tool_that_swallows_the_client_failure_is_still_rejected(obo, monkeypatch):
    h = _handler(TOKEN)
    state = {"n": 0}

    def _build(*a, **k):
        state["n"] += 1
        if state["n"] == 1:
            return OBO_CLIENT
        raise RuntimeError("token rejected")

    monkeypatch.setattr(mcp_routes, "get_obo_workspace_client", _build)

    async def _swallow(ctx, **kwargs):
        try:
            ctx.workspace_client
        except MCPError:
            pass
        return ToolResult(success=True, data={})

    h._tool_registry.get(UC_TOOL).execute = _swallow
    with pytest.raises(MCPError) as exc_info:
        _call(h, UC_TOOL)
    assert exc_info.value.code == MCP_AUTH_FAILED


def _failing_obo(monkeypatch):
    state = {"n": 0}

    def _build(*a, **k):
        state["n"] += 1
        if state["n"] == 1:  # the identity verification succeeds
            return OBO_CLIENT
        raise RuntimeError("token rejected")

    monkeypatch.setattr(mcp_routes, "get_obo_workspace_client", _build)
    return state


def test_a_tool_that_wraps_the_client_refusal_in_another_error_is_still_rejected(
    obo, monkeypatch
):
    h = _handler(TOKEN)
    _failing_obo(monkeypatch)

    async def _wrap(ctx, **kwargs):
        try:
            ctx.workspace_client
        except MCPError as e:
            raise ValueError("wrapped") from e

    h._tool_registry.get(UC_TOOL).execute = _wrap
    with pytest.raises(MCPError) as exc_info:
        _call(h, UC_TOOL)
    assert exc_info.value.code == MCP_AUTH_FAILED


def test_an_mcp_error_from_a_tool_is_not_turned_into_a_tool_failure(obo):
    h = _handler({})

    async def _refuse(ctx, **kwargs):
        raise MCPError(-32602, "bad params")

    h._tool_registry.get(UC_TOOL).execute = _refuse
    with pytest.raises(MCPError) as exc_info:
        _call(h, UC_TOOL)
    assert exc_info.value.code == -32602


def test_a_second_read_after_a_failed_build_reuses_the_refusal(obo, monkeypatch):
    h = _handler(TOKEN)
    state = _failing_obo(monkeypatch)
    reads = []

    async def _read_twice(ctx, **kwargs):
        for _ in range(2):
            try:
                ctx.workspace_client
            except MCPError as e:
                reads.append(e)
        return ToolResult(success=True, data={})

    h._tool_registry.get(UC_TOOL).execute = _read_twice
    with pytest.raises(MCPError):
        _call(h, UC_TOOL)
    assert state["n"] == 2  # verification + one UC attempt
    assert len(reads) == 2 and reads[0] is reads[1]
    assert len(_audits(h._audit_manager, "IDENTITY_REJECTED")) == 1


def test_the_tool_call_audit_of_the_refusal_links_to_it(obo, monkeypatch):
    h = _handler(TOKEN)
    _failing_obo(monkeypatch)
    _fake_tool(h, UC_TOOL, reads=1)
    with pytest.raises(MCPError):
        _call(h, UC_TOOL)
    details = _audits(h._audit_manager, "TOOL_CALL")[0]["details"]
    assert details["is_error"] is True and details["error_code"] == "obo_setup_failed"


@pytest.mark.parametrize("tool", [NON_UC_TOOL, UC_TOOL])
def test_a_forwarded_token_that_fails_verification_rejects_every_tool(obo, tool):
    """Pins #1250: the identity is verified before any tool, UC or not."""
    h = _handler(TOKEN, me_error=RuntimeError("expired"))
    seen = _fake_tool(h, tool, reads=1)
    with pytest.raises(MCPError) as exc_info:
        _call(h, tool)
    assert exc_info.value.code == MCP_AUTH_FAILED
    assert seen == []
    rejected = _audits(h._audit_manager, "IDENTITY_REJECTED")
    assert len(rejected) == 1 and rejected[0]["details"]["reason"] == "caller_unresolved"


class TestToolContextWorkspaceClient:
    def test_a_client_passed_directly_is_used_and_assignable(self):
        client = MagicMock()
        ctx = ToolContext(db=MagicMock(), settings=MagicMock(), workspace_client=client)
        assert ctx.workspace_client is client
        other = MagicMock()
        ctx.workspace_client = other
        assert ctx.workspace_client is other

    def test_without_a_client_or_factory_it_is_none(self):
        ctx = ToolContext(db=MagicMock(), settings=MagicMock())
        assert ctx.workspace_client is None

    def test_a_direct_client_wins_over_the_factory(self):
        factory = MagicMock()
        client = MagicMock()
        ctx = ToolContext(db=MagicMock(), settings=MagicMock(), workspace_client=client,
                          workspace_client_factory=factory)
        assert ctx.workspace_client is client
        factory.assert_not_called()

    def test_the_factory_runs_on_first_read_only(self):
        factory = MagicMock(return_value="client")
        ctx = ToolContext(db=MagicMock(), settings=MagicMock(),
                          workspace_client_factory=factory)
        factory.assert_not_called()
        repr(ctx)  # does not build it
        assert ctx.workspace_client == "client" and ctx.workspace_client == "client"
        factory.assert_called_once()

    def test_a_factory_error_reaches_the_reader(self):
        ctx = ToolContext(db=MagicMock(), settings=MagicMock(),
                          workspace_client_factory=MagicMock(side_effect=ValueError("x")))
        with pytest.raises(ValueError):
            ctx.workspace_client
