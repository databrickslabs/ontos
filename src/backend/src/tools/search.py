"""
Search tools for LLM.

Tools for global search across all indexed features.
"""

from typing import Any, Dict, List, Optional

from src.common.logging import get_logger
from src.controller import search_scoring
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = get_logger(__name__)


class GlobalSearchTool(BaseTool):
    """Search across all indexed features (data products, contracts, glossary, etc.)."""

    name = "global_search"
    category = "discovery"
    description = (
        "Search across all indexed features (data products, data contracts, glossary terms, "
        "domains, tags, and more), ranked by relevance. Use FEW BROAD terms, not full "
        "sentences — each term is matched independently, so 'customer churn' finds items "
        "matching either word. Prefer narrowing with the 'type' filter and paginating with "
        "'offset' over broadening the query. Leave 'query' empty (or '*') to list everything; "
        "the response is always paginated and includes 'total_count' and 'facets' (available "
        "types/domains/statuses/tags) so you can refine instead of fetching all results."
    )
    parameters = {
        "query": {
            "type": "string",
            "description": "Search terms (e.g., 'customer analytics', 'PII', 'sales'). Empty or '*' lists all items."
        },
        "type": {
            "type": "string",
            "description": "Optional filter by item type (e.g., 'data-product', 'data-contract', 'glossary-term', 'data-domain', 'tag')."
        },
        "limit": {
            "type": "integer",
            "description": "Max results to return (default: 25, max: 100)."
        },
        "offset": {
            "type": "integer",
            "description": "Number of results to skip for pagination (default: 0). Use with 'total_count'/'has_more' to page."
        }
    }
    required_params = ["query"]
    required_scope = "search:read"

    async def execute(
        self,
        ctx: ToolContext,
        query: str = "",
        type: Optional[str] = None,
        limit: int = 25,
        offset: int = 0,
    ) -> ToolResult:
        """Execute global search over the in-memory search index."""
        logger.info(f"[global_search] Starting - query='{query}', type={type}, limit={limit}, offset={offset}")

        if not ctx.search_manager:
            logger.warning("[global_search] FAILED: search_manager is None")
            return ToolResult(success=False, error="Search not available", data={"results": []})

        try:
            # MCP has its own scope-based access control via tokens, so no per-user
            # permission filtering here — we search the shared index directly.
            data = search_scoring.search_index(
                ctx.search_manager.index,
                query,
                ctx.search_manager.config,
                type_filter=type,
                limit=limit,
                offset=offset,
            )
            logger.info(
                f"[global_search] SUCCESS: returned {data['returned']} of {data['total_count']} matches"
            )
            return ToolResult(success=True, data=data)

        except Exception as e:
            # NOTE: the 'type' parameter shadows the builtin, so use e.__class__.
            logger.error(f"[global_search] FAILED: {e.__class__.__name__}: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error=f"{e.__class__.__name__}: {str(e)}",
                data={"results": []},
            )

