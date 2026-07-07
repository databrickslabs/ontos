"""
Unified Asset Models

This module provides platform-agnostic asset type definitions and metadata models
for the pluggable connector architecture. It enables Datasets and Contracts to
reference any asset type uniformly across Unity Catalog, Snowflake, Kafka, PowerBI,
and other platforms.

It also contains the reference-data models for persisted Asset Types and Assets
(the cataloged "things" that Ontos governs, stored in the database).
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field

from src.models.domain_associations import AssignedDomain


# ============================================================================
# Asset Categories (Connector-level)
# ============================================================================

class AssetCategory(str, Enum):
    """High-level categorization of assets by their primary function."""
    DATA = "data"           # Tables, views, topics, streams
    COMPUTE = "compute"     # Functions, models, jobs, notebooks
    SEMANTIC = "semantic"   # Metrics, measures, dimensions, KPIs
    VISUALIZATION = "viz"   # Dashboards, reports, charts
    STORAGE = "storage"     # Files, objects, volumes
    OTHER = "other"         # Catch-all for uncategorized assets


# ============================================================================
# Unified Asset Types (Connector-level)
# ============================================================================

class UnifiedAssetType(str, Enum):
    """
    Unified enumeration of all supported asset types across platforms.
    
    Naming convention: {PLATFORM}_{ASSET_TYPE}
    This allows platform-specific handling while maintaining a unified interface.
    """
    # -------------------------------------------------------------------------
    # Unity Catalog / Databricks - Structural Containers
    # -------------------------------------------------------------------------
    UC_CATALOG = "uc_catalog"
    UC_SCHEMA = "uc_schema"

    # -------------------------------------------------------------------------
    # Unity Catalog / Databricks - Data Assets
    # -------------------------------------------------------------------------
    UC_TABLE = "uc_table"
    UC_VIEW = "uc_view"
    UC_MATERIALIZED_VIEW = "uc_materialized_view"
    UC_STREAMING_TABLE = "uc_streaming_table"
    UC_VOLUME = "uc_volume"
    UC_VOLUME_FILE = "uc_volume_file"
    
    # -------------------------------------------------------------------------
    # Unity Catalog / Databricks - Compute Assets
    # -------------------------------------------------------------------------
    UC_FUNCTION = "uc_function"
    UC_MODEL = "uc_model"
    UC_NOTEBOOK = "uc_notebook"
    UC_JOB = "uc_job"
    UC_PIPELINE = "uc_pipeline"  # DLT / Spark Declarative Pipelines (SDP)
    
    # -------------------------------------------------------------------------
    # Unity Catalog / Databricks - Semantic Assets (NEW)
    # -------------------------------------------------------------------------
    UC_METRIC = "uc_metric"  # Unity Catalog metrics (AI/BI)
    
    # -------------------------------------------------------------------------
    # Snowflake - Structural Containers
    # -------------------------------------------------------------------------
    SNOWFLAKE_DATABASE = "snowflake_database"
    SNOWFLAKE_SCHEMA = "snowflake_schema"

    # -------------------------------------------------------------------------
    # Snowflake - Data Assets
    # -------------------------------------------------------------------------
    SNOWFLAKE_TABLE = "snowflake_table"
    SNOWFLAKE_VIEW = "snowflake_view"
    SNOWFLAKE_MATERIALIZED_VIEW = "snowflake_materialized_view"
    SNOWFLAKE_STREAM = "snowflake_stream"
    SNOWFLAKE_STAGE = "snowflake_stage"
    
    # -------------------------------------------------------------------------
    # Snowflake - Compute Assets
    # -------------------------------------------------------------------------
    SNOWFLAKE_FUNCTION = "snowflake_function"
    SNOWFLAKE_PROCEDURE = "snowflake_procedure"
    SNOWFLAKE_TASK = "snowflake_task"
    
    # -------------------------------------------------------------------------
    # BigQuery - Structural Containers
    # -------------------------------------------------------------------------
    BQ_PROJECT = "bq_project"
    BQ_DATASET = "bq_dataset"

    # -------------------------------------------------------------------------
    # BigQuery - Data Assets
    # -------------------------------------------------------------------------
    BQ_TABLE = "bq_table"
    BQ_VIEW = "bq_view"
    BQ_MATERIALIZED_VIEW = "bq_materialized_view"
    BQ_EXTERNAL_TABLE = "bq_external_table"
    
    # -------------------------------------------------------------------------
    # BigQuery - Compute Assets
    # -------------------------------------------------------------------------
    BQ_ROUTINE = "bq_routine"
    BQ_MODEL = "bq_model"
    
    # -------------------------------------------------------------------------
    # Kafka - Data Assets
    # -------------------------------------------------------------------------
    KAFKA_TOPIC = "kafka_topic"
    KAFKA_SCHEMA = "kafka_schema"  # Schema Registry schemas
    
    # -------------------------------------------------------------------------
    # PowerBI - Visualization & Semantic Assets
    # -------------------------------------------------------------------------
    POWERBI_DATASET = "powerbi_dataset"
    POWERBI_SEMANTIC_MODEL = "powerbi_semantic_model"
    POWERBI_DASHBOARD = "powerbi_dashboard"
    POWERBI_REPORT = "powerbi_report"
    POWERBI_DATAFLOW = "powerbi_dataflow"
    
    # -------------------------------------------------------------------------
    # Cloud Storage - Storage Assets
    # -------------------------------------------------------------------------
    S3_BUCKET = "s3_bucket"
    S3_OBJECT = "s3_object"
    ADLS_CONTAINER = "adls_container"
    ADLS_PATH = "adls_path"
    GCS_BUCKET = "gcs_bucket"
    GCS_OBJECT = "gcs_object"
    
    # -------------------------------------------------------------------------
    # API & External - Other Assets
    # -------------------------------------------------------------------------
    EXTERNAL_API = "external_api"
    EXTERNAL_DATABASE = "external_database"
    
    # -------------------------------------------------------------------------
    # Generic / Unknown
    # -------------------------------------------------------------------------
    GENERIC = "generic"
    UNKNOWN = "unknown"


# ============================================================================
# Asset Type Metadata
# ============================================================================

# Mapping of asset types to their categories
ASSET_TYPE_CATEGORIES: Dict[UnifiedAssetType, AssetCategory] = {
    # UC Data
    UnifiedAssetType.UC_TABLE: AssetCategory.DATA,
    UnifiedAssetType.UC_VIEW: AssetCategory.DATA,
    UnifiedAssetType.UC_MATERIALIZED_VIEW: AssetCategory.DATA,
    UnifiedAssetType.UC_STREAMING_TABLE: AssetCategory.DATA,
    UnifiedAssetType.UC_VOLUME: AssetCategory.STORAGE,
    UnifiedAssetType.UC_VOLUME_FILE: AssetCategory.STORAGE,
    # UC Compute
    UnifiedAssetType.UC_FUNCTION: AssetCategory.COMPUTE,
    UnifiedAssetType.UC_MODEL: AssetCategory.COMPUTE,
    UnifiedAssetType.UC_NOTEBOOK: AssetCategory.COMPUTE,
    UnifiedAssetType.UC_JOB: AssetCategory.COMPUTE,
    UnifiedAssetType.UC_PIPELINE: AssetCategory.COMPUTE,
    # UC Semantic
    UnifiedAssetType.UC_METRIC: AssetCategory.SEMANTIC,
    # Snowflake Data
    UnifiedAssetType.SNOWFLAKE_TABLE: AssetCategory.DATA,
    UnifiedAssetType.SNOWFLAKE_VIEW: AssetCategory.DATA,
    UnifiedAssetType.SNOWFLAKE_MATERIALIZED_VIEW: AssetCategory.DATA,
    UnifiedAssetType.SNOWFLAKE_STREAM: AssetCategory.DATA,
    UnifiedAssetType.SNOWFLAKE_STAGE: AssetCategory.STORAGE,
    # Snowflake Compute
    UnifiedAssetType.SNOWFLAKE_FUNCTION: AssetCategory.COMPUTE,
    UnifiedAssetType.SNOWFLAKE_PROCEDURE: AssetCategory.COMPUTE,
    UnifiedAssetType.SNOWFLAKE_TASK: AssetCategory.COMPUTE,
    # BigQuery Data
    UnifiedAssetType.BQ_TABLE: AssetCategory.DATA,
    UnifiedAssetType.BQ_VIEW: AssetCategory.DATA,
    UnifiedAssetType.BQ_MATERIALIZED_VIEW: AssetCategory.DATA,
    UnifiedAssetType.BQ_EXTERNAL_TABLE: AssetCategory.DATA,
    # BigQuery Compute
    UnifiedAssetType.BQ_ROUTINE: AssetCategory.COMPUTE,
    UnifiedAssetType.BQ_MODEL: AssetCategory.COMPUTE,
    # Kafka
    UnifiedAssetType.KAFKA_TOPIC: AssetCategory.DATA,
    UnifiedAssetType.KAFKA_SCHEMA: AssetCategory.DATA,
    # PowerBI
    UnifiedAssetType.POWERBI_DATASET: AssetCategory.DATA,
    UnifiedAssetType.POWERBI_SEMANTIC_MODEL: AssetCategory.SEMANTIC,
    UnifiedAssetType.POWERBI_DASHBOARD: AssetCategory.VISUALIZATION,
    UnifiedAssetType.POWERBI_REPORT: AssetCategory.VISUALIZATION,
    UnifiedAssetType.POWERBI_DATAFLOW: AssetCategory.DATA,
    # Cloud Storage
    UnifiedAssetType.S3_BUCKET: AssetCategory.STORAGE,
    UnifiedAssetType.S3_OBJECT: AssetCategory.STORAGE,
    UnifiedAssetType.ADLS_CONTAINER: AssetCategory.STORAGE,
    UnifiedAssetType.ADLS_PATH: AssetCategory.STORAGE,
    UnifiedAssetType.GCS_BUCKET: AssetCategory.STORAGE,
    UnifiedAssetType.GCS_OBJECT: AssetCategory.STORAGE,
    # External
    UnifiedAssetType.EXTERNAL_API: AssetCategory.OTHER,
    UnifiedAssetType.EXTERNAL_DATABASE: AssetCategory.DATA,
    # Generic
    UnifiedAssetType.GENERIC: AssetCategory.OTHER,
    UnifiedAssetType.UNKNOWN: AssetCategory.OTHER,
}

# Mapping of asset types that support schema (columns/fields)
SCHEMA_SUPPORTING_TYPES: set = {
    UnifiedAssetType.UC_TABLE,
    UnifiedAssetType.UC_VIEW,
    UnifiedAssetType.UC_MATERIALIZED_VIEW,
    UnifiedAssetType.UC_STREAMING_TABLE,
    UnifiedAssetType.SNOWFLAKE_TABLE,
    UnifiedAssetType.SNOWFLAKE_VIEW,
    UnifiedAssetType.SNOWFLAKE_MATERIALIZED_VIEW,
    UnifiedAssetType.BQ_TABLE,
    UnifiedAssetType.BQ_VIEW,
    UnifiedAssetType.BQ_MATERIALIZED_VIEW,
    UnifiedAssetType.BQ_EXTERNAL_TABLE,
    UnifiedAssetType.KAFKA_TOPIC,  # If using Schema Registry
    UnifiedAssetType.POWERBI_DATASET,
    UnifiedAssetType.POWERBI_SEMANTIC_MODEL,
}

# Mapping of connector types to supported asset types
CONNECTOR_ASSET_TYPES: Dict[str, List[UnifiedAssetType]] = {
    "databricks": [
        UnifiedAssetType.UC_TABLE,
        UnifiedAssetType.UC_VIEW,
        UnifiedAssetType.UC_MATERIALIZED_VIEW,
        UnifiedAssetType.UC_STREAMING_TABLE,
        UnifiedAssetType.UC_VOLUME,
        UnifiedAssetType.UC_VOLUME_FILE,
        UnifiedAssetType.UC_FUNCTION,
        UnifiedAssetType.UC_MODEL,
        UnifiedAssetType.UC_NOTEBOOK,
        UnifiedAssetType.UC_JOB,
        UnifiedAssetType.UC_PIPELINE,
        UnifiedAssetType.UC_METRIC,
    ],
    "snowflake": [
        UnifiedAssetType.SNOWFLAKE_TABLE,
        UnifiedAssetType.SNOWFLAKE_VIEW,
        UnifiedAssetType.SNOWFLAKE_MATERIALIZED_VIEW,
        UnifiedAssetType.SNOWFLAKE_STREAM,
        UnifiedAssetType.SNOWFLAKE_STAGE,
        UnifiedAssetType.SNOWFLAKE_FUNCTION,
        UnifiedAssetType.SNOWFLAKE_PROCEDURE,
        UnifiedAssetType.SNOWFLAKE_TASK,
    ],
    "bigquery": [
        UnifiedAssetType.BQ_TABLE,
        UnifiedAssetType.BQ_VIEW,
        UnifiedAssetType.BQ_MATERIALIZED_VIEW,
        UnifiedAssetType.BQ_EXTERNAL_TABLE,
        UnifiedAssetType.BQ_ROUTINE,
        UnifiedAssetType.BQ_MODEL,
    ],
    "kafka": [
        UnifiedAssetType.KAFKA_TOPIC,
        UnifiedAssetType.KAFKA_SCHEMA,
    ],
    "powerbi": [
        UnifiedAssetType.POWERBI_DATASET,
        UnifiedAssetType.POWERBI_SEMANTIC_MODEL,
        UnifiedAssetType.POWERBI_DASHBOARD,
        UnifiedAssetType.POWERBI_REPORT,
        UnifiedAssetType.POWERBI_DATAFLOW,
    ],
    "s3": [
        UnifiedAssetType.S3_BUCKET,
        UnifiedAssetType.S3_OBJECT,
    ],
}


def get_asset_category(asset_type: UnifiedAssetType) -> AssetCategory:
    """Get the category for a given asset type."""
    return ASSET_TYPE_CATEGORIES.get(asset_type, AssetCategory.OTHER)


def supports_schema(asset_type: UnifiedAssetType) -> bool:
    """Check if an asset type supports schema (columns/fields)."""
    return asset_type in SCHEMA_SUPPORTING_TYPES


def get_connector_type_for_asset(asset_type: UnifiedAssetType) -> Optional[str]:
    """Get the connector type that handles a given asset type."""
    for connector_type, asset_types in CONNECTOR_ASSET_TYPES.items():
        if asset_type in asset_types:
            return connector_type
    return None


# ============================================================================
# Schema Models (for assets that have columnar structure)
# ============================================================================

class ColumnInfo(BaseModel):
    """Information about a single column/field in an asset's schema."""
    name: str = Field(..., description="Column name")
    data_type: str = Field(..., description="Data type (platform-specific)")
    logical_type: Optional[str] = Field(None, description="Logical/normalized type")
    nullable: bool = Field(True, description="Whether the column allows nulls")
    description: Optional[str] = Field(None, description="Column description/comment")
    is_primary_key: bool = Field(False, description="Whether this is part of the primary key")
    is_partition_key: bool = Field(False, description="Whether this is a partition column")
    default_value: Optional[str] = Field(None, description="Default value if any")
    
    # Extended metadata
    tags: Dict[str, str] = Field(default_factory=dict, description="Column-level tags")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Additional properties")
    
    model_config = {"from_attributes": True}


