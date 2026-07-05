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
from src.common.dependencies import AuditManagerDep
from src.common.logging import get_logger
from src.controller.audit_manager import AuditManager
from src.controller.mcp_tokens_manager import MCPTokensManager, MCPTokenInfo
from src.models.mcp import JSONRPCRequest, JSONRPCError, JSONRPCResponse
from src.tools.base import ToolContext, ToolResult
from src.tools.registry import create_default_registry

logger = get_logger(__name__)

router = APIRouter(prefix="/api/mcp", tags=["MCP Server"])


def register_routes(app):
    """Register MCP routes with the FastAPI app."""
    app.include_router(router)


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
MCP_PROTOCOL_VERSION = "2024-11-05"

# Feature ID for audit logging
MCP_FEATURE_ID = "mcp"

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
    
    def _get_username(self) -> str:
        return self._token_info.created_by or self._token_info.name
    
    def _get_ip_address(self) -> Optional[str]:
        return self._request.client.host if self._request.client else None
    
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
        
        self._audit(
            action="SESSION_CREATE",
            success=True,
            details={
                "session_id": self._session_id,
                "token_name": self._token_info.name,
                "client_info": client_info,
            },
        )
        
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
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
        
        # Create tool context
        ctx = self._create_tool_context()
        
        # Execute the tool with audit logging
        success = False
        details_for_audit: Dict[str, Any] = {
            "tool_name": tool_name,
            "token_name": self._token_info.name,
            "session_id": self._session_id,
        }
        try:
            result = await tool.execute(ctx, **tool_args)
            is_error = not result.success
            details_for_audit["is_error"] = is_error
            success = not is_error
            
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
            logger.error(f"Error executing tool {tool_name}: {e}", exc_info=True)
            details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Tool execution failed: {str(e)}"
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
    
    def _create_tool_context(self) -> ToolContext:
        """Create a ToolContext for tool execution."""
        # Get managers from app.state if available
        app = self._request.app
        
        return ToolContext(
            db=self._db,
            settings=self._settings,
            workspace_client=getattr(app.state, "workspace_client", None),
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
    
    # Validate API key
    token_info = validate_api_key(db, x_api_key)
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
        response_data = JSONRPCResponse(
            error=JSONRPCError(code=code, message=message),
            id=request_id
        ).model_dump()
        
        if use_sse:
            return EventSourceResponse(
                sse_event_generator(response_data, session_id),
                headers={"MCP-Session-Id": session_id} if session_id else {}
            )
        return JSONResponse(content=response_data)
    
    # Validate API key
    token_info = validate_api_key(db, x_api_key)
    if not token_info:
        audit_manager.log_action(
            db=db,
            username="anonymous",
            ip_address=request.client.host if request.client else None,
            feature=MCP_FEATURE_ID,
            action="AUTH_FAILURE",
            success=False,
            details={"reason": "Invalid or missing API key"},
        )
        return await error_response(MCP_AUTH_FAILED, "Invalid or missing API key")
    
    # Parse request body
    try:
        body = await request.json()
    except Exception as e:
        return await error_response(JSONRPC_PARSE_ERROR, f"Failed to parse JSON: {str(e)}")
    
    # Validate JSON-RPC format
    try:
        rpc_request = JSONRPCRequest(**body)
    except Exception as e:
        return await error_response(JSONRPC_INVALID_REQUEST, f"Invalid request: {str(e)}")
    
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
    
    response_data = response.model_dump()
    
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
    # Validate API key
    token_info = validate_api_key(db, x_api_key)
    if not token_info:
        audit_manager.log_action(
            db=db,
            username="anonymous",
            ip_address=request.client.host if request.client else None,
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
            ip_address=request.client.host if request.client else None,
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
    }
