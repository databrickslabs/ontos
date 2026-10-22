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


INVALID_TRANSITION_CODE = "invalid_status_transition"


def invalid_transition(current: str, new: str, allowed: List[str]) -> Dict[str, str]:
    """The client-facing part of a status change the lifecycle doesn't allow.

    Checked by the update tools before the manager, whose ValueError would only
    reach the client as the generic failure. Spread like ``tool_failure``.
    """
    return {
        "error": (
            f"Invalid status transition from '{current}' to '{new}'. "
            f"Allowed transitions: {', '.join(allowed) if allowed else 'none'}"
        ),
        "error_code": INVALID_TRANSITION_CODE,
    }


@dataclass
class ToolContext:
    """
    Dependency container for tool execution.
    
    Provides access to database session, settings, and various managers
    needed by tools without coupling them to specific implementations.
    """
    db: Session
    settings: Settings
    workspace_client: Optional[Any] = None
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
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        if self.success:
            return self.data
        else:
            out: Dict[str, Any] = {"error": self.error, **self.data}
            if self.error_code:
                out["error_code"] = self.error_code
            return out


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