class SchemaInfo(BaseModel):
    """Schema information for assets that have columnar structure."""
    columns: List[ColumnInfo] = Field(default_factory=list, description="List of columns")
    primary_key: Optional[List[str]] = Field(None, description="Primary key column names")
    partition_columns: Optional[List[str]] = Field(None, description="Partition column names")
    clustering_columns: Optional[List[str]] = Field(None, description="Clustering column names")
    
    # Schema versioning
    schema_version: Optional[str] = Field(None, description="Schema version if tracked")
    
    model_config = {"from_attributes": True}
    
    @property
    def column_count(self) -> int:
        """Return the number of columns."""
        return len(self.columns)
    
    def get_column(self, name: str) -> Optional[ColumnInfo]:
        """Get a column by name (case-insensitive)."""
        name_lower = name.lower()
        for col in self.columns:
            if col.name.lower() == name_lower:
                return col
        return None


# ============================================================================
# Asset Metadata Models (Connector-level)
# ============================================================================

class AssetOwnership(BaseModel):
    """Ownership information for an asset."""
    owner: Optional[str] = Field(None, description="Primary owner (user or group)")
    owner_email: Optional[str] = Field(None, description="Owner email")
    steward: Optional[str] = Field(None, description="Data steward")
    team: Optional[str] = Field(None, description="Owning team")
    
    model_config = {"from_attributes": True}


