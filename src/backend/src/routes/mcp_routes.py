"""
FastAPI routes for MCP (Model Context Protocol) server.

Implements a JSON-RPC 2.0 endpoint for MCP clients to interact with application tools.
Supports both standard HTTP POST/JSON responses and SSE (Server-Sent Events) transport.
"""

import asyncio
import json
import secrets
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from src.common.config import Settings, get_settings
from src.common.database import get_db
from src.common.workspace_client import get_obo_workspace_client
from src.common.dependencies import AuditManagerDep
from src.common.logging import get_logger
from src.controller.audit_manager import AuditManager
from src.controller.mcp_tokens_manager import MCPTokensManager, MCPTokenInfo
from src.models.mcp import JSONRPCRequest, JSONRPCError, JSONRPCResponse
from src.common.api_errors import new_error_id
from src.common.manager_dependencies import get_users_manager
from src.models.users import UserInfo
from src.tools.base import (
    ToolCaller,
    ToolContext,
    ToolResult,
    check_tool_permission,
    tool_failed_message,
)
from src.tools.caller import (
    MCP_FORWARDED_TOKEN_AUTH_PATH,
    mcp_api_key_caller,
    resolve_tool_caller,
)
from src.tools.registry import create_default_registry

logger = get_logger(__name__)

# No prefix on the router itself: it is mounted at two roots below so the same
# handlers serve both the native MCP path and the legacy one.
router = APIRouter(tags=["MCP Server"])


def register_routes(app):
    """Register MCP routes with the FastAPI app.

    Mounted at two roots:
    - ``/mcp``     — canonical, native MCP integration path.
    - ``/api/mcp`` — legacy alias kept for existing clients; hidden from the
      OpenAPI schema to avoid duplicate operation ids.
    """
    app.include_router(router, prefix="/mcp")
    app.include_router(router, prefix="/api/mcp", include_in_schema=False)


# JSON-RPC 2.0 Error Codes
JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603

# Custom MCP Error Codes
MCP_AUTH_FAILED = -32001
MCP_AUTH_MISSING_SCOPE = -32002

# MCP Protocol Version
# MCP protocol revisions this server is compatible with, newest first. Per the
# MCP spec's initialize negotiation, the server echoes back the client's
# requested protocolVersion when it's one of these, otherwise it responds with
# its newest. Our JSON-RPC surface (initialize / tools.list / tools.call / ping
# / notifications) is stable across these revisions and uses no version-specific
# features, so declaring support for all of them is safe. Clients that speak a
# newer revision (e.g. the Databricks AI Gateway MCP client) reject a server
# that answers with an older version than they requested, so a single hardcoded
# version breaks them — hence the echo-with-fallback below.
SUPPORTED_PROTOCOL_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]
MCP_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]

# Feature ID for audit logging
MCP_FEATURE_ID = "mcp"

# The forwarded user token (Databricks Apps proxy / native integration).
FORWARDED_TOKEN_HEADER = "x-forwarded-access-token"
# Client message for every identity rejection; the reason is in the audit entry.
IDENTITY_REJECTED_MESSAGE = "The caller's identity could not be verified."

# Session storage (in-memory for now, could be moved to Redis/DB for production)
_sessions: Dict[str, Dict[str, Any]] = {}


def make_error_response(
    code: int,
    message: str,
    data: Any = None,
    request_id: Optional[Union[str, int]] = None
) -> JSONRPCResponse:
    """Create a JSON-RPC error response."""
    return JSONRPCResponse(
        error=JSONRPCError(code=code, message=message, data=data),
        id=request_id
    )


def make_success_response(
    result: Any,
    request_id: Optional[Union[str, int]] = None
) -> JSONRPCResponse:
    """Create a JSON-RPC success response."""
    return JSONRPCResponse(result=result, id=request_id)


def dump_jsonrpc_response(resp: JSONRPCResponse) -> Dict[str, Any]:
    """Serialize per JSON-RPC 2.0: exactly ONE of result/error.

    JSONRPCResponse.model_dump() emits both keys (one null), which strict
    clients (e.g. the MCP Python SDK used by Kasal/CrewAI) reject.
    """
    out: Dict[str, Any] = {"jsonrpc": "2.0", "id": resp.id}
    if resp.error is not None:
        out["error"] = resp.error.model_dump()
    else:
        out["result"] = resp.result
    return out


