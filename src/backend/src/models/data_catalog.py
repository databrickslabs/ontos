"""
Data Catalog / Data Dictionary API Models

This module implements Pydantic models for the Data Dictionary feature,
providing column-level browsing and lineage analysis across Unity Catalog.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field


# ============================================================================
# Enums
# ============================================================================

class LineageDirection(str, Enum):
    """Direction for lineage traversal."""
    UPSTREAM = "upstream"
    DOWNSTREAM = "downstream"
    BOTH = "both"


class AssetType(str, Enum):
    """Type of data asset in lineage."""
    TABLE = "table"
    VIEW = "view"
    EXTERNAL = "external"
    NOTEBOOK = "notebook"
    JOB = "job"
    DASHBOARD = "dashboard"


# ============================================================================
# Column & Table Models
# ============================================================================

class ColumnDictionaryEntry(BaseModel):
    """
    Single row in the Data Dictionary view.
    Represents a column with its table/contract context.
    """
    # Column identifiers
    column_name: str = Field(..., description="Technical column name (e.g., 'src_issuer_id')")
    column_label: Optional[str] = Field(None, description="Business-friendly label if available")
    
    # Column metadata
    column_type: str = Field(..., description="Data type (e.g., 'STRING', 'INT', 'DECIMAL(18,2)')")
    description: Optional[str] = Field(None, description="Column description/comment")
    nullable: bool = Field(True, description="Whether column allows NULL values")
    position: int = Field(0, description="Column ordinal position in table")
    
    # Additional column properties
    is_primary_key: bool = Field(False, description="Whether column is part of primary key")
    classification: Optional[str] = Field(None, description="Data classification (e.g., PII, Confidential)")
    
    # Table/Schema context
    table_name: str = Field(..., description="Short table/schema object name")
    table_full_name: str = Field(..., description="Fully qualified name: contract.schema_object or catalog.schema.table")
    schema_name: str = Field(..., description="Schema/Contract name")
    catalog_name: str = Field(..., description="Catalog/Version")
    table_type: str = Field("TABLE", description="TABLE, VIEW, DATASET, or CONTRACT")
    
    # Provenance
    source: str = Field("contract", description="Data source: 'contract', 'asset', or 'both'")
    asset_id: Optional[str] = Field(None, description="Source Asset ID when sourced from Asset DB")
    system_name: Optional[str] = Field(None, description="Parent System name in the asset hierarchy")
    
    # Contract context (when sourced from Data Contracts)
    contract_id: Optional[str] = Field(None, description="ID of the source Data Contract")
    contract_name: Optional[str] = Field(None, description="Name of the source Data Contract")
    contract_version: Optional[str] = Field(None, description="Version of the source Data Contract")
    contract_status: Optional[str] = Field(None, description="Status of the source Data Contract")
    
    # Business terms linked to this column (from authoritative definitions)
    business_terms: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Business terms/concepts linked to this column. Each item: {iri, label, type}"
    )
    
    @property
    def display_label(self) -> str:
        """Return display label (business label if set, else column name)."""
        return self.column_label or self.column_name
    
    model_config = {"from_attributes": True}


class ColumnInfo(BaseModel):
    """Column information within a table."""
    name: str
    type_text: str
    type_name: Optional[str] = None
    position: int = 0
    nullable: bool = True
    comment: Optional[str] = None
    
    # Optional metadata
    partition_index: Optional[int] = None
    mask: Optional[Dict[str, Any]] = None
    
    model_config = {"from_attributes": True}


class TableInfo(BaseModel):
    """Full table information with all columns."""
    # Identifiers
    full_name: str = Field(..., description="catalog.schema.table")
    name: str
    schema_name: str
    catalog_name: str
    
    # Metadata
    table_type: str = Field("TABLE", description="MANAGED, EXTERNAL, or VIEW")
    owner: Optional[str] = None
    comment: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    
    # Storage info
    storage_location: Optional[str] = None
    data_source_format: Optional[str] = None
    
    # Columns
    columns: List[ColumnInfo] = Field(default_factory=list)
    
    # Statistics
    row_count: Optional[int] = None
    size_bytes: Optional[int] = None
    
    # Tags (from UC)
    tags: Optional[Dict[str, str]] = None
    
    model_config = {"from_attributes": True}


class TableListItem(BaseModel):
    """Lightweight table/schema object info for dropdown/list views."""
    full_name: str
    name: str
    schema_name: str
    catalog_name: str
    table_type: str  # TABLE, VIEW, or CONTRACT
    column_count: int = 0
    comment: Optional[str] = None
    
    # Contract context (when sourced from Data Contracts)
    contract_id: Optional[str] = None
    contract_name: Optional[str] = None
    contract_version: Optional[str] = None
    contract_status: Optional[str] = None
    
    model_config = {"from_attributes": True}


# ============================================================================
# Search Models
# ============================================================================

class ColumnSearchRequest(BaseModel):
    """Request for column search."""
    query: str = Field(..., min_length=1, description="Search query for column name")
    catalog_filter: Optional[str] = Field(None, description="Filter to specific catalog")
    schema_filter: Optional[str] = Field(None, description="Filter to specific schema")
    table_filter: Optional[str] = Field(None, description="Filter to specific table (FQN)")
    limit: int = Field(500, ge=1, le=2000, description="Maximum results to return")
    offset: int = Field(0, ge=0, description="Offset for pagination")


class ColumnSearchResponse(BaseModel):
    """Response from column search."""
    query: str
    total_count: int
    columns: List[ColumnDictionaryEntry]
    has_more: bool = False
    offset: int = 0
    limit: int = 50
    filters_applied: Dict[str, Optional[str]] = Field(default_factory=dict)


# ============================================================================
# Lineage Models
# ============================================================================

class LineageNode(BaseModel):
    """Node in a lineage graph."""
    id: str = Field(..., description="Unique node ID (usually FQN)")
    name: str = Field(..., description="Display name")
    type: AssetType = Field(..., description="Asset type")
    
    # Location info
    catalog: Optional[str] = None
    schema_name: Optional[str] = Field(None, alias="schema")
    
    # Metadata
    owner: Optional[str] = None
    comment: Optional[str] = None
    
    # For external nodes
    external_system: Optional[str] = None
    external_url: Optional[str] = None
    
    # UI hints
    is_root: bool = Field(False, description="Whether this is the queried node")
    depth: int = Field(0, description="Distance from root node")
    
    model_config = {"from_attributes": True, "populate_by_name": True}


class ColumnMapping(BaseModel):
    """Column-level mapping in lineage edge."""
    source_column: str
    target_column: str
    transformation: Optional[str] = None  # e.g., "CAST", "UPPER", etc.


class LineageEdge(BaseModel):
    """Edge in a lineage graph."""
    source: str = Field(..., description="Source node ID")
    target: str = Field(..., description="Target node ID")
    
    # Optional column-level detail
    column_mappings: Optional[List[ColumnMapping]] = None
    
    # Metadata
    query_id: Optional[str] = None
    created_at: Optional[datetime] = None
    
    model_config = {"from_attributes": True}


class LineageGraph(BaseModel):
    """Complete lineage graph for visualization."""
    nodes: List[LineageNode] = Field(default_factory=list)
    edges: List[LineageEdge] = Field(default_factory=list)
    root_node: str = Field(..., description="ID of the queried node")
    direction: LineageDirection
    
    # Statistics
    upstream_count: int = 0
    downstream_count: int = 0
    external_count: int = 0
    
    model_config = {"from_attributes": True}


# ============================================================================
# Impact Analysis Models
# ============================================================================

class ImpactedAsset(BaseModel):
    """An asset impacted by a change."""
    id: str
    name: str
    type: AssetType
    full_name: Optional[str] = None
    
    # Impact details
    impact_path: List[str] = Field(default_factory=list, description="Path from source to this asset")
    distance: int = Field(1, description="Hops from source")
    
    # Affected columns (if column-level analysis)
    affected_columns: Optional[List[str]] = None
    
    # Owner for notification
    owner: Optional[str] = None
    
    model_config = {"from_attributes": True}


class ImpactAnalysis(BaseModel):
    """Result of impact analysis for a table or column change."""
    source_table: str = Field(..., description="Table being changed")
    source_column: Optional[str] = Field(None, description="Column being changed (if column-level)")
    
    # Impacted assets grouped by type
    impacted_tables: List[ImpactedAsset] = Field(default_factory=list)
    impacted_views: List[ImpactedAsset] = Field(default_factory=list)
    impacted_external: List[ImpactedAsset] = Field(default_factory=list)
    
    # Summary
    total_impacted_count: int = 0
    max_depth: int = 0
    
    # Owners to notify
    affected_owners: List[str] = Field(default_factory=list)
    
    model_config = {"from_attributes": True}


# ============================================================================
# Response Models
# ============================================================================

class DataDictionaryResponse(BaseModel):
    """Response for the main Data Dictionary view."""
    table_count: int
    column_count: int
    columns: List[ColumnDictionaryEntry]
    
    # Pagination
    offset: int = 0
    limit: int = 50
    has_more: bool = False
    
    # Filter state
    table_filter: Optional[str] = None
    
    model_config = {"from_attributes": True}


class TableListResponse(BaseModel):
    """Response for table dropdown list."""
    tables: List[TableListItem]
    total_count: int
    total_column_count: int
    
    model_config = {"from_attributes": True}


class HierarchyFilters(BaseModel):
    """Available filter values for the faceted filter UI."""
    asset_types: List[str] = Field(default_factory=list, description="Available asset types (Table, View, Dataset)")
    systems: List[str] = Field(default_factory=list, description="Available System names")
    catalogs: List[str] = Field(default_factory=list, description="Available Catalog names")
    schemas: List[str] = Field(default_factory=list, description="Available Schema names")
    
    model_config = {"from_attributes": True}