class AssetStatistics(BaseModel):
    """Statistics about an asset (when available)."""
    row_count: Optional[int] = Field(None, description="Number of rows/records")
    size_bytes: Optional[int] = Field(None, description="Size in bytes")
    partition_count: Optional[int] = Field(None, description="Number of partitions")
    file_count: Optional[int] = Field(None, description="Number of files (for table formats)")
    last_modified: Optional[datetime] = Field(None, description="Last modification timestamp")
    last_accessed: Optional[datetime] = Field(None, description="Last access timestamp")
    
    model_config = {"from_attributes": True}


class AssetInfo(BaseModel):
    """
    Basic information about an asset, returned by list operations.
    
    This is a lightweight model for discovery/listing purposes.
    For full details, use AssetMetadata.
    """
    identifier: str = Field(..., description="Unique identifier (FQN or path)")
    name: str = Field(..., description="Display name")
    asset_type: UnifiedAssetType = Field(..., description="Type of the asset")
    connector_type: str = Field(..., description="Connector type that manages this asset")
    
    # Optional quick info
    description: Optional[str] = Field(None, description="Short description")
    path: Optional[str] = Field(None, description="Full path to the asset")
    url: Optional[str] = Field(None, description="URL to view the asset in its native UI")
    
    # Container hierarchy (if applicable)
    catalog: Optional[str] = Field(None, description="Catalog/database name")
    schema_name: Optional[str] = Field(None, alias="schema", description="Schema name")
    
    model_config = {"from_attributes": True, "populate_by_name": True}
    
    @property
    def category(self) -> AssetCategory:
        """Get the category of this asset."""
        return get_asset_category(self.asset_type)
    
    @property
    def has_schema(self) -> bool:
        """Check if this asset type supports schema."""
        return supports_schema(self.asset_type)


