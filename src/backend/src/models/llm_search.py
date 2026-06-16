"""
LLM Search Models

Pydantic models for the conversational LLM search feature.
Supports chat messages, sessions, tool calls, and responses.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field
import uuid


# ============================================================================
# Enums
# ============================================================================

class MessageRole(str, Enum):
    """Role of a message in the conversation."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ToolName(str, Enum):
    """Available tools for the LLM to call."""
    # Data Products (full CRUD)
    SEARCH_DATA_PRODUCTS = "search_data_products"
    GET_DATA_PRODUCT = "get_data_product"
    CREATE_DRAFT_DATA_PRODUCT = "create_draft_data_product"
    UPDATE_DATA_PRODUCT = "update_data_product"
    DELETE_DATA_PRODUCT = "delete_data_product"
    
    # Data Contracts (full CRUD)
    SEARCH_DATA_CONTRACTS = "search_data_contracts"
    GET_DATA_CONTRACT = "get_data_contract"
    CREATE_DRAFT_DATA_CONTRACT = "create_draft_data_contract"
    UPDATE_DATA_CONTRACT = "update_data_contract"
    DELETE_DATA_CONTRACT = "delete_data_contract"
    
    # Domains (full CRUD)
    SEARCH_DOMAINS = "search_domains"
    GET_DOMAIN = "get_domain"
    CREATE_DOMAIN = "create_domain"
    UPDATE_DOMAIN = "update_domain"
    DELETE_DOMAIN = "delete_domain"
    
    # Teams (full CRUD)
    SEARCH_TEAMS = "search_teams"
    GET_TEAM = "get_team"
    CREATE_TEAM = "create_team"
    UPDATE_TEAM = "update_team"
    DELETE_TEAM = "delete_team"
    
    # Projects (full CRUD)
    SEARCH_PROJECTS = "search_projects"
    GET_PROJECT = "get_project"
    CREATE_PROJECT = "create_project"
    UPDATE_PROJECT = "update_project"
    DELETE_PROJECT = "delete_project"
    
    # Discovery
    SEARCH_GLOSSARY_TERMS = "search_glossary_terms"
    EXPLORE_CATALOG_SCHEMA = "explore_catalog_schema"
    
    # Schema & Query
    GET_TABLE_SCHEMA = "get_table_schema"
    EXECUTE_ANALYTICS_QUERY = "execute_analytics_query"
    
    # Cost Analysis
    GET_DATA_PRODUCT_COSTS = "get_data_product_costs"
    
    # Semantic Linking
    ADD_SEMANTIC_LINK = "add_semantic_link"
    LIST_SEMANTIC_LINKS = "list_semantic_links"
    REMOVE_SEMANTIC_LINK = "remove_semantic_link"
    
    # Tags (CRUD + entity assignment)
    SEARCH_TAGS = "search_tags"
    GET_TAG = "get_tag"
    CREATE_TAG = "create_tag"
    UPDATE_TAG = "update_tag"
    DELETE_TAG = "delete_tag"
    LIST_ENTITY_TAGS = "list_entity_tags"
    ASSIGN_TAG_TO_ENTITY = "assign_tag_to_entity"
    REMOVE_TAG_FROM_ENTITY = "remove_tag_from_entity"
    
    # Unity Catalog browsing
    GET_CURRENT_USER = "get_current_user"
    LIST_CATALOGS = "list_catalogs"
    GET_CATALOG_DETAILS = "get_catalog_details"
    LIST_SCHEMAS = "list_schemas"
    
    # Semantic model graph operations
    FIND_ENTITIES_BY_CONCEPT = "find_entities_by_concept"
    EXECUTE_SPARQL_QUERY = "execute_sparql_query"
    GET_CONCEPT_HIERARCHY = "get_concept_hierarchy"
    GET_CONCEPT_NEIGHBORS = "get_concept_neighbors"
    
    # Global search
    GLOBAL_SEARCH = "global_search"

    # Handbook search (grounds the copilot in docs/handbook/)
    SEARCH_ONTOS_HANDBOOK = "search_ontos_handbook"


