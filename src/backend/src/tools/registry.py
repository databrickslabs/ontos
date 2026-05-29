"""
Tool Registry for LLM tools.

Provides centralized registration, discovery, and execution of tools
for both LLM Search and MCP server endpoints.
"""

from typing import Any, Dict, List, Optional, Type

from src.common.logging import get_logger
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = get_logger(__name__)


class ToolRegistry:
    """
    Central registry for discovering and invoking tools.
    
    Provides:
    - Tool registration and lookup by name
    - Tool listing in various formats (OpenAI, MCP)
    - Unified tool execution with context injection
    
    Usage:
        registry = ToolRegistry()
        registry.register(SearchDataProductsTool())
        registry.register(GetTableSchemaTool())
        
        # Get tool definitions for OpenAI
        openai_tools = registry.get_openai_definitions()
        
        # Execute a tool
        result = await registry.execute("search_data_products", ctx, query="sales")
    """
    
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
    
    def register(self, tool: BaseTool) -> None:
        """
        Register a tool instance.
        
        Args:
            tool: Tool instance to register
            
        Raises:
            ValueError: If a tool with the same name is already registered
        """
        if tool.name in self._tools:
            logger.warning(f"Tool '{tool.name}' is already registered, overwriting")
        
        self._tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name}")
    
    def register_all(self, tools: List[BaseTool]) -> None:
        """
        Register multiple tools at once.
        
        Args:
            tools: List of tool instances to register
        """
        for tool in tools:
            self.register(tool)
    
    def get(self, name: str) -> Optional[BaseTool]:
        """
        Get a tool by name.
        
        Args:
            name: Tool name
            
        Returns:
            Tool instance or None if not found
        """
        return self._tools.get(name)
    
    def list_tools(self) -> List[BaseTool]:
        """
        Get all registered tools.
        
        Returns:
            List of all registered tool instances
        """
        return list(self._tools.values())
    
    def list_tool_names(self) -> List[str]:
        """
        Get names of all registered tools.
        
        Returns:
            List of tool names
        """
        return list(self._tools.keys())
    
    def get_openai_definitions(self) -> List[Dict[str, Any]]:
        """
        Get all tool definitions in OpenAI function calling format.
        
        Returns:
            List of tool definitions suitable for OpenAI API
        """
        return [tool.to_openai_format() for tool in self._tools.values()]
    
    def get_openai_definitions_filtered(self, categories: List[str]) -> List[Dict[str, Any]]:
        """
        Get tool definitions filtered by categories in OpenAI format.
        
        Args:
            categories: List of category names to include
            
        Returns:
            List of tool definitions for tools matching the categories
        """
        filtered = [
            tool.to_openai_format() 
            for tool in self._tools.values() 
            if tool.category in categories
        ]
        logger.debug(f"Filtered tools: {len(filtered)} of {len(self._tools)} (categories: {categories})")
        return filtered
    
    def get_mcp_definitions(self) -> List[Dict[str, Any]]:
        """
        Get all tool definitions in MCP format.
        
        Returns:
            List of tool definitions suitable for MCP server
        """
        return [tool.to_mcp_format() for tool in self._tools.values()]
    
    async def execute(
        self,
        name: str,
        ctx: ToolContext,
        args: Optional[Dict[str, Any]] = None
    ) -> ToolResult:
        """
        Execute a tool by name with the given context and arguments.
        
        Args:
            name: Tool name
            ctx: ToolContext with database session and managers
            args: Tool arguments (will be passed as **kwargs)
            
        Returns:
            ToolResult with success/failure status and data
            
        Raises:
            ValueError: If tool is not found
        """
        tool = self.get(name)
        if not tool:
            logger.error(f"Tool not found: {name}")
            return ToolResult(
                success=False,
                error=f"Unknown tool: {name}"
            )
        
        try:
            logger.info(f"Executing tool: {name} with args: {args}")
            result = await tool.execute(ctx, **(args or {}))
            
            if result.success:
                logger.debug(f"Tool {name} succeeded")
            else:
                logger.warning(f"Tool {name} returned error: {result.error}")
            
            return result
            
        except Exception as e:
            logger.error(f"Tool {name} raised exception: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error=f"{type(e).__name__}: {str(e)}"
            )
    
    def __len__(self) -> int:
        return len(self._tools)
    
    def __contains__(self, name: str) -> bool:
        return name in self._tools