class AssetMetadata(BaseModel):
    """
    Full metadata for an asset.
    
    This is the comprehensive model returned by get_asset_metadata operations,
    including schema, statistics, ownership, and platform-specific properties.
    """
    # Core identity
    identifier: str = Field(..., description="Unique identifier (FQN or path)")
    name: str = Field(..., description="Display name")
    asset_type: UnifiedAssetType = Field(..., description="Type of the asset")
    connector_type: str = Field(..., description="Connector type that manages this asset")
    
    # Description and documentation
    description: Optional[str] = Field(None, description="Full description")
    comment: Optional[str] = Field(None, description="Comment (if different from description)")
    
    # Location
    path: Optional[str] = Field(None, description="Full path to the asset")
    url: Optional[str] = Field(None, description="URL to view the asset in its native UI")
    location: Optional[str] = Field(None, description="Physical location (e.g., S3 path)")
    
    # Container hierarchy
    catalog: Optional[str] = Field(None, description="Catalog/database name")
    schema_name: Optional[str] = Field(None, alias="schema", description="Schema name")
    
    # Schema (for data assets)
    schema_info: Optional[SchemaInfo] = Field(None, description="Schema information")
    
    # Ownership
    ownership: Optional[AssetOwnership] = Field(None, description="Ownership information")
    
    # Statistics
    statistics: Optional[AssetStatistics] = Field(None, description="Asset statistics")
    
    # Tags and properties
    tags: Dict[str, str] = Field(default_factory=dict, description="Tags/labels")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Platform-specific properties")
    
    # Lifecycle
    created_at: Optional[datetime] = Field(None, description="Creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")
    created_by: Optional[str] = Field(None, description="Creator")
    updated_by: Optional[str] = Field(None, description="Last updater")
    
    # Status
    status: Optional[str] = Field(None, description="Asset status if applicable")
    
    # Validation result (populated by connector)
    exists: bool = Field(True, description="Whether the asset currently exists")
    validation_message: Optional[str] = Field(None, description="Validation message if any")
    
    model_config = {"from_attributes": True, "populate_by_name": True}
    
    @property
    def category(self) -> AssetCategory:
        """Get the category of this asset."""
        return get_asset_category(self.asset_type)
    
    @property
    def has_schema(self) -> bool:
        """Check if this asset type supports schema."""
        return supports_schema(self.asset_type)
    
    @property
    def column_count(self) -> int:
        """Get the number of columns if schema is available."""
        if self.schema_info:
            return self.schema_info.column_count
        return 0