# ============================================================================
# Tool Parameter Models
# ============================================================================

class SearchDataProductsParams(BaseModel):
    """Parameters for search_data_products tool."""
    query: str = Field(..., description="Search query for data products")
    domain: Optional[str] = Field(None, description="Filter by domain (e.g., 'Customer', 'Sales')")
    status: Optional[str] = Field(None, description="Filter by status (active, draft, deprecated)")


class SearchGlossaryTermsParams(BaseModel):
    """Parameters for search_glossary_terms tool."""
    term: str = Field(..., description="Business term to search for")
    domain: Optional[str] = Field(None, description="Filter by domain")


class GetDataProductCostsParams(BaseModel):
    """Parameters for get_data_product_costs tool."""
    product_id: Optional[str] = Field(None, description="Specific product ID, or null for all")
    aggregate: bool = Field(False, description="If true, return totals; if false, return per-product breakdown")


class GetTableSchemaParams(BaseModel):
    """Parameters for get_table_schema tool."""
    table_fqn: str = Field(..., description="Fully qualified table name (catalog.schema.table)")


class ExecuteAnalyticsQueryParams(BaseModel):
    """Parameters for execute_analytics_query tool."""
    sql: str = Field(..., description="The SQL SELECT query to execute")
    explanation: str = Field(..., description="Why this query answers the user's question")


# ============================================================================
# Tool Call Models
# ============================================================================

class ToolCall(BaseModel):
    """A tool call requested by the LLM."""
    id: str = Field(..., description="Unique identifier for this tool call")
    name: ToolName = Field(..., description="Name of the tool to call")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Arguments for the tool")


class ToolResult(BaseModel):
    """Result from executing a tool."""
    tool_call_id: str = Field(..., description="ID of the tool call this result is for")
    success: bool = Field(..., description="Whether the tool execution succeeded")
    result: Optional[Dict[str, Any]] = Field(None, description="Tool execution result data")
    error: Optional[str] = Field(None, description="Error message if execution failed")


# ============================================================================
# Message Models
# ============================================================================

class ChatMessage(BaseModel):
    """A single message in the conversation."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique message ID")
    role: MessageRole = Field(..., description="Role of the message sender")
    content: Optional[str] = Field(None, description="Text content of the message")
    tool_calls: Optional[List[ToolCall]] = Field(None, description="Tool calls (for assistant messages)")
    tool_call_id: Optional[str] = Field(None, description="Tool call ID (for tool result messages)")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="When the message was created")
    
    model_config = {"from_attributes": True}


class ChatMessageCreate(BaseModel):
    """Request model for creating a new user message."""
    content: str = Field(..., min_length=1, max_length=4000, description="User's message content")
    session_id: Optional[str] = Field(None, description="Session ID for continuing a conversation")
    debug: bool = Field(False, description="When true, include debug info (tool calls, categories, timing) in response")


# ============================================================================
# Session Models
# ============================================================================

class ConversationSession(BaseModel):
    """A conversation session with history."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Session ID")
    user_id: str = Field(..., description="User who owns this session")
    title: Optional[str] = Field(None, description="Session title (derived from first message)")
    messages: List[ChatMessage] = Field(default_factory=list, description="Conversation history")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    model_config = {"from_attributes": True}
    
    def add_user_message(self, content: str) -> ChatMessage:
        """Add a user message to the conversation."""
        msg = ChatMessage(role=MessageRole.USER, content=content)
        self.messages.append(msg)
        self.updated_at = datetime.utcnow()
        # Set title from first user message
        if self.title is None:
            self.title = content[:50] + ("..." if len(content) > 50 else "")
        return msg
    
    def add_assistant_message(self, content: str, tool_calls: Optional[List[ToolCall]] = None) -> ChatMessage:
        """Add an assistant message to the conversation."""
        msg = ChatMessage(role=MessageRole.ASSISTANT, content=content, tool_calls=tool_calls)
        self.messages.append(msg)
        self.updated_at = datetime.utcnow()
        return msg
    
    def add_tool_result(self, tool_call_id: str, result: Dict[str, Any]) -> ChatMessage:
        """Add a tool result message."""
        import json
        msg = ChatMessage(
            role=MessageRole.TOOL,
            content=json.dumps(result),
            tool_call_id=tool_call_id
        )
        self.messages.append(msg)
        self.updated_at = datetime.utcnow()
        return msg
    
    def get_messages_for_llm(self, system_prompt: str) -> List[Dict[str, Any]]:
        """Get messages formatted for the LLM API."""
        result = [{"role": "system", "content": system_prompt}]
        
        for msg in self.messages:
            llm_msg: Dict[str, Any] = {"role": msg.role.value}
            
            if msg.content is not None:
                llm_msg["content"] = msg.content
            
            if msg.tool_calls:
                llm_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name.value,
                            "arguments": tc.arguments if isinstance(tc.arguments, str) else __import__('json').dumps(tc.arguments)
                        }
                    }
                    for tc in msg.tool_calls
                ]
            
            if msg.tool_call_id:
                llm_msg["tool_call_id"] = msg.tool_call_id
            
            result.append(llm_msg)
        
        return result


