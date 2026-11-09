"""
Schema Import Models

Request/response models for the Schema Importer feature, which bridges
external connectors (BigQuery, Databricks, Snowflake, etc.) with persisted
Ontos assets.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Browse models
# ---------------------------------------------------------------------------

class BrowseNode(BaseModel):
    """A single node in the remote system hierarchy."""
    name: str = Field(..., description="Display name of the node")
    node_type: str = Field(..., description="Type label (e.g. catalog, schema, dataset, table, view)")
    path: str = Field(..., description="Dot-separated path used for further browsing")
    has_children: bool = Field(False, description="Whether expanding this node will yield children")
    description: Optional[str] = Field(None, description="Optional description/comment")
    asset_type: Optional[str] = Field(None, description="UnifiedAssetType value if this is a leaf asset")
    connector_type: Optional[str] = Field(None, description="Connector type that owns this node")


class BrowseResponse(BaseModel):
    """Response for a browse request."""
    connection_id: UUID
    path: Optional[str] = None
    nodes: List[BrowseNode] = Field(default_factory=list)
    error: Optional[str] = Field(None, description="Short error message if browsing failed")
    error_detail: Optional[str] = Field(None, description="Full error details for debugging")
    truncated: bool = Field(False, description="True if leaf assets at this path were capped by the configured fetch limit; more assets exist than are shown")
    truncated_at: Optional[int] = Field(None, description="The child fetch limit that was applied when truncated is True")


# ---------------------------------------------------------------------------
# Import depth
# ---------------------------------------------------------------------------

class ImportDepth(str, Enum):
    SELECTED_ONLY = "selected_only"
    ONE_LEVEL = "one_level"
    FULL_RECURSIVE = "full_recursive"


# ---------------------------------------------------------------------------
# Import request / preview / result
# ---------------------------------------------------------------------------

class ImportRequest(BaseModel):
    """Request to preview or execute a schema import."""
    connection_id: UUID = Field(..., description="ID of the connection to import from")
    selected_paths: List[str] = Field(..., min_length=1, description="Dot-separated paths of selected nodes")
    depth: ImportDepth = Field(ImportDepth.FULL_RECURSIVE, description="How deep to recurse below selected nodes")
    dry_run: bool = Field(False, description="If true, only preview — do not create assets")
    excluded_paths: List[str] = Field(default_factory=list, description="Paths the user chose to exclude from import")
    path_mappings: Dict[str, UUID] = Field(default_factory=dict, description="Map preview path to an existing asset ID instead of creating a new one")


class ImportPreviewItem(BaseModel):
    """A single item in an import preview."""
    path: str = Field(..., description="Full path of the item")
    name: str = Field(..., description="Display name")
    asset_type: str = Field(..., description="Mapped Ontos asset type name (e.g. Table, View, Column)")
    will_create: bool = Field(True, description="True if a new asset will be created, False if it already exists")
    existing_asset_id: Optional[UUID] = Field(None, description="ID of the existing asset if will_create is False")
    parent_path: Optional[str] = Field(None, description="Path of the parent node (for relationship creation)")
    is_ancestor: bool = Field(False, description="True for auto-included structural parents (System, Catalog, Schema)")


class ImportResultItem(BaseModel):
    """Outcome for a single imported item."""
    path: str
    name: str
    asset_type: str
    action: str = Field(..., description="created | skipped | error")
    asset_id: Optional[UUID] = None
    error: Optional[str] = None
    parent_path: Optional[str] = Field(None, description="Path of the parent node (for tree display)")


class ImportResult(BaseModel):
    """Overall import result."""
    created: int = 0
    skipped: int = 0
    errors: int = 0
    error_messages: List[str] = Field(default_factory=list)
    items: List[ImportResultItem] = Field(default_factory=list)
    system_asset_id: Optional[UUID] = Field(None, description="ID of the System asset used as hierarchy root")


# ---------------------------------------------------------------------------
# Async import run (background execution)
# ---------------------------------------------------------------------------

class SchemaImportRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StartImportRunResponse(BaseModel):
    """Returned by the async import endpoint (HTTP 202)."""
    run_id: str = Field(..., description="ID of the background import run to poll")
    status: SchemaImportRunStatus = SchemaImportRunStatus.PENDING


class SchemaImportRunDetail(BaseModel):
    """Status + progress of a background import run (poll target)."""
    model_config = {"from_attributes": True}

    id: str
    status: SchemaImportRunStatus
    progress_message: Optional[str] = None
    error: Optional[str] = None
    connection_id: Optional[str] = None
    total_items: Optional[int] = None
    processed_items: int = 0
    created_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    result: Optional[ImportResult] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class SchemaImportRunSummary(BaseModel):
    """Lightweight run row for list views."""
    model_config = {"from_attributes": True}

    id: str
    status: SchemaImportRunStatus
    connection_id: Optional[str] = None
    total_items: Optional[int] = None
    processed_items: int = 0
    created_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