def create_default_registry() -> ToolRegistry:
    """
    Create a registry with all default tools registered.
    
    Returns:
        ToolRegistry with all standard tools
    """
    from src.tools.data_products import (
        SearchDataProductsTool,
        GetDataProductTool,
        CreateDraftDataProductTool,
        UpdateDataProductTool,
        DeleteDataProductTool
    )
    from src.tools.data_contracts import (
        SearchDataContractsTool,
        GetDataContractTool,
        CreateDraftDataContractTool,
        UpdateDataContractTool,
        DeleteDataContractTool
    )
    from src.tools.semantic_models import (
        SearchGlossaryTermsTool,
        AddSemanticLinkTool,
        ListSemanticLinksTool,
        RemoveSemanticLinkTool,
        FindEntitiesByConceptTool,
        ExecuteSparqlQueryTool,
        GetConceptHierarchyTool,
        GetConceptNeighborsTool
    )
    from src.tools.search import GlobalSearchTool
    from src.tools.concepts import SearchOntosConceptsTool
    from src.tools.analytics import (
        GetTableSchemaTool,
        ExecuteAnalyticsQueryTool,
        ExploreCatalogSchemaTool
    )
    from src.tools.costs import GetDataProductCostsTool
    from src.tools.domains import (
        SearchDomainsTool,
        GetDomainTool,
        CreateDomainTool,
        UpdateDomainTool,
        DeleteDomainTool
    )
    from src.tools.teams import (
        SearchTeamsTool,
        GetTeamTool,
        CreateTeamTool,
        UpdateTeamTool,
        DeleteTeamTool
    )
    from src.tools.projects import (
        SearchProjectsTool,
        GetProjectTool,
        CreateProjectTool,
        UpdateProjectTool,
        DeleteProjectTool
    )
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
    from src.tools.unity_catalog import (
        GetCurrentUserTool,
        ListCatalogsTool,
        GetCatalogDetailsTool,
        ListSchemasTool
    )
    
    registry = ToolRegistry()
    
    # Data Products tools (full CRUD)
    registry.register(SearchDataProductsTool())
    registry.register(GetDataProductTool())
    registry.register(CreateDraftDataProductTool())
    registry.register(UpdateDataProductTool())
    registry.register(DeleteDataProductTool())
    
    # Data Contracts tools (full CRUD)
    registry.register(SearchDataContractsTool())
    registry.register(GetDataContractTool())
    registry.register(CreateDraftDataContractTool())
    registry.register(UpdateDataContractTool())
    registry.register(DeleteDataContractTool())
    
    # Domains tools (full CRUD)
    registry.register(SearchDomainsTool())
    registry.register(GetDomainTool())
    registry.register(CreateDomainTool())
    registry.register(UpdateDomainTool())
    registry.register(DeleteDomainTool())
    
    # Teams tools (full CRUD)
    registry.register(SearchTeamsTool())
    registry.register(GetTeamTool())
    registry.register(CreateTeamTool())
    registry.register(UpdateTeamTool())
    registry.register(DeleteTeamTool())
    
    # Projects tools (full CRUD)
    registry.register(SearchProjectsTool())
    registry.register(GetProjectTool())
    registry.register(CreateProjectTool())
    registry.register(UpdateProjectTool())
    registry.register(DeleteProjectTool())
    
    # Semantic Models tools
    registry.register(SearchGlossaryTermsTool())
    registry.register(AddSemanticLinkTool())
    registry.register(ListSemanticLinksTool())
    registry.register(RemoveSemanticLinkTool())
    registry.register(FindEntitiesByConceptTool())
    registry.register(ExecuteSparqlQueryTool())
    registry.register(GetConceptHierarchyTool())
    registry.register(GetConceptNeighborsTool())
    
    # Search tools
    registry.register(GlobalSearchTool())

    # Concept-doc search — grounds the LLM in docs/concepts/ for any
    # "what is X" / "how does Y work" question. New `concepts` category;
    # see query_classifier.CATEGORY_KEYWORDS["concepts"] and
    # ALWAYS_INCLUDED_CATEGORIES.
    registry.register(SearchOntosConceptsTool())
    
    # Analytics tools
    registry.register(GetTableSchemaTool())
    registry.register(ExecuteAnalyticsQueryTool())
    registry.register(ExploreCatalogSchemaTool())
    
    # Costs tools
    registry.register(GetDataProductCostsTool())
    
    # Tags tools (CRUD + entity assignment)
    registry.register(SearchTagsTool())
    registry.register(GetTagTool())
    registry.register(CreateTagTool())
    registry.register(UpdateTagTool())
    registry.register(DeleteTagTool())
    registry.register(ListEntityTagsTool())
    registry.register(AssignTagToEntityTool())
    registry.register(RemoveTagFromEntityTool())
    
    # Unity Catalog browsing tools
    registry.register(GetCurrentUserTool())
    registry.register(ListCatalogsTool())
    registry.register(GetCatalogDetailsTool())
    registry.register(ListSchemasTool())
    
    logger.info(f"Created default registry with {len(registry)} tools")
    return registry