class SessionSummary(BaseModel):
    """Summary of a session for listing."""
    id: str
    title: Optional[str]
    message_count: int
    created_at: datetime
    updated_at: datetime
    
    model_config = {"from_attributes": True}


# ============================================================================
# Response Models
# ============================================================================

class ChatResponse(BaseModel):
    """Response from a chat request."""
    session_id: str = Field(..., description="Session ID for continuing the conversation")
    message: ChatMessage = Field(..., description="The assistant's response message")
    tool_calls_executed: int = Field(0, description="Number of tool calls made to generate this response")
    sources: List[Dict[str, Any]] = Field(default_factory=list, description="Data sources used in the response")
    debug: Optional[Dict[str, Any]] = Field(None, description="Debug info with tool calls, categories, and timing (only when debug=true)")


class LLMSearchStatus(BaseModel):
    """Status of the LLM search feature."""
    model_config = {"protected_namespaces": ()}

    enabled: bool = Field(..., description="Whether LLM search is enabled")
    endpoint: Optional[str] = Field(None, description="Configured LLM endpoint")
    model_name: Optional[str] = Field(None, description="Name of the configured foundation model")
    disclaimer: str = Field(..., description="Disclaimer text about AI limitations")


# ============================================================================
# Tool Result Data Models
# ============================================================================

class DataProductSearchResult(BaseModel):
    """A data product from search results."""
    id: str
    name: str
    domain: Optional[str] = None
    description: Optional[str] = None
    status: str
    output_tables: List[str] = Field(default_factory=list)
    owner: Optional[str] = None


class GlossaryTermResult(BaseModel):
    """A glossary term from search results."""
    id: str
    name: str
    definition: str
    domain: Optional[str] = None
    synonyms: List[str] = Field(default_factory=list)
    tagged_assets: List[Dict[str, Any]] = Field(default_factory=list)


class CostBreakdown(BaseModel):
    """Cost breakdown for a data product."""
    product_id: str
    product_name: str
    total_usd: float
    items: List[Dict[str, Any]] = Field(default_factory=list)


class TableSchemaResult(BaseModel):
    """Schema information for a table."""
    table_fqn: str
    columns: List[Dict[str, Any]]
    row_count: Optional[int] = None


class QueryExecutionResult(BaseModel):
    """Result from executing an analytics query."""
    columns: List[str]
    rows: List[List[Any]]
    row_count: int
    explanation: str
    query_truncated: bool = False