def generate_session_id() -> str:
    """Generate a cryptographically secure session ID."""
    return secrets.token_urlsafe(32)


def generate_event_id() -> str:
    """Generate a unique event ID for SSE resumability."""
    return f"evt_{secrets.token_urlsafe(16)}"


def wants_sse(request: Request) -> bool:
    """Check if client wants SSE response based on Accept header."""
    accept = request.headers.get("accept", "")
    return "text/event-stream" in accept


def format_sse_event(
    data: Dict[str, Any],
    event_id: Optional[str] = None,
    event_type: str = "message"
) -> Dict[str, Any]:
    """Format data as an SSE event dict for sse-starlette."""
    event = {
        "event": event_type,
        "data": json.dumps(data, default=str),
    }
    if event_id:
        event["id"] = event_id
    return event


class MCPHandler:
    """Handler for MCP JSON-RPC methods."""
    
    def __init__(
        self,
        db: Session,
        settings: Settings,
        token_info: MCPTokenInfo,
        request: Request,
        audit_manager: Optional[AuditManager] = None,
        session_id: Optional[str] = None
    ):
        self._db = db
        self._settings = settings
        self._token_info = token_info
        self._request = request
        self._audit_manager = audit_manager
        self._session_id = session_id
        self._tool_registry = create_default_registry()
        # Set when a tool context is built: "obo" (ran as the forwarded user) or
        # "service_principal" (app identity). Audited so UC data scope is traceable.
        self._identity_mode: Optional[str] = None
        # The caller the tools act for, resolved once per request (_resolve_caller).
        self._caller: Optional[ToolCaller] = None
    
    def _get_username(self) -> str:
        # The verified forwarded user when there is one, else the token's creator.
        if self._caller is not None and self._caller.email:
            return self._caller.email
        return self._token_info.created_by or self._token_info.name
    
    def _get_ip_address(self) -> Optional[str]:
        return _client_ip(self._request)
    
    def _audit(self, *, action: str, success: bool, details: Optional[Dict[str, Any]] = None):
        """Log an audit record if audit manager is available."""
        if not self._audit_manager:
            return
        self._audit_manager.log_action(
            db=self._db,
            username=self._get_username(),
            ip_address=self._get_ip_address(),
            feature=MCP_FEATURE_ID,
            action=action,
            success=success,
            details=details,
        )
    
    async def handle(self, rpc_request: JSONRPCRequest) -> JSONRPCResponse:
        """Route the request to the appropriate handler."""
        method = rpc_request.method
        params = rpc_request.params or {}
        request_id = rpc_request.id
        
        handlers = {
            "initialize": self._handle_initialize,
            "notifications/initialized": self._handle_initialized,
            "ping": self._handle_ping,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
        }
        
        handler = handlers.get(method)
        if not handler:
            return make_error_response(
                JSONRPC_METHOD_NOT_FOUND,
                f"Method not found: {method}",
                request_id=request_id
            )
        
        try:
            if _has_forwarded_token(self._request):
                # The verified user is the caller (and the audit username) of
                # every method, not only of tool calls.
                await self._resolve_caller(
                    params.get("name") if method == "tools/call" else method
                )
            result = await handler(params)
            return make_success_response(result, request_id=request_id)
        except MCPError as e:
            return make_error_response(e.code, e.message, e.data, request_id=request_id)
        except Exception as e:
            logger.error(f"Error handling MCP method {method}: {e}", exc_info=True)
            return make_error_response(
                JSONRPC_INTERNAL_ERROR,
                f"Internal error: {str(e)}",
                request_id=request_id
            )
    
    async def _handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle initialize request."""
        # Store client info in session if available
        client_info = params.get("clientInfo", {})
        if self._session_id and self._session_id in _sessions:
            _sessions[self._session_id]["client_info"] = client_info
            _sessions[self._session_id]["initialized"] = True

        # Protocol version negotiation: echo the client's requested version when
        # we support it, otherwise fall back to our newest. Answering with an
        # older version than the client asked for makes strict clients (e.g. the
        # Databricks AI Gateway) abort with "unsupported protocol version".
        requested_version = params.get("protocolVersion")
        negotiated_version = (
            requested_version
            if requested_version in SUPPORTED_PROTOCOL_VERSIONS
            else MCP_PROTOCOL_VERSION
        )

        self._audit(
            action="SESSION_CREATE",
            success=True,
            details={
                "session_id": self._session_id,
                "token_name": self._token_info.name,
                "client_info": client_info,
                "requested_protocol_version": requested_version,
                "negotiated_protocol_version": negotiated_version,
            },
        )

        return {
            "protocolVersion": negotiated_version,
            "serverInfo": {
                "name": "ontos-mcp-server",
                "version": "1.0.0"
            },
            "capabilities": {
                "tools": {}
            }
        }
    
    async def _handle_initialized(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle initialized notification."""
        return {}
    
    async def _handle_ping(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle ping request."""
        return {"pong": True, "timestamp": datetime.now(timezone.utc).isoformat()}
    
    async def _handle_tools_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/list request, filtering by token scopes."""
        all_tools = self._tool_registry.get_mcp_definitions()
        
        # Filter tools by scope
        filtered_tools = []
        for tool_def in all_tools:
            tool = self._tool_registry.get(tool_def["name"])
            if tool:
                required_scope = getattr(tool, "required_scope", "*")
                if self._has_scope(required_scope):
                    filtered_tools.append(tool_def)
        
        return {"tools": filtered_tools}
    
    async def _handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/call request."""
        tool_name = params.get("name")
        tool_args = params.get("arguments", {})
        
        if not tool_name:
            raise MCPError(JSONRPC_INVALID_PARAMS, "Missing tool name")
        
        # Get the tool
        tool = self._tool_registry.get(tool_name)
        if not tool:
            raise MCPError(JSONRPC_METHOD_NOT_FOUND, f"Tool not found: {tool_name}")
        
        # Check scope
        required_scope = getattr(tool, "required_scope", "*")
        if not self._has_scope(required_scope):
            self._audit(
                action="SCOPE_VIOLATION",
                success=False,
                details={
                    "tool_name": tool_name,
                    "required_scope": required_scope,
                    "token_scopes": self._token_info.scopes,
                    "token_name": self._token_info.name,
                    "session_id": self._session_id,
                },
            )
            raise MCPError(
                MCP_AUTH_MISSING_SCOPE,
                f"Missing required scope: {required_scope}",
                {"required_scope": required_scope, "token_scopes": self._token_info.scopes}
            )
        
        # Create tool context (also sets self._identity_mode)
        ctx = self._create_tool_context()
        ctx.caller = await self._resolve_caller(tool_name)

        # Execute the tool with audit logging
        success = False
        details_for_audit: Dict[str, Any] = {
            "tool_name": tool_name,
            "token_name": self._token_info.name,
            "token_id": str(self._token_info.id) if getattr(self._token_info, "id", None) else None,
            "session_id": self._session_id,
            "identity_mode": self._identity_mode,
            "auth_path": ctx.caller.auth_path,
        }
        try:
            result = check_tool_permission(tool, ctx) or await tool.execute(ctx, **tool_args)
            is_error = not result.success
            details_for_audit["is_error"] = is_error
            success = not is_error
            if result.error_code:
                details_for_audit["error_code"] = result.error_code
            if result.denied_reason:
                # The read rule answered some items as not found: not a success.
                details_for_audit["denied_reason"] = result.denied_reason
                success = False
            
            if result.success:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result.data, default=str)
                        }
                    ],
                    "isError": False
                }
            else:
                details_for_audit["tool_error"] = result.error
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": result.error or "Unknown error"
                        }
                    ],
                    "isError": True
                }
                
        except Exception as e:
            error_id = new_error_id()
            logger.error(
                "Error executing tool %s (error id %s): %s", tool_name, error_id, e, exc_info=True
            )
            details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
            details_for_audit["error_id"] = error_id
            return {
                "content": [
                    {
                        "type": "text",
                        "text": tool_failed_message(error_id)
                    }
                ],
                "isError": True
            }
        finally:
            self._audit(action="TOOL_CALL", success=success, details=details_for_audit)
    
    def _has_scope(self, required_scope: str) -> bool:
        """Check if token has required scope."""
        # Tools may declare required_scope=None meaning "no scope required"
        # (e.g. get_app_state, search_ontos_handbook). Without this guard,
        # tools/list crashes on `":" in None` for any non-wildcard token.
        if not required_scope:
            return True
        scopes = self._token_info.scopes
        
        # Admin wildcard
        if "*" in scopes:
            return True
        
        # Exact match
        if required_scope in scopes:
            return True
        
        # Prefix wildcard
        if ":" in required_scope:
            prefix = required_scope.split(":")[0]
            if f"{prefix}:*" in scopes:
                return True
        
        return False
    
    def _resolve_workspace_client(self):
        """Pick the workspace client identity for UC-touching tools.

        When the request carries a Databricks-forwarded user token (i.e. it came
        through the app proxy / native integration), run tools on-behalf-of that
        user so Unity Catalog results are scoped to their grants — matching the
        in-app Ask Ontos path. Raw external token agents (no forwarded token) keep
        the app service-principal client, preserving the prior behavior.

        Fail-closed on bad forwarded tokens: if the token is present but OBO setup
        fails (expired/invalid), raise an auth error rather than silently falling
        back to the service principal — otherwise the caller's SQL would run with
        SP grants, which they can't see and shouldn't have.
        """
        app = self._request.app
        if self._request.headers.get("x-forwarded-access-token"):
            try:
                client = get_obo_workspace_client(self._request, self._settings)
            except Exception as e:
                logger.warning("OBO workspace client failed: %s", e)
                # Audit the rejection so a security investigator can trace it
                # the same way SCOPE_VIOLATION is recorded. The exception
                # otherwise aborts handle() before any audit row is written.
                self._audit(
                    action="IDENTITY_REJECTED",
                    success=False,
                    details={
                        "reason": "obo_setup_failed",
                        "error": str(e),
                        "token_name": self._token_info.name,
                        "session_id": self._session_id,
                    },
                )
                raise MCPError(
                    MCP_AUTH_FAILED,
                    "Forwarded identity could not be verified. "
                    "The forwarded access token was rejected (expired or invalid). "
                    "Not falling back to the service principal — the request would run "
                    "with grants the caller cannot see.",
                )
            self._identity_mode = "obo"
            return client
        self._identity_mode = "service_principal"
        return getattr(app.state, "workspace_client", None)

    async def _resolve_caller(self, tool_name: Optional[str]) -> ToolCaller:
        """The caller the tools act for, resolved once per request.

        With a forwarded user token: the user (or service principal) returned by
        the verified ``current_user.me()``; the X-Forwarded-Email header never
        names the caller. The token's scopes stay the ceiling. When the identity
        can't be verified the request fails and an ``IDENTITY_REJECTED`` audit
        entry records why. Without a forwarded token (API key only): the
        API-key policy, ``mcp_api_key_caller``.
        """
        if self._caller is not None:
            return self._caller
        if not _has_forwarded_token(self._request):
            self._caller = mcp_api_key_caller(self._token_info)
            return self._caller
        try:
            user = await verify_forwarded_user(self._request, self._settings)
        except MCPIdentityError as e:
            _log_identity_rejection(e.reason, tool_name, MCP_FORWARDED_TOKEN_AUTH_PATH)
            self._audit(
                action="IDENTITY_REJECTED",
                success=False,
                details={
                    "reason": e.reason,
                    "tool_name": tool_name,
                    "auth_path": MCP_FORWARDED_TOKEN_AUTH_PATH,
                    "token_name": self._token_info.name,
                    "session_id": self._session_id,
                },
            )
            raise MCPError(MCP_AUTH_FAILED, IDENTITY_REJECTED_MESSAGE)
        self._caller = await resolve_tool_caller(
            user, self._request, MCP_FORWARDED_TOKEN_AUTH_PATH, self._db
        )
        return self._caller

    def _create_tool_context(self) -> ToolContext:
        """Create a ToolContext for tool execution."""
        # Get managers from app.state if available
        app = self._request.app

        return ToolContext(
            db=self._db,
            settings=self._settings,
            workspace_client=self._resolve_workspace_client(),
            data_products_manager=getattr(app.state, "data_products_manager", None),
            data_contracts_manager=getattr(app.state, "data_contracts_manager", None),
            semantic_models_manager=getattr(app.state, "semantic_models_manager", None),
            costs_manager=None,  # Add if needed
            search_manager=getattr(app.state, "search_manager", None)
        )


class MCPError(Exception):
    """MCP-specific error with JSON-RPC code."""
    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(message)


def validate_api_key(
    db: Session,
    x_api_key: Optional[str]
) -> Optional[MCPTokenInfo]:
    """Validate the API key and return token info if valid."""
    if not x_api_key:
        return None

    token_manager = MCPTokensManager(db=db)
    return token_manager.validate_token(x_api_key)


def _forwarded_email(request: Request) -> Optional[str]:
    """
    Extract the caller's Databricks identity from the app-proxy forwarded headers.

    These headers are injected by the Databricks Apps OAuth2 proxy after it
    authenticates the user, so their presence means the request has already
    cleared the app-gate. Header-trust only — no OBO/SDK round-trip — matching
    the trust level the regular HTTP API places in the same headers.
    """
    return request.headers.get("X-Forwarded-Email") or request.headers.get("X-Forwarded-User")


def _client_ip(request: Request) -> Optional[str]:
    """The caller's address: the proxy's X-Real-Ip when present, else the socket peer."""
    real_ip = request.headers.get("X-Real-Ip")
    if real_ip:
        return real_ip
    return request.client.host if getattr(request, "client", None) else None


def _has_forwarded_token(request: Request) -> bool:
    return bool(request.headers.get(FORWARDED_TOKEN_HEADER))


class MCPIdentityError(Exception):
    """The forwarded identity was refused; ``reason`` is the audit code.

    ``forwarded_token_missing``: a keyless request without a forwarded user token.
    ``caller_unresolved``: ``current_user.me()`` failed for the forwarded token.
    ``forwarded_identity_mismatch``: X-Forwarded-Email names someone else.
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _log_identity_rejection(reason: str, tool_name: Optional[str], auth_path: str) -> None:
    logger.warning(
        "MCP identity rejected (%s): tool=%s auth_path=%s", reason, tool_name, auth_path
    )


async def verify_forwarded_user(request: Request, settings: Settings) -> UserInfo:
    """The identity behind the forwarded user token, from ``current_user.me()``.

    A service principal is resolved the same way, with its groups. The result is
    kept on ``request.state`` so a request verifies it once. Raises
    ``MCPIdentityError``.
    """
    state = getattr(request, "state", None)
    cached = getattr(state, "mcp_verified_user", None) if state is not None else None
    if cached is not None:
        return cached
    if not _has_forwarded_token(request):
        raise MCPIdentityError("forwarded_token_missing")
    try:
        obo_client = get_obo_workspace_client(request, settings)
        user = get_users_manager(request).get_current_user(
            obo_client=obo_client, real_ip=request.headers.get("X-Real-Ip")
        )
    except Exception as e:
        logger.warning("current_user.me() failed for the forwarded token: %s", type(e).__name__)
        raise MCPIdentityError("caller_unresolved") from e
    if not user or not (user.email or user.username):
        raise MCPIdentityError("caller_unresolved")
    forwarded = _forwarded_email(request)
    if forwarded:
        known = {str(v).lower() for v in (user.email, user.username) if v}
        if forwarded.lower() not in known:
            raise MCPIdentityError("forwarded_identity_mismatch")
    if state is not None:
        state.mcp_verified_user = user
    return user


def _audit_identity_rejection(audit_manager, db, request: Request, reason: str,
                              endpoint: str) -> None:
    _log_identity_rejection(reason, None, "mcp_keyless")
    audit_manager.log_action(
        db=db,
        username="anonymous",
        ip_address=_client_ip(request),
        feature=MCP_FEATURE_ID,
        action="IDENTITY_REJECTED",
        success=False,
        details={"reason": reason, "auth_path": "mcp_keyless", "endpoint": endpoint},
    )


async def resolve_mcp_principal(
    db: Session,
    x_api_key: Optional[str],
    request: Request,
    settings: Optional[Settings] = None,
) -> Optional[MCPTokenInfo]:
    """
    Resolve the caller of an MCP request to a token principal, or None to reject.

    Two paths:
    - A request carrying an ``X-API-Key`` is validated exactly as before; the
      keyless default is never consulted. (Who the tools then act for is decided
      per request by ``MCPHandler._resolve_caller``.)
    - A request with no key is the opt-in keyless path, inert unless an admin has
      designated an active default token. It is accepted only with a forwarded
      user token (``x-forwarded-access-token``): the caller is the identity from
      the verified ``current_user.me()``, stamped on the default token for audit
      attribution. The X-Forwarded-Email / X-Forwarded-User headers alone are not
      accepted, in every environment.

    Returns None (reject) when the key is invalid, or when there is no key and
    keyless access is not enabled or the request names no caller at all. Raises
    ``MCPIdentityError`` when a keyless request names a caller that can't be
    verified (no forwarded token, ``me()`` failed, or the headers disagree).
    """
    if x_api_key:
        return validate_api_key(db, x_api_key)

    if not _has_forwarded_token(request) and not _forwarded_email(request):
        return None
    from src.repositories.mcp_tokens_repository import mcp_tokens_repo

    if mcp_tokens_repo.get_keyless_default(db) is None:
        return None
    user = await verify_forwarded_user(request, settings or get_settings())

    token_manager = MCPTokensManager(db=db)
    return token_manager.resolve_keyless_default(user.email or user.username)


async def sse_event_generator(
    response_data: Dict[str, Any],
    session_id: Optional[str] = None
) -> AsyncGenerator[Dict[str, Any], None]:
    """Generate SSE events for a single response."""
    # Send initial event with empty data to prime the connection (per MCP spec)
    event_id = generate_event_id()
    yield format_sse_event({}, event_id=event_id, event_type="open")
    
    # Send the actual response
    event_id = generate_event_id()
    yield format_sse_event(response_data, event_id=event_id, event_type="message")


async def sse_stream_generator(
    token_info: MCPTokenInfo,
    session_id: str,
    request: Request
) -> AsyncGenerator[Dict[str, Any], None]:
    """Generate SSE events for an open stream (GET endpoint)."""
    # Send initial connection event
    event_id = generate_event_id()
    yield format_sse_event(
        {"type": "connection", "session_id": session_id},
        event_id=event_id,
        event_type="open"
    )
    
    # Keep the connection alive with periodic pings
    # This allows server-initiated messages in the future
    try:
        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                logger.info(f"SSE client disconnected: session={session_id}")
                break
            
            # Send a keepalive ping every 30 seconds
            await asyncio.sleep(30)
            
            if session_id in _sessions:
                event_id = generate_event_id()
                yield format_sse_event(
                    {"type": "ping", "timestamp": datetime.now(timezone.utc).isoformat()},
                    event_id=event_id,
                    event_type="ping"
                )
    except asyncio.CancelledError:
        logger.info(f"SSE stream cancelled: session={session_id}")
    finally:
        # Clean up session on disconnect
        if session_id in _sessions:
            logger.info(f"Cleaning up session: {session_id}")


@router.get("")
async def mcp_sse_stream(
    request: Request,
    audit_manager: AuditManagerDep,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    mcp_session_id: Optional[str] = Header(None, alias="MCP-Session-Id"),
):
    """
    MCP SSE stream endpoint (GET).
    
    Opens a Server-Sent Events stream for server-to-client messages.
    Requires Accept: text/event-stream header.
    """
    # Check Accept header
    if not wants_sse(request):
        raise HTTPException(
            status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
            detail="GET requires Accept: text/event-stream header"
        )
    
    # Resolve caller: X-API-Key token, or the keyless default for app-gate
    # authenticated requests with a verified forwarded user token, when enabled.
    try:
        token_info = await resolve_mcp_principal(db, x_api_key, request, settings)
    except MCPIdentityError as e:
        _audit_identity_rejection(audit_manager, db, request, e.reason, "GET")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=IDENTITY_REJECTED_MESSAGE
        )
    if not token_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key"
        )

    # Get or create session
    session_id = mcp_session_id
    if session_id and session_id not in _sessions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )
    
    if not session_id:
        session_id = generate_session_id()
        _sessions[session_id] = {
            "created_at": datetime.now(timezone.utc),
            "token_name": token_info.name,
            "initialized": False
        }
        logger.info(f"Created new MCP session: {session_id}")
    
    # Release the DB connection BEFORE streaming: FastAPI keeps dependencies
    # alive until the response completes, which for a long-lived SSE stream
    # means each open stream pins one pooled connection indefinitely.
    # Reconnecting clients (Kasal retries on any hiccup) exhaust the pool
    # within seconds — after which token validation can't query and every
    # request 401s or hangs on pool timeout. The stream loop only touches
    # the in-memory session dict, so the session is safe to close here.
    db.close()

    # Return SSE stream
    return EventSourceResponse(
        sse_stream_generator(token_info, session_id, request),
        headers={
            "MCP-Session-Id": session_id,
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


@router.post("")
async def mcp_handler(
    request: Request,
    audit_manager: AuditManagerDep,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    mcp_session_id: Optional[str] = Header(None, alias="MCP-Session-Id"),
    mcp_protocol_version: Optional[str] = Header(None, alias="MCP-Protocol-Version"),
):
    """
    MCP JSON-RPC 2.0 endpoint (POST).
    
    Requires X-API-Key header with a valid MCP token.
    Supports methods: initialize, notifications/initialized, ping, tools/list, tools/call
    
    Response format depends on Accept header:
    - Accept: text/event-stream -> SSE stream response
    - Accept: application/json (or default) -> JSON response
    """
    use_sse = wants_sse(request)
    session_id = mcp_session_id
    
    # Helper to create error response in the appropriate format
    async def error_response(code: int, message: str, request_id: Any = None):
        response_data = dump_jsonrpc_response(JSONRPCResponse(
            error=JSONRPCError(code=code, message=message),
            id=request_id
        ))
        
        if use_sse:
            return EventSourceResponse(
                sse_event_generator(response_data, session_id),
                headers={"MCP-Session-Id": session_id} if session_id else {}
            )
        return JSONResponse(content=response_data)
    
    # Parse request body first so every error response can carry the id
    try:
        body = await request.json()
    except Exception as e:
        return await error_response(JSONRPC_PARSE_ERROR, f"Failed to parse JSON: {str(e)}")
    
    # Validate JSON-RPC format
    try:
        rpc_request = JSONRPCRequest(**body)
    except Exception as e:
        return await error_response(JSONRPC_INVALID_REQUEST, f"Invalid request: {str(e)}",
                                    body.get("id") if isinstance(body, dict) else None)
    
    # JSON-RPC notifications (no id) MUST NOT receive a response body — the
    # MCP spec says unknown notifications are ignored and streamable HTTP
    # expects 202 Accepted. Replying with an error (id=null) crashes strict
    # clients (MCP Python SDK / Kasal). notifications/cancelled et al. land here.
    if rpc_request.id is None and rpc_request.method.startswith("notifications/"):
        if rpc_request.method == "notifications/initialized" and session_id in _sessions:
            _sessions[session_id]["initialized"] = True
        return Response(status_code=202,
                        headers={"MCP-Session-Id": session_id} if session_id else {})
    
    # Resolve caller: X-API-Key token, or the keyless default for app-gate
    # authenticated requests with a verified forwarded user token, when enabled.
    try:
        token_info = await resolve_mcp_principal(db, x_api_key, request, settings)
    except MCPIdentityError as e:
        _audit_identity_rejection(audit_manager, db, request, e.reason, "POST")
        return await error_response(MCP_AUTH_FAILED, IDENTITY_REJECTED_MESSAGE, rpc_request.id)
    if not token_info:
        audit_manager.log_action(
            db=db,
            username="anonymous",
            ip_address=_client_ip(request),
            feature=MCP_FEATURE_ID,
            action="AUTH_FAILURE",
            success=False,
            details={"reason": "Invalid or missing API key"},
        )
        return await error_response(MCP_AUTH_FAILED, "Invalid or missing API key",
                                    rpc_request.id)
    
    
    # Handle session management
    is_initialize = rpc_request.method == "initialize"
    
    if is_initialize:
        # Create new session on initialize
        session_id = generate_session_id()
        _sessions[session_id] = {
            "created_at": datetime.now(timezone.utc),
            "token_name": token_info.name,
            "initialized": False
        }
        logger.info(f"Created new MCP session on initialize: {session_id}")
    elif session_id:
        # Validate existing session
        if session_id not in _sessions:
            return await error_response(
                JSONRPC_INVALID_REQUEST,
                "Session not found",
                rpc_request.id
            )
    
    # Log the request
    logger.info(f"MCP request: method={rpc_request.method}, token={token_info.name}, sse={use_sse}")
    
    # Handle the request
    handler = MCPHandler(db, settings, token_info, request, audit_manager, session_id)
    response = await handler.handle(rpc_request)
    
    # Commit any changes
    try:
        db.commit()
    except Exception as e:
        logger.error(f"Error committing MCP changes: {e}")
        db.rollback()
    
    response_data = dump_jsonrpc_response(response)
    
    # Build response headers
    response_headers = {}
    if session_id:
        response_headers["MCP-Session-Id"] = session_id
    
    # Return in appropriate format
    if use_sse:
        return EventSourceResponse(
            sse_event_generator(response_data, session_id),
            headers=response_headers
        )
    
    return JSONResponse(content=response_data, headers=response_headers)


@router.delete("")
async def mcp_delete_session(
    request: Request,
    audit_manager: AuditManagerDep,
    db: Session = Depends(get_db),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    mcp_session_id: Optional[str] = Header(None, alias="MCP-Session-Id"),
):
    """
    Delete an MCP session.
    
    Clients should call this when they no longer need the session.
    """
    # Resolve caller: X-API-Key token, or the keyless default for app-gate
    # authenticated requests with a verified forwarded user token, when enabled.
    try:
        token_info = await resolve_mcp_principal(db, x_api_key, request)
    except MCPIdentityError as e:
        _audit_identity_rejection(audit_manager, db, request, e.reason, "DELETE")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=IDENTITY_REJECTED_MESSAGE
        )
    if not token_info:
        audit_manager.log_action(
            db=db,
            username="anonymous",
            ip_address=_client_ip(request),
            feature=MCP_FEATURE_ID,
            action="AUTH_FAILURE",
            success=False,
            details={"reason": "Invalid or missing API key", "endpoint": "DELETE"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key"
        )
    
    if not mcp_session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MCP-Session-Id header required"
        )
    
    if mcp_session_id in _sessions:
        del _sessions[mcp_session_id]
        logger.info(f"Deleted MCP session: {mcp_session_id}")
        audit_manager.log_action(
            db=db,
            username=token_info.created_by or token_info.name,
            ip_address=_client_ip(request),
            feature=MCP_FEATURE_ID,
            action="SESSION_DELETE",
            success=True,
            details={"session_id": mcp_session_id, "token_name": token_info.name},
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Session not found"
    )


@router.get("/health")
async def mcp_health():
    """Health check endpoint for MCP server.

    Public liveness probe — no auth required by design (load balancers,
    uptime checks). Does NOT expose session counts or any operational
    detail. Use ``/api/mcp/sessions`` (token-gated) for diagnostics.
    """
    return {
        "status": "ok",
        "server": "ontos-mcp-server",
        "version": "1.0.0",
        "protocol_version": MCP_PROTOCOL_VERSION,
        "supported_protocol_versions": SUPPORTED_PROTOCOL_VERSIONS,
    }
