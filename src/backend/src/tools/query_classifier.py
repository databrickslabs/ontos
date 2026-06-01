"""
Query Classifier for Tool Filtering.

Classifies user queries to determine which tool categories are relevant,
reducing the number of tools sent to the LLM to stay within context limits.
"""

from typing import List, Set

from src.common.logging import get_logger

logger = get_logger(__name__)

# Category definitions with their trigger keywords
CATEGORY_KEYWORDS = {
    "unity_catalog": [
        "catalog", "catalogs", "schema", "schemas", "table", "tables",
        "view", "views", "database", "databases", "sql", "query", "column",
        "columns", "unity", "uc", "explore", "browse", "list catalog",
        "my catalogs", "own catalog", "owner"
    ],
    # Ontos-side governance handle for UC resources (tables, views,
    # models, dashboards, etc.). The system prompt teaches the LLM
    # that UC tables become Assets when they enter Ontos via a
    # Deliverable — these keywords ensure the classifier flags Asset
    # intent alongside the raw `unity_catalog` browse intent. No tool
    # currently registers `category = "assets"`, but the matched
    # category is wired into the per-request category list so future
    # asset tools and the integration test suite can rely on it.
    "assets": [
        "asset", "assets", "table", "tables", "view", "views",
        "unity catalog", "uc", "catalog", "schema", "delta table",
        "publish", "govern", "expose",
    ],
    "data_products": [
        "data product", "product", "products", "output port", "output table",
        "create product", "draft product", "publish",
        "find data", "search data", "discover data", "data about", "where is data",
        "help me find", "looking for data", "available data", "what data"
    ],
    "data_contracts": [
        "contract", "contracts", "data contract", "agreement", "sla",
        "service level", "quality check", "validation"
    ],
    "organization": [
        "domain", "domains", "team", "teams", "project", "projects",
        "organization", "org", "department", "group"
    ],
    "semantic": [
        "glossary", "term", "terms", "business term", "definition",
        "concept", "semantic", "sparql", "ontology", "meaning",
        "hierarchy", "relationship", "link"
    ],
    "tags": [
        "tag", "tags", "label", "labels", "assign tag", "tagging",
        "categorize", "classify"
    ],
    "costs": [
        "cost", "costs", "price", "pricing", "spend", "spending",
        "budget", "expense", "billing", "usage cost"
    ],
    "analytics": [
        "analyze", "analysis", "aggregate", "sum", "count", "average",
        "statistics", "metrics", "measure", "calculate"
    ],
    # Conceptual / "what is X" / "how does Y work" questions about the
    # platform itself (roles, lifecycles, the agreement workflow, the
    # ontology + knowledge graph model, delivery modes, MCP, etc.).
    # The matching tool — search_ontos_handbook — grounds the LLM in
    # the curated docs/handbook/ corpus.
    "handbook": [
        "what is", "what's", "what are", "how does", "how do",
        "how is", "how are", "explain", "definition", "define",
        "difference between", "vs", "versus", "lifecycle",
        "rbac", "role", "roles", "permission", "permissions",
        "workflow", "approval", "agreement", "ontology",
        "knowledge graph", "delivery mode", "mcp",
        "data steward", "data producer", "data consumer",
        "data owner", "business owner",
    ],
    # App-state / adoption questions. Surfaces ``get_app_state`` for
    # questions like "how many data products do we have?", "is this a
    # fresh install?", "what's our adoption?". Also always-on (see
    # ``ALWAYS_INCLUDED_CATEGORIES``) because the same snapshot drives
    # the system-prompt adoption-mode preamble.
    "app_state": [
        "how many", "how much", "adoption", "empty", "new install",
        "fresh install", "getting started", "onboarding",
        "total number", "count of", "current state", "anyone using",
    ],
}

# Categories that are always included for general discovery.
# `handbook` is always-on so the LLM can ground any vague question in
# the corpus — the cost of carrying one extra tool definition is low and
# the safety upside (fewer hallucinated platform concepts) is large.
# `app_state` is always-on for the same reason: it's a single
# parameter-less tool whose result is cheap and is sometimes the right
# answer to a vague "how are we doing?" question.
ALWAYS_INCLUDED_CATEGORIES = ["discovery", "handbook", "app_state"]

# Default categories when no specific match is found
DEFAULT_CATEGORIES = ["discovery", "handbook", "app_state", "data_products", "data_contracts", "semantic"]


def classify_query(query: str) -> List[str]:
    """
    Classify a user query to determine relevant tool categories.
    
    Args:
        query: The user's message/query
        
    Returns:
        List of relevant category names
    """
    if not query:
        return DEFAULT_CATEGORIES.copy()
    
    query_lower = query.lower()
    matched_categories: Set[str] = set(ALWAYS_INCLUDED_CATEGORIES)
    
    # Check each category's keywords
    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in query_lower:
                matched_categories.add(category)
                break  # Found a match for this category, move to next
    
    # If only discovery matched (no specific category), add defaults
    if matched_categories == set(ALWAYS_INCLUDED_CATEGORIES):
        matched_categories.update(DEFAULT_CATEGORIES)
    
    result = list(matched_categories)
    logger.info(f"Query classification: '{query[:50]}...' -> categories: {result}")
    return result


def get_all_categories() -> List[str]:
    """
    Get all available tool categories.
    
    Returns:
        List of all category names
    """
    return ALWAYS_INCLUDED_CATEGORIES + list(CATEGORY_KEYWORDS.keys())

