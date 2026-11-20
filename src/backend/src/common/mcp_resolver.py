"""Thin MCP client for Authority Resolution resource refs.

Discovery goes through the Databricks SDK (``ws.ai_gateway.list_mcp_services``);
invocation speaks MCP streamable-HTTP JSON-RPC directly over ``requests`` using
the WorkspaceClient's own auth headers, so OBO vs app-SP is just a matter of
which client is passed in. Kept dependency-free (no ``mcp``/``databricks-mcp``)
because the app's requirements are hash-locked.
"""
import json
import re
import time
from typing import Any, Dict, Iterable, List, Optional

import requests
from jinja2 import StrictUndefined, Undefined
from jinja2.sandbox import SandboxedEnvironment

from src.common.logging import get_logger

logger = get_logger(__name__)

MCP_PROTOCOL_VERSION = "2025-06-18"
DEFAULT_CALL_TIMEOUT_S = 3.0
SERVICE_PREFIX = "mcp-services/"
BUILTIN_PARENT = "schemas/system.ai"

_jinja = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False)


class McpResolverError(Exception):
    """Raised for any MCP discovery/invocation failure. ``kind`` is one of
    ``timeout`` | ``permission`` | ``protocol`` | ``tool_error`` | ``config``."""

    def __init__(self, message: str, kind: str = "protocol"):
        super().__init__(message)
        self.kind = kind


def short_service_name(service_name: str) -> str:
    return service_name[len(SERVICE_PREFIX):] if service_name.startswith(SERVICE_PREFIX) else service_name


def server_url(ws: Any, service_name: str) -> str:
    host = (ws.config.host or "").rstrip("/")
    return f"{host}/ai-gateway/mcp-services/{short_service_name(service_name)}"


def list_mcp_services(ws: Any, parents: Iterable[str]) -> List[Dict[str, Any]]:
    """MCP services visible to ``ws`` under each ``schemas/<catalog>.<schema>`` parent,
    de-duplicated by name. A parent the caller can't read is skipped, not fatal."""
    from databricks.sdk.service.catalog import ListMcpServicesRequestView

    seen: Dict[str, Dict[str, Any]] = {}
    for parent in parents:
        try:
            for svc in ws.ai_gateway.list_mcp_services(
                parent=parent, view=ListMcpServicesRequestView.BASIC,
            ):
                if not svc.name or svc.name in seen:
                    continue
                short = short_service_name(svc.name)
                seen[svc.name] = {
                    "name": svc.name,
                    "short_name": short,
                    "schema": ".".join(short.split(".")[:2]),
                    "comment": svc.comment,
                }
        except Exception as e:
            logger.warning(f"list_mcp_services failed for parent {parent}: {e}")
    return sorted(seen.values(), key=lambda s: (s["schema"], s["short_name"]))


def _parse_body(resp: requests.Response, request_id: int) -> Dict[str, Any]:
    ctype = resp.headers.get("Content-Type", "")
    if "text/event-stream" in ctype:
        for line in resp.text.splitlines():
            if not line.startswith("data:"):
                continue
            try:
                msg = json.loads(line[5:].strip())
            except ValueError:
                continue
            if isinstance(msg, dict) and msg.get("id") == request_id:
                return msg
        raise McpResolverError("no JSON-RPC response in event stream")
    try:
        return resp.json()
    except ValueError:
        raise McpResolverError(f"non-JSON MCP response ({ctype or 'no content-type'})")


