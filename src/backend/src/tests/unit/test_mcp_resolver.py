"""Unit tests for the dependency-free MCP client used by Authority Resolution refs."""
import json
from types import SimpleNamespace

import pytest
import requests

from src.common import mcp_resolver
from src.common.mcp_resolver import (
    Deadline, McpHttpClient, McpResolverError,
    apply_result_pointer, render_params, unwrap_tool_result,
)


def _ws(host="https://ws.example.com"):
    return SimpleNamespace(config=SimpleNamespace(
        host=host, authenticate=lambda: {"Authorization": "Bearer t"},
    ))


class _Resp:
    def __init__(self, status=200, body=None, ctype="application/json", headers=None, text=None):
        self.status_code = status
        self.headers = {"Content-Type": ctype, **(headers or {})}
        self._body = body
        self.text = text if text is not None else json.dumps(body) if body is not None else ""

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


class _FakeSession:
    """Scripted MCP server: replies per JSON-RPC method, records requests."""

    def __init__(self, replies):
        self.replies = replies
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        reply = self.replies[json["method"]]
        return reply(json) if callable(reply) else reply


def test_server_url_strips_service_prefix():
    assert mcp_resolver.server_url(_ws("https://h/"), "mcp-services/system.ai.github") == \
        "https://h/ai-gateway/mcp-services/system.ai.github"


def test_render_params_keeps_native_type_and_sandboxes():
    ctx = {"actor_identity": "a@x", "value": 0.2, "ar": {"domain_context": {"market": "DE"}}}
    out = render_params(
        {"who": "{{ actor_identity }}", "v": "{{ value }}", "label": "m={{ ar.domain_context.market }}",
         "nested": ["{{ value }}", 3]},
        ctx,
    )
    assert out == {"who": "a@x", "v": 0.2, "label": "m=DE", "nested": [0.2, 3]}
    with pytest.raises(McpResolverError) as e:
        render_params({"x": "{{ missing_var }}"}, ctx)
    assert e.value.kind == "config"
    with pytest.raises(McpResolverError):
        render_params({"x": "{{ ''.__class__.__mro__ }}"}, ctx)


def test_apply_result_pointer():
    doc = {"user": {"roles": [{"name": "Director"}]}, "odd key": 7}
    assert apply_result_pointer(doc, "$") is doc
    assert apply_result_pointer(doc, "$.user.roles[0].name") == "Director"
    assert apply_result_pointer(doc, "$['odd key']") == 7
    with pytest.raises(McpResolverError):
        apply_result_pointer(doc, "$.user.missing")
    with pytest.raises(McpResolverError):
        apply_result_pointer(doc, "user.roles")


def test_unwrap_tool_result_variants():
    assert unwrap_tool_result({"structuredContent": {"a": 1}, "content": []}) == {"a": 1}
    assert unwrap_tool_result({"content": [{"type": "text", "text": '{"b": 2}'}]}) == {"b": 2}
    assert unwrap_tool_result({"content": [{"type": "text", "text": "plain"}]}) == "plain"
    with pytest.raises(McpResolverError) as e:
        unwrap_tool_result({"isError": True, "content": [{"type": "text", "text": "boom"}]})
    assert e.value.kind == "tool_error"


def test_client_handshake_session_id_and_sse_call():
    sse = 'event: message\ndata: {"jsonrpc":"2.0","id":2,"result":{"structuredContent":{"role":"Director"}}}\n\n'
    session = _FakeSession({
        "initialize": _Resp(body={"jsonrpc": "2.0", "id": 1, "result": {}}, headers={"Mcp-Session-Id": "s-1"}),
        "notifications/initialized": _Resp(status=202, ctype=""),
        "tools/call": _Resp(ctype="text/event-stream", text=sse),
    })
    client = McpHttpClient(_ws(), "mcp-services/c.s.org", session=session)
    assert client.call_tool("get_role", {"email": "a@x"}) == {"role": "Director"}
    methods = [c["json"]["method"] for c in session.calls]
    assert methods == ["initialize", "notifications/initialized", "tools/call"]
    assert "Mcp-Session-Id" not in session.calls[0]["headers"]
    assert session.calls[2]["headers"]["Mcp-Session-Id"] == "s-1"
    assert session.calls[2]["headers"]["Authorization"] == "Bearer t"
    assert session.calls[2]["json"]["params"] == {"name": "get_role", "arguments": {"email": "a@x"}}


def test_client_maps_403_and_timeout():
    denied = _FakeSession({"initialize": _Resp(status=403, text="no EXECUTE")})
    with pytest.raises(McpResolverError) as e:
        McpHttpClient(_ws(), "mcp-services/c.s.x", session=denied).list_tools()
    assert e.value.kind == "permission"

    def _timeout(_payload):
        raise requests.Timeout()
    slow = _FakeSession({"initialize": _timeout})
    with pytest.raises(McpResolverError) as e:
        McpHttpClient(_ws(), "mcp-services/c.s.x", session=slow).list_tools()
    assert e.value.kind == "timeout"


def test_exhausted_deadline_short_circuits_before_request():
    session = _FakeSession({})
    client = McpHttpClient(_ws(), "mcp-services/c.s.x", session=session, deadline=Deadline(-1))
    with pytest.raises(McpResolverError) as e:
        client.list_tools()
    assert e.value.kind == "timeout"
    assert session.calls == []


def test_list_tools_shape():
    session = _FakeSession({
        "initialize": _Resp(body={"jsonrpc": "2.0", "id": 1, "result": {}}),
        "notifications/initialized": _Resp(status=202, ctype=""),
        "tools/list": _Resp(body={"jsonrpc": "2.0", "id": 2, "result": {"tools": [
            {"name": "t", "description": "d", "inputSchema": {"type": "object"}},
        ]}}),
    })
    assert McpHttpClient(_ws(), "mcp-services/c.s.x", session=session).list_tools() == [
        {"name": "t", "description": "d", "input_schema": {"type": "object"}, "output_schema": None},
    ]


def test_list_mcp_services_dedupes_and_skips_failing_parent():
    svc = lambda n: SimpleNamespace(name=n, comment=None)  # noqa: E731

    def _list(parent, view):
        if parent == "schemas/bad.schema":
            raise PermissionError("no USE_SCHEMA")
        return [svc("mcp-services/system.ai.github"), svc("mcp-services/system.ai.github")]

    ws = SimpleNamespace(ai_gateway=SimpleNamespace(list_mcp_services=_list))
    out = mcp_resolver.list_mcp_services(ws, ["schemas/system.ai", "schemas/bad.schema"])
    assert [s["short_name"] for s in out] == ["system.ai.github"]
    assert out[0]["schema"] == "system.ai"


def test_render_params_multiple_expressions_render_as_string():
    assert render_params({"k": "{{ a }}-{{ b }}"}, {"a": 1, "b": 2}) == {"k": "1-2"}


def test_non_object_jsonrpc_body_and_auth_failure_raise_resolver_errors():
    session = _FakeSession({"initialize": _Resp(body=["not", "an", "object"])})
    with pytest.raises(McpResolverError):
        McpHttpClient(_ws(), "mcp-services/c.s.x", session=session).list_tools()

    def _no_creds():
        raise RuntimeError("token refresh failed")
    ws = SimpleNamespace(config=SimpleNamespace(host="https://h", authenticate=_no_creds))
    with pytest.raises(McpResolverError) as e:
        McpHttpClient(ws, "mcp-services/c.s.x", session=_FakeSession({})).list_tools()
    assert e.value.kind == "permission"
