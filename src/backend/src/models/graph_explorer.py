"""
Pydantic models for Graph Explorer API.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class GraphNodeRequest(BaseModel):
    """Request model for creating/updating a node."""
    id: str
    label: str
    type: str = "Node"
    properties: Dict[str, Any] = Field(default_factory=dict)


class GraphEdgeRequest(BaseModel):
    """Request model for creating/updating an edge."""
    id: Optional[str] = None
    source: str
    target: str
    relationshipType: str
    properties: Dict[str, Any] = Field(default_factory=dict)


class SaveGraphRequest(BaseModel):
    """Request model for saving new/modified graph data."""
    tableName: str
    nodes: List[GraphNodeRequest] = Field(default_factory=list)
    edges: List[GraphEdgeRequest] = Field(default_factory=list)


class DeleteNodeRequest(BaseModel):
    """Request model for deleting a node."""
    tableName: str
    nodeId: str


class DeleteEdgeRequest(BaseModel):
    """Request model for deleting an edge."""
    tableName: str
    sourceId: str
    targetId: str
    relationshipType: str


class UpdateNodeRequest(BaseModel):
    """Request model for updating a node."""
    tableName: str
    nodeId: str
    label: str
    type: str = "Node"
    properties: Dict[str, Any] = Field(default_factory=dict)


class GraphDataResponse(BaseModel):
    """Response model for graph data."""
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]


class SaveGraphResponse(BaseModel):
    """Response model for save operation."""
    nodesWritten: int
    edgesWritten: int


class EnsureTableResponse(BaseModel):
    """Response model for table creation."""
    tableName: str
    status: str = "ok"


# ---------------------------------------------------------------------------
# Graph Query (Cypher / Gremlin → SQL via LLM)
# ---------------------------------------------------------------------------

class GraphQueryRequest(BaseModel):
    """Request model for executing a Cypher/Gremlin graph query."""
    query: str
    language: str = Field(default="cypher", description="Query language: 'cypher' or 'gremlin'")
    tableName: Optional[str] = None
    modelEndpoint: Optional[str] = None
    sql: Optional[str] = Field(default=None, description="Override SQL — skip LLM translation and execute directly")


class GraphQueryResponseMetadata(BaseModel):
    """Metadata about the query execution."""
    source: str = "databricks"
    timestamp: Optional[str] = None
    duration: Optional[str] = None
    translationModel: Optional[str] = None
    graphSchema: Optional[str] = None


class GraphQueryResponse(BaseModel):
    """Response model for a graph query execution."""
    success: bool
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    edges: List[Dict[str, Any]] = Field(default_factory=list)
    sql: str = ""
    language: str = ""
    originalQuery: str = ""
    rawRowCount: Optional[int] = None
    hasEdgeColumns: Optional[bool] = None
    vertexOnly: Optional[bool] = None
    message: Optional[str] = None
    metadata: Optional[GraphQueryResponseMetadata] = None


class LlmConfigResponse(BaseModel):
    """Response model for LLM configuration status."""
    enabled: bool
    defaultModel: str = ""
    maxTokens: int = 4096
    provider: str = "databricks"