class McpHttpClient:
    """One MCP session against a single service. Not thread-safe; create per resolve."""

    def __init__(self, ws: Any, service_name: str, timeout: float = DEFAULT_CALL_TIMEOUT_S,
                 session: Optional[requests.Session] = None, deadline: Optional["Deadline"] = None):
        self._ws = ws
        self._url = server_url(ws, service_name)
        self._timeout = timeout
        self._deadline = deadline
        self._http = session or requests.Session()
        self._session_id: Optional[str] = None
        self._next_id = 0
        self._initialized = False

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        }
        try:
            headers.update(self._ws.config.authenticate())
        except Exception as e:
            raise McpResolverError(f"could not obtain credentials: {e}", kind="permission")
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _post(self, payload: Dict[str, Any]) -> requests.Response:
        timeout = self._deadline.call_timeout(self._timeout) if self._deadline else self._timeout
        try:
            resp = self._http.post(self._url, json=payload, headers=self._headers(), timeout=timeout)
        except requests.Timeout:
            raise McpResolverError("resolver_timeout", kind="timeout")
        except requests.RequestException as e:
            raise McpResolverError(f"MCP transport error: {e}")
        if resp.status_code in (401, 403):
            raise McpResolverError(
                f"MCP permission denied ({resp.status_code}): {resp.text[:200]}", kind="permission",
            )
        if resp.status_code >= 400:
            raise McpResolverError(f"MCP HTTP {resp.status_code}: {resp.text[:200]}")
        return resp

    def _rpc(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        self._next_id += 1
        rid = self._next_id
        resp = self._post({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        sid = resp.headers.get("Mcp-Session-Id")
        if sid:
            self._session_id = sid
        msg = _parse_body(resp, rid)
        if not isinstance(msg, dict):
            raise McpResolverError("MCP response is not a JSON-RPC object")
        if "error" in msg:
            err = msg["error"] or {}
            raise McpResolverError(f"MCP error {err.get('code')}: {err.get('message')}")
        return msg.get("result")

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._rpc("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "ontos-authority-resolver", "version": "1"},
        })
        # Notifications carry no id and expect 202/empty — don't parse a body.
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._initialized = True

    def list_tools(self) -> List[Dict[str, Any]]:
        self._ensure_initialized()
        result = self._rpc("tools/list") or {}
        return [
            {
                "name": t.get("name"),
                "description": t.get("description"),
                "input_schema": t.get("inputSchema"),
                "output_schema": t.get("outputSchema"),
            }
            for t in result.get("tools", [])
        ]

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        self._ensure_initialized()
        result = self._rpc("tools/call", {"name": name, "arguments": arguments}) or {}
        return unwrap_tool_result(result)


def unwrap_tool_result(result: Dict[str, Any]) -> Any:
    """``structuredContent`` when present, else the joined text content (JSON-decoded
    if it parses). ``isError`` results raise."""
    texts = [c.get("text", "") for c in result.get("content") or [] if c.get("type") == "text"]
    if result.get("isError"):
        raise McpResolverError("; ".join(texts) or "tool reported an error", kind="tool_error")
    if result.get("structuredContent") is not None:
        return result["structuredContent"]
    text = "\n".join(texts)
    try:
        return json.loads(text)
    except ValueError:
        return text


def render_params(template: Any, context: Dict[str, Any]) -> Any:
    """Render every string leaf of ``template`` as a sandboxed Jinja template.
    A string that is exactly one ``{{ expr }}`` keeps the expression's native type."""
    if isinstance(template, dict):
        return {k: render_params(v, context) for k, v in template.items()}
    if isinstance(template, list):
        return [render_params(v, context) for v in template]
    if not isinstance(template, str) or "{" not in template:
        return template
    try:
        m = re.fullmatch(r"\s*\{\{(.+?)\}\}\s*", template)
        if m and "{{" not in m.group(1) and "}}" not in m.group(1):
            value = _jinja.compile_expression(m.group(1).strip(), undefined_to_none=False)(**context)
            if isinstance(value, Undefined):
                raise McpResolverError(f"undefined variable in {template!r}", kind="config")
            return value
        return _jinja.from_string(template).render(**context)
    except McpResolverError:
        raise
    except Exception as e:
        raise McpResolverError(f"param template error in {template!r}: {e}", kind="config")


_POINTER_TOKEN = re.compile(r"\.([A-Za-z_][A-Za-z0-9_\-]*)|\[(\d+)\]|\[['\"]([^'\"]+)['\"]\]")


def apply_result_pointer(value: Any, pointer: Optional[str]) -> Any:
    """Minimal JSONPath: ``$``, ``$.a.b``, ``$.a[0]``, ``$['key with space']``."""
    if not pointer or pointer.strip() == "$":
        return value
    p = pointer.strip()
    if not p.startswith("$"):
        raise McpResolverError(f"result pointer must start with '$': {pointer}", kind="config")
    pos, cur = 1, value
    while pos < len(p):
        m = _POINTER_TOKEN.match(p, pos)
        if not m:
            raise McpResolverError(f"unsupported result pointer syntax: {pointer}", kind="config")
        key, idx, qkey = m.groups()
        try:
            cur = cur[int(idx)] if idx is not None else cur[key if key is not None else qkey]
        except (KeyError, IndexError, TypeError):
            raise McpResolverError(f"result pointer {pointer} did not match the tool response", kind="tool_error")
        pos = m.end()
    return cur


def stringify(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, default=str)


class Deadline:
    """Wall-clock budget shared by every MCP call within one top-level resolve."""

    def __init__(self, seconds: float):
        self._end = time.monotonic() + seconds

    def remaining(self) -> float:
        return self._end - time.monotonic()

    def call_timeout(self, per_call: float = DEFAULT_CALL_TIMEOUT_S) -> float:
        left = self.remaining()
        if left <= 0:
            raise McpResolverError("resolver_timeout", kind="timeout")
        return min(per_call, left)
