"""
LLM Tools Submodule

Provides reusable tools for LLM search and MCP server endpoints.

This module contains:
- BaseTool: Abstract base class for all tools
- ToolContext: Dependency container for tool execution
- ToolResult: Standardized result from tool execution
- ToolRegistry: Central registry for discovering and invoking tools
- Individual tool implementations organized by category

Usage:
    from src.tools import ToolRegistry, ToolContext, create_default_registry
    
    # Create registry with all default tools
    registry = create_default_registry()
    
    # Create context with dependencies
    ctx = ToolContext(
        db=session,
        settings=settings,
        workspace_client=ws_client,
        data_products_manager=data_products_manager,
        ...
    )
    
    # Execute a tool
    result = await registry.execute("search_data_products", ctx, {"query": "sales"})
    
    # Get tool definitions for OpenAI
    openai_tools = registry.get_openai_definitions()
    
    # Get tool definitions for MCP
    mcp_tools = registry.get_mcp_definitions()
"""

# Base classes
from src.tools.base import BaseTool, ToolContext, ToolResult

# Registry
from src.tools.registry import ToolRegistry, create_default_registry

# Data Products tools
from src.tools.data_products import (
    SearchDataProductsTool,
    GetDataProductTool,
    ListDataProductsTool,
    CreateDraftDataProductTool,
    UpdateDataProductTool,
    DeleteDataProductTool
)

# Data Contracts tools
from src.tools.data_contracts import (
    SearchDataContractsTool,
    GetDataContractTool,
    ListDataContractsTool,
    CreateDraftDataContractTool,
    UpdateDataContractTool,
    DeleteDataContractTool
)

# Domains tools
from src.tools.domains import (
    SearchDomainsTool,
    GetDomainTool,
    CreateDomainTool,
    UpdateDomainTool,
    DeleteDomainTool
)

# Teams tools
from src.tools.teams import (
    SearchTeamsTool,
    GetTeamTool,
    CreateTeamTool,
    UpdateTeamTool,
    DeleteTeamTool
)

# Projects tools
from src.tools.projects import (
    SearchProjectsTool,
    GetProjectTool,
    CreateProjectTool,
    UpdateProjectTool,
    DeleteProjectTool
)

# Semantic Models tools
from src.tools.semantic_models import (
    SearchGlossaryTermsTool,
    AddSemanticLinkTool,
    ListSemanticLinksTool,
    RemoveSemanticLinkTool
)

# Analytics tools
from src.tools.analytics import (
    GetTableSchemaTool,
    ExecuteAnalyticsQueryTool,
    ExploreCatalogSchemaTool
)

# Costs tools
from src.tools.costs import GetDataProductCostsTool

# Tags tools
from src.tools.tags import (
    SearchTagsTool,
    GetTagTool,
    CreateTagTool,
    UpdateTagTool,
    DeleteTagTool,
    ListEntityTagsTool,
    AssignTagToEntityTool,
    RemoveTagFromEntityTool
)

__all__ = [
    # Base classes
    "BaseTool",
    "ToolContext",
    "ToolResult",
    
    # Registry
    "ToolRegistry",
    "create_default_registry",
    
    # Data Products tools (full CRUD)
    "SearchDataProductsTool",
    "GetDataProductTool",
    "ListDataProductsTool",
    "CreateDraftDataProductTool",
    "UpdateDataProductTool",
    "DeleteDataProductTool",

    # Data Contracts tools (full CRUD)
    "SearchDataContractsTool",
    "GetDataContractTool",
    "ListDataContractsTool",
    "CreateDraftDataContractTool",
    "UpdateDataContractTool",
    "DeleteDataContractTool",
    
    # Domains tools (full CRUD)
    "SearchDomainsTool",
    "GetDomainTool",
    "CreateDomainTool",
    "UpdateDomainTool",
    "DeleteDomainTool",
    
    # Teams tools (full CRUD)
    "SearchTeamsTool",
    "GetTeamTool",
    "CreateTeamTool",
    "UpdateTeamTool",
    "DeleteTeamTool",
    
    # Projects tools (full CRUD)
    "SearchProjectsTool",
    "GetProjectTool",
    "CreateProjectTool",
    "UpdateProjectTool",
    "DeleteProjectTool",
    
    # Semantic Models tools
    "SearchGlossaryTermsTool",
    "AddSemanticLinkTool",
    "ListSemanticLinksTool",
    "RemoveSemanticLinkTool",
    
    # Analytics tools
    "GetTableSchemaTool",
    "ExecuteAnalyticsQueryTool",
    "ExploreCatalogSchemaTool",
    
    # Costs tools
    "GetDataProductCostsTool",
    
    # Tags tools
    "SearchTagsTool",
    "GetTagTool",
    "CreateTagTool",
    "UpdateTagTool",
    "DeleteTagTool",
    "ListEntityTagsTool",
    "AssignTagToEntityTool",
    "RemoveTagFromEntityTool",
]