# ============================================================================
# Validation Result
# ============================================================================

class AssetValidationResult(BaseModel):
    """Result of validating an asset's existence."""
    identifier: str = Field(..., description="Asset identifier that was validated")
    exists: bool = Field(..., description="Whether the asset exists")
    validated: bool = Field(True, description="Whether validation was performed")
    asset_type: Optional[UnifiedAssetType] = Field(None, description="Detected asset type")
    message: Optional[str] = Field(None, description="Validation message")
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional details")
    
    model_config = {"from_attributes": True}


# ============================================================================
# Sample Data
# ============================================================================

class SampleData(BaseModel):
    """Sample data from an asset."""
    columns: List[str] = Field(default_factory=list, description="Column names")
    rows: List[List[Any]] = Field(default_factory=list, description="Data rows")
    total_rows: Optional[int] = Field(None, description="Total row count in the asset")
    sample_size: int = Field(0, description="Number of rows in this sample")
    truncated: bool = Field(False, description="Whether the sample was truncated")
    
    model_config = {"from_attributes": True}
    
    @property
    def row_count(self) -> int:
        """Return the number of sample rows."""
        return len(self.rows)


# ============================================================================
# Reference Data: Persisted Asset Types and Assets (Database-backed)
# ============================================================================
# These models represent the cataloged "things" Ontos governs, stored in the
# database. They complement the connector-level models above.

