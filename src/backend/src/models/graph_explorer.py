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
