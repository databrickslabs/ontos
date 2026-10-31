"""
Base classes for LLM tools.

Provides the foundation for reusable tools that can be invoked by both
the LLM Search feature and MCP server endpoints.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.common.api_errors import CodedValueError, new_error_id
from src.common.config import Settings
from src.common.features import ACCESS_LEVEL_ORDER, FeatureAccessLevel
from src.common.logging import get_logger

logger = get_logger(__name__)


# Client-facing failure for an unexpected exception in a tool. The exception's
# class and text (SQL, parameters, paths, hosts) go to the server log only: a
# tool result reaches the MCP client and the chat LLM, which may quote it. The
# message carries an error id, in the same shape as the API's server errors
# (``src.common.api_errors``), so a user can quote it and the log entry is found.
TOOL_FAILED_CODE = "tool_failed"
TOOL_FAILED_MESSAGE = "The tool failed with an unexpected error (error id {error_id})."


def tool_failed_message(error_id: str) -> str:
    return TOOL_FAILED_MESSAGE.format(error_id=error_id)


def tool_failure(tag: str, exc: BaseException) -> Dict[str, str]:
    """Log an unexpected tool failure with an error id and return the client-facing part.

    Spread into ``ToolResult(success=False, **tool_failure("get_domain", e), ...)``.
    """
    if isinstance(exc, CodedValueError):
        # An expected refusal (invalid transition, blocked by a workflow...):
        # its message is written for the user, so the client gets it with the code.
        logger.info("[%s] refused: %s: %s", tag, type(exc).__name__, exc)
        return {"error": f"{type(exc).__name__}: {exc}", "error_code": exc.code or TOOL_FAILED_CODE}
    error_id = new_error_id()
    logger.error(
        "[%s] FAILED (error id %s): %s: %s", tag, error_id, type(exc).__name__, exc, exc_info=exc
    )
    return {"error": tool_failed_message(error_id), "error_code": TOOL_FAILED_CODE}


@dataclass
class ToolContext:
    """
    Dependency container for tool execution.
    
    Provides access to database session, settings, and various managers
    needed by tools without coupling them to specific implementations.
    ``caller`` is the identity the tools act for; without one, tools that
    declare a ``required_permission`` are refused.
    """
    db: Session
    settings: Settings
    workspace_client: Optional[Any] = None
    caller: Optional["ToolCaller"] = None
    # Per-request memo for the read rules (src.tools.read_access).
    cache: Dict[str, Any] = field(default_factory=dict)
    # The search and list tools' default ``visibility`` (src.tools.visibility):
    # "published" for MCP, "readable" for Ask Ontos.
    default_visibility: str = "published"
    data_products_manager: Optional[Any] = None
    data_contracts_manager: Optional[Any] = None
    semantic_models_manager: Optional[Any] = None
    costs_manager: Optional[Any] = None
    search_manager: Optional[Any] = None


@dataclass
class ToolResult:
    """
    Standardized result from tool execution.
    
    Attributes:
        success: Whether the tool executed successfully
        data: The result data (dict, list, etc.)
        error: Error message if success is False
        error_code: Optional stable machine-readable code for the failure
            (e.g. ``tool_failed``). Additive: clients that only read ``error``
            keep working.
    """
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    error_code: Optional[str] = None
    # Why the caller got less than the tool would return to an admin (e.g.
    # ``not_readable``). For audit entries only: never sent to the client,
    # where an unreadable item looks like a missing one.
    denied_reason: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        if self.success:
            return self.data
        else:
            out: Dict[str, Any] = {"error": self.error, **self.data}
            if self.error_code:
                out["error_code"] = self.error_code
            return out


# A tool the caller may not run: its feature level is below the level the
# matching REST route requires (or the caller is unknown).
TOOL_NOT_PERMITTED_CODE = "tool_not_permitted"


@dataclass
class ToolCaller:
    """Who runs a tool, resolved once per request.

    ``permissions`` are the caller's effective feature levels, resolved the
    same way as ``PermissionChecker`` (role override, team role, groups).
    ``auth_path`` says where the identity came from (``ask_ontos``,
    ``mcp_forwarded_token``, ...) for logs and audit entries.
    ``products_admin`` / ``contracts_admin`` / ``team_ids`` are the inputs of
    the product and contract read rules (``src.tools.read_access``).
    ``full_access`` skips the feature checks and the read rules; no caller
    sets it today (see ``src.tools.caller.mcp_api_key_caller``).
    """
    email: Optional[str]
    auth_path: str
    groups: List[str] = field(default_factory=list)
    permissions: Dict[str, FeatureAccessLevel] = field(default_factory=dict)
    full_access: bool = False
    products_admin: bool = False
    contracts_admin: bool = False
    team_ids: set[str] = field(default_factory=set)
    # Projects the caller is a member of; None = every project (admin groups).
    project_ids: Optional[set[str]] = field(default_factory=set)

    def has_level(self, feature_id: str, required_level: FeatureAccessLevel) -> bool:
        if self.full_access:
            return True
        level = self.permissions.get(feature_id, FeatureAccessLevel.NONE)
        return ACCESS_LEVEL_ORDER[level] >= ACCESS_LEVEL_ORDER[required_level]


def permission_refusal(
    ctx: ToolContext,
    feature_id: str,
    required_level: FeatureAccessLevel,
    tool_name: str,
) -> Optional[ToolResult]:
    """Return a coded refusal when the caller lacks ``required_level`` on ``feature_id``.

    ``None`` means the tool may run. The non-``Depends`` counterpart of
    ``PermissionChecker`` for tools; the levels are resolved in ``ctx.caller``.
    """
    caller = ctx.caller
    if caller is not None and caller.has_level(feature_id, required_level):
        return None
    logger.warning(
        "[%s] refused: needs %s on %s; caller=%s auth_path=%s",
        tool_name,
        required_level.value,
        feature_id,
        caller.email if caller else None,
        caller.auth_path if caller else None,
    )
    return ToolResult(
        success=False,
        error=(
            f"Not allowed: this tool needs the '{required_level.value}' level "
            f"on '{feature_id}'."
        ),
        error_code=TOOL_NOT_PERMITTED_CODE,
        data={"feature_id": feature_id, "required_level": required_level.value},
    )


def check_tool_permission(tool: "BaseTool", ctx: ToolContext) -> Optional[ToolResult]:
    """Apply a tool's declared ``required_permission``; ``None`` means it may run.

    Called by every runner (``ToolRegistry.execute`` and the MCP handler)
    before ``execute``.
    """
    required = getattr(tool, "required_permission", None)
    if not required:
        return None
    feature_id, required_level = required
    return permission_refusal(ctx, feature_id, required_level, tool.name)


class BaseTool(ABC):
    """
    Abstract base class for all LLM tools.
    
    Each tool is a class with:
    - name: Unique identifier for the tool
    - description: Human-readable description
    - parameters: JSON Schema for input parameters
    - required_params: List of required parameter names
    - required_scope: MCP scope required to use this tool (e.g., 'data-products:read')
    - category: Tool category for query-based filtering
    - execute(): Async method that performs the tool's action
    
    Tools can be converted to OpenAI or MCP format for use with
    different LLM orchestration systems.
    """
    
    # Class attributes to be defined by subclasses
    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = {}
    required_params: List[str] = []
    required_scope: str = "*"  # Default: admin-only, subclasses should override
    category: str = "general"  # Tool category for query-based filtering
    # (feature_id, level) the caller needs, the same as the matching REST
    # route's PermissionChecker. Every tool that changes data declares one.
    required_permission: Optional[tuple[str, FeatureAccessLevel]] = None
    
    @abstractmethod
    async def execute(self, ctx: ToolContext, **kwargs) -> ToolResult:
        """
        Execute the tool with the given context and arguments.
        
        Args:
            ctx: ToolContext with database session and managers
            **kwargs: Tool-specific arguments matching the parameters schema
            
        Returns:
            ToolResult with success/failure status and data
        """
        pass
    
    def to_openai_format(self) -> Dict[str, Any]:
        """
        Convert tool definition to OpenAI function calling format.
        
        Returns:
            Dict in OpenAI tool format with type="function"
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": self.required_params
                }
            }
        }
    
    def to_mcp_format(self) -> Dict[str, Any]:
        """
        Convert tool definition to MCP (Model Context Protocol) format.
        
        Returns:
            Dict in MCP tool format with inputSchema
        """
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": self.parameters,
                "required": self.required_params
            }
        }
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name={self.name})>"