class AssetTypeStatus(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class AssetTypeCategory(str, Enum):
    """Category for persisted asset type definitions."""
    DATA = "data"
    ANALYTICS = "analytics"
    INTEGRATION = "integration"
    SYSTEM = "system"
    CUSTOM = "custom"


class AssetStatus(str, Enum):
    """Asset lifecycle status. Aligned with EntityStatus."""
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


# --- Persisted Asset Type Models ---

class AssetTypeBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Unique asset type name (e.g., Table, Dashboard, API)")
    description: Optional[str] = Field(None, description="Human-readable description")
    category: Optional[AssetTypeCategory] = Field(None, description="High-level category")
    icon: Optional[str] = Field(None, description="Icon identifier for UI display")
    required_fields: Optional[Dict[str, Any]] = Field(None, description="JSON schema for required metadata fields")
    optional_fields: Optional[Dict[str, Any]] = Field(None, description="JSON schema for optional metadata fields")
    allowed_relationships: Optional[List[str]] = Field(None, description="Valid relationship types for assets of this type")
    is_system: bool = Field(False, description="Whether this is a built-in asset type")
    status: AssetTypeStatus = Field(AssetTypeStatus.ACTIVE, description="Lifecycle status")


class AssetTypeCreate(AssetTypeBase):
    pass


class AssetTypeUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    category: Optional[AssetTypeCategory] = None
    icon: Optional[str] = None
    required_fields: Optional[Dict[str, Any]] = None
    optional_fields: Optional[Dict[str, Any]] = None
    allowed_relationships: Optional[List[str]] = None
    is_system: Optional[bool] = None
    status: Optional[AssetTypeStatus] = None


class AssetTypeRead(AssetTypeBase):
    id: UUID
    asset_count: int = Field(0, description="Number of assets of this type")
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AssetTypeSummary(BaseModel):
    """Lightweight representation for dropdowns."""
    id: UUID
    name: str
    category: Optional[AssetTypeCategory] = None
    icon: Optional[str] = None
    status: AssetTypeStatus

    model_config = {"from_attributes": True}


# --- Asset Relationship Models ---

class AssetRelationshipBase(BaseModel):
    source_asset_id: UUID = Field(..., description="ID of the source asset")
    target_asset_id: UUID = Field(..., description="ID of the target asset")
    relationship_type: str = Field(..., description="Type of relationship (hasColumn, belongsToSystem, consumesFrom, etc.)")
    properties: Optional[Dict[str, Any]] = Field(None, description="Additional relationship metadata")


class AssetRelationshipCreate(AssetRelationshipBase):
    pass


class AssetRelationshipRead(AssetRelationshipBase):
    id: UUID
    created_by: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Persisted Asset Models ---

class AssetBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=500, description="Asset name")
    description: Optional[str] = Field(None, description="Human-readable description")
    asset_type_id: UUID = Field(..., description="ID of the persisted asset type")
    platform: Optional[str] = Field(None, description="Platform (e.g., Databricks, Power BI)")
    location: Optional[str] = Field(None, description="FQDN, URL, or path")
    domain_ids: List[str] = Field(default_factory=list, description="Assigned data domain IDs (primary included)")
    primary_domain_id: Optional[str] = Field(None, description="Primary data domain ID")
    properties: Optional[Dict[str, Any]] = Field(None, description="Type-specific metadata")
    tags: Optional[List[str]] = Field(None, description="Quick tags/classifications")
    status: AssetStatus = Field(AssetStatus.ACTIVE, description="Lifecycle status")


