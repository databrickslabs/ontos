"""
Search tools for LLM.

Tools for global search across all indexed features.
"""

from typing import Any, Dict, List, Optional

from src.common.logging import get_logger
from src.tools import read_access
from src.tools import visibility as vis
from src.tools.base import BaseTool, ToolContext, ToolResult, tool_failure

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
        "types/domains/statuses/tags) so you can refine instead of fetching all results. "
        "For data products and contracts: " + vis.VISIBILITY_DESCRIPTION
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
        },
        "visibility": vis.VISIBILITY_PARAM,
        "min_certification_level": vis.MIN_CERTIFICATION_PARAM,
        "include_history": vis.INCLUDE_HISTORY_PARAM,
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
        visibility: Optional[str] = None,
        min_certification_level: Optional[int] = None,
        include_history: bool = False,
    ) -> ToolResult:
        """Execute global search over the in-memory search index."""
        logger.info(f"[global_search] Starting - query='{query}', type={type}, limit={limit}, offset={offset}")

        if not ctx.search_manager:
            logger.warning("[global_search] FAILED: search_manager is None")
            return ToolResult(success=False, error="Search not available", data={"results": []})

        applied = vis.applied_visibility(ctx, visibility)
        if applied is None:
            return vis.invalid_visibility(visibility, results=[])

        try:
            # Products and contracts the caller can't read, or outside the
            # visibility, are dropped before pagination and facets.
            data = ctx.search_manager.query_index(
                query,
                type_filter=type,
                limit=limit,
                offset=offset,
                allowed_ids_by_type=vis.allowed_ids_by_type(
                    ctx, type, visibility=applied,
                    min_certification_level=min_certification_level,
                    include_history=include_history, query=query,
                ),
                # Rows of features without the caller's Read-only level are
                # dropped too, as /api/search does by feature_id.
                allowed_features=read_access.allowed_features(ctx),
            )
            vis.annotate(ctx, data["results"])
            data["visibility"] = applied
            logger.info(
                f"[global_search] SUCCESS: returned {data['returned']} of {data['total_count']} matches"
            )
            return ToolResult(success=True, data=data)

        except Exception as e:
            # NOTE: the 'type' parameter shadows the builtin, so use e.__class__.
            return ToolResult(
                success=False,
                **tool_failure("global_search", e),
                data={"results": []},
            )

