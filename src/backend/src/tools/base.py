"""
Base classes for LLM tools.

Provides the foundation for reusable tools that can be invoked by both
the LLM Search feature and MCP server endpoints.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from src.common.config import Settings
from src.common.logging import get_logger

logger = get_logger(__name__)


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
    # Lazily builds a WorkspaceClient scoped to the calling user (OBO); None when
    # the request carried no forwarded user token.
    obo_workspace_client_factory: Optional[Callable[[], Any]] = None


@dataclass
class ToolResult:
    """
    Standardized result from tool execution.
    
    Attributes:
        success: Whether the tool executed successfully
        data: The result data (dict, list, etc.)
        error: Error message if success is False
    """
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        if self.success:
            return self.data
        else:
            return {"error": self.error, **self.data}


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