class AssetCreate(AssetBase):
    pass


class AssetUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = None
    asset_type_id: Optional[UUID] = None
    platform: Optional[str] = None
    location: Optional[str] = None
    domain_ids: Optional[List[str]] = None
    primary_domain_id: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    status: Optional[AssetStatus] = None


class AssetRead(AssetBase):
    id: UUID
    domains: List[AssignedDomain] = Field(default_factory=list, description="Assigned domains with names + primary flag")
    asset_type_name: Optional[str] = Field(None, description="Resolved asset type name")
    relationships: List[AssetRelationshipRead] = Field(default_factory=list)
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AssetSummary(BaseModel):
    """Lightweight representation for lists."""
    id: UUID
    name: str
    description: Optional[str] = None
    asset_type_id: UUID
    asset_type_name: Optional[str] = None
    platform: Optional[str] = None
    location: Optional[str] = None
    tags: Optional[List[str]] = None
    status: AssetStatus
    # Multi-domain assignment (#520): carried on summaries so list rows can show domain
    # badges and edit dialogs (fed an AssetSummary) preserve domains on save.
    domain_ids: List[str] = Field(default_factory=list)
    primary_domain_id: Optional[str] = None
    domains: List[AssignedDomain] = Field(default_factory=list)
    parent_id: Optional[UUID] = Field(None, description="ID of the parent asset (from hierarchical relationship)")
    parent_name: Optional[str] = Field(None, description="Name of the parent asset")
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class PaginatedAssetSummary(BaseModel):
    """Paginated wrapper for asset summaries."""
    items: List[AssetSummary]
    total: int
    skip: int
    limit: int


# --- Cascade Delete Models ---

class DeletePreviewItem(BaseModel):
    """A node in the cascade-delete preview tree."""
    id: UUID
    name: str
    asset_type_name: Optional[str] = None
    relationship_type: Optional[str] = None
    level: int = 0
    children: List["DeletePreviewItem"] = Field(default_factory=list)


class CascadeDeleteRequest(BaseModel):
    asset_ids: List[UUID] = Field(..., min_length=1, description="Asset IDs to delete")


class CascadeDeleteResult(BaseModel):
    deleted: List[Dict[str, Any]] = Field(default_factory=list)
    failed: List[Dict[str, Any]] = Field(default_factory=list)
