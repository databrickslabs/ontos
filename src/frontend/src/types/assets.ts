/**
 * Unified Asset Types
 * 
 * This module provides platform-agnostic asset type definitions for the
 * pluggable connector architecture. It enables Datasets and Contracts to
 * reference any asset type uniformly across Unity Catalog, Snowflake,
 * Kafka, PowerBI, and other platforms.
 * 
 * These types mirror the backend definitions in src/backend/src/models/assets.py
 */

// ============================================================================
// Asset Categories
// ============================================================================

/**
 * High-level categorization of assets by their primary function.
 */
export enum AssetCategory {
    DATA = "data",           // Tables, views, topics, streams
    COMPUTE = "compute",     // Functions, models, jobs, notebooks
    SEMANTIC = "semantic",   // Metrics, measures, dimensions, KPIs
    VISUALIZATION = "viz",   // Dashboards, reports, charts
    STORAGE = "storage",     // Files, objects, volumes
    OTHER = "other",         // Catch-all for uncategorized assets
}

// ============================================================================
// Unified Asset Types
// ============================================================================

/**
 * Unified enumeration of all supported asset types across platforms.
 * 
 * Naming convention: {PLATFORM}_{ASSET_TYPE}
 * This allows platform-specific handling while maintaining a unified interface.
 */
export enum UnifiedAssetType {
    // -------------------------------------------------------------------------
    // Unity Catalog / Databricks - Data Assets
    // -------------------------------------------------------------------------
    UC_TABLE = "uc_table",
    UC_VIEW = "uc_view",
    UC_MATERIALIZED_VIEW = "uc_materialized_view",
    UC_STREAMING_TABLE = "uc_streaming_table",
    UC_VOLUME = "uc_volume",
    UC_VOLUME_FILE = "uc_volume_file",
    
    // -------------------------------------------------------------------------
    // Unity Catalog / Databricks - Compute Assets
    // -------------------------------------------------------------------------
    UC_FUNCTION = "uc_function",
    UC_MODEL = "uc_model",
    UC_NOTEBOOK = "uc_notebook",
    UC_JOB = "uc_job",
    UC_PIPELINE = "uc_pipeline", // DLT / Spark Declarative Pipelines (SDP)
    
    // -------------------------------------------------------------------------
    // Unity Catalog / Databricks - Semantic Assets
    // -------------------------------------------------------------------------
    UC_METRIC = "uc_metric", // Unity Catalog metrics (AI/BI)
    
    // -------------------------------------------------------------------------
    // Snowflake - Data Assets
    // -------------------------------------------------------------------------
    SNOWFLAKE_TABLE = "snowflake_table",
    SNOWFLAKE_VIEW = "snowflake_view",
    SNOWFLAKE_MATERIALIZED_VIEW = "snowflake_materialized_view",
    SNOWFLAKE_STREAM = "snowflake_stream",
    SNOWFLAKE_STAGE = "snowflake_stage",
    
    // -------------------------------------------------------------------------
    // Snowflake - Compute Assets
    // -------------------------------------------------------------------------
    SNOWFLAKE_FUNCTION = "snowflake_function",
    SNOWFLAKE_PROCEDURE = "snowflake_procedure",
    SNOWFLAKE_TASK = "snowflake_task",
    
    // -------------------------------------------------------------------------
    // BigQuery - Data Assets
    // -------------------------------------------------------------------------
    BQ_TABLE = "bq_table",
    BQ_VIEW = "bq_view",
    BQ_MATERIALIZED_VIEW = "bq_materialized_view",
    BQ_EXTERNAL_TABLE = "bq_external_table",
    
    // -------------------------------------------------------------------------
    // BigQuery - Compute Assets
    // -------------------------------------------------------------------------
    BQ_ROUTINE = "bq_routine",
    BQ_MODEL = "bq_model",
    
    // -------------------------------------------------------------------------
    // Kafka - Data Assets
    // -------------------------------------------------------------------------
    KAFKA_TOPIC = "kafka_topic",
    KAFKA_SCHEMA = "kafka_schema", // Schema Registry schemas
    
    // -------------------------------------------------------------------------
    // PowerBI - Visualization & Semantic Assets
    // -------------------------------------------------------------------------
    POWERBI_DATASET = "powerbi_dataset",
    POWERBI_SEMANTIC_MODEL = "powerbi_semantic_model",
    POWERBI_DASHBOARD = "powerbi_dashboard",
    POWERBI_REPORT = "powerbi_report",
    POWERBI_DATAFLOW = "powerbi_dataflow",
    
    // -------------------------------------------------------------------------
    // Cloud Storage - Storage Assets
    // -------------------------------------------------------------------------
    S3_BUCKET = "s3_bucket",
    S3_OBJECT = "s3_object",
    ADLS_CONTAINER = "adls_container",
    ADLS_PATH = "adls_path",
    GCS_BUCKET = "gcs_bucket",
    GCS_OBJECT = "gcs_object",
    
    // -------------------------------------------------------------------------
    // API & External - Other Assets
    // -------------------------------------------------------------------------
    EXTERNAL_API = "external_api",
    EXTERNAL_DATABASE = "external_database",
    
    // -------------------------------------------------------------------------
    // Generic / Unknown
    // -------------------------------------------------------------------------
    GENERIC = "generic",
    UNKNOWN = "unknown",
}

// ============================================================================
// Asset Type Metadata
// ============================================================================

/**
 * Mapping of asset types to their categories.
 */
export const ASSET_TYPE_CATEGORIES: Record<UnifiedAssetType, AssetCategory> = {
    // UC Data
    [UnifiedAssetType.UC_TABLE]: AssetCategory.DATA,
    [UnifiedAssetType.UC_VIEW]: AssetCategory.DATA,
    [UnifiedAssetType.UC_MATERIALIZED_VIEW]: AssetCategory.DATA,
    [UnifiedAssetType.UC_STREAMING_TABLE]: AssetCategory.DATA,
    [UnifiedAssetType.UC_VOLUME]: AssetCategory.STORAGE,
    [UnifiedAssetType.UC_VOLUME_FILE]: AssetCategory.STORAGE,
    // UC Compute
    [UnifiedAssetType.UC_FUNCTION]: AssetCategory.COMPUTE,
    [UnifiedAssetType.UC_MODEL]: AssetCategory.COMPUTE,
    [UnifiedAssetType.UC_NOTEBOOK]: AssetCategory.COMPUTE,
    [UnifiedAssetType.UC_JOB]: AssetCategory.COMPUTE,
    [UnifiedAssetType.UC_PIPELINE]: AssetCategory.COMPUTE,
    // UC Semantic
    [UnifiedAssetType.UC_METRIC]: AssetCategory.SEMANTIC,
    // Snowflake Data
    [UnifiedAssetType.SNOWFLAKE_TABLE]: AssetCategory.DATA,
    [UnifiedAssetType.SNOWFLAKE_VIEW]: AssetCategory.DATA,
    [UnifiedAssetType.SNOWFLAKE_MATERIALIZED_VIEW]: AssetCategory.DATA,
    [UnifiedAssetType.SNOWFLAKE_STREAM]: AssetCategory.DATA,
    [UnifiedAssetType.SNOWFLAKE_STAGE]: AssetCategory.STORAGE,
    // Snowflake Compute
    [UnifiedAssetType.SNOWFLAKE_FUNCTION]: AssetCategory.COMPUTE,
    [UnifiedAssetType.SNOWFLAKE_PROCEDURE]: AssetCategory.COMPUTE,
    [UnifiedAssetType.SNOWFLAKE_TASK]: AssetCategory.COMPUTE,
    // BigQuery Data
    [UnifiedAssetType.BQ_TABLE]: AssetCategory.DATA,
    [UnifiedAssetType.BQ_VIEW]: AssetCategory.DATA,
    [UnifiedAssetType.BQ_MATERIALIZED_VIEW]: AssetCategory.DATA,
    [UnifiedAssetType.BQ_EXTERNAL_TABLE]: AssetCategory.DATA,
    // BigQuery Compute
    [UnifiedAssetType.BQ_ROUTINE]: AssetCategory.COMPUTE,
    [UnifiedAssetType.BQ_MODEL]: AssetCategory.COMPUTE,
    // Kafka
    [UnifiedAssetType.KAFKA_TOPIC]: AssetCategory.DATA,
    [UnifiedAssetType.KAFKA_SCHEMA]: AssetCategory.DATA,
    // PowerBI
    [UnifiedAssetType.POWERBI_DATASET]: AssetCategory.DATA,
    [UnifiedAssetType.POWERBI_SEMANTIC_MODEL]: AssetCategory.SEMANTIC,
    [UnifiedAssetType.POWERBI_DASHBOARD]: AssetCategory.VISUALIZATION,
    [UnifiedAssetType.POWERBI_REPORT]: AssetCategory.VISUALIZATION,
    [UnifiedAssetType.POWERBI_DATAFLOW]: AssetCategory.DATA,
    // Cloud Storage
    [UnifiedAssetType.S3_BUCKET]: AssetCategory.STORAGE,
    [UnifiedAssetType.S3_OBJECT]: AssetCategory.STORAGE,
    [UnifiedAssetType.ADLS_CONTAINER]: AssetCategory.STORAGE,
    [UnifiedAssetType.ADLS_PATH]: AssetCategory.STORAGE,
    [UnifiedAssetType.GCS_BUCKET]: AssetCategory.STORAGE,
    [UnifiedAssetType.GCS_OBJECT]: AssetCategory.STORAGE,
    // External
    [UnifiedAssetType.EXTERNAL_API]: AssetCategory.OTHER,
    [UnifiedAssetType.EXTERNAL_DATABASE]: AssetCategory.DATA,
    // Generic
    [UnifiedAssetType.GENERIC]: AssetCategory.OTHER,
    [UnifiedAssetType.UNKNOWN]: AssetCategory.OTHER,
};

/**
 * Asset types that support schema (columns/fields).
 */
export const SCHEMA_SUPPORTING_TYPES = new Set<UnifiedAssetType>([
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
    UnifiedAssetType.KAFKA_TOPIC, // If using Schema Registry
    UnifiedAssetType.POWERBI_DATASET,
    UnifiedAssetType.POWERBI_SEMANTIC_MODEL,
]);

/**
 * Connector types for different platforms.
 */
export type ConnectorType = "databricks" | "bigquery" | "snowflake" | "kafka" | "powerbi" | "s3" | "custom";

/**
 * Mapping of connector types to their supported asset types.
 */
export const CONNECTOR_ASSET_TYPES: Record<ConnectorType, UnifiedAssetType[]> = {
    databricks: [
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
    bigquery: [
        UnifiedAssetType.BQ_TABLE,
        UnifiedAssetType.BQ_VIEW,
        UnifiedAssetType.BQ_MATERIALIZED_VIEW,
        UnifiedAssetType.BQ_EXTERNAL_TABLE,
        UnifiedAssetType.BQ_ROUTINE,
        UnifiedAssetType.BQ_MODEL,
    ],
    snowflake: [
        UnifiedAssetType.SNOWFLAKE_TABLE,
        UnifiedAssetType.SNOWFLAKE_VIEW,
        UnifiedAssetType.SNOWFLAKE_MATERIALIZED_VIEW,
        UnifiedAssetType.SNOWFLAKE_STREAM,
        UnifiedAssetType.SNOWFLAKE_STAGE,
        UnifiedAssetType.SNOWFLAKE_FUNCTION,
        UnifiedAssetType.SNOWFLAKE_PROCEDURE,
        UnifiedAssetType.SNOWFLAKE_TASK,
    ],
    kafka: [
        UnifiedAssetType.KAFKA_TOPIC,
        UnifiedAssetType.KAFKA_SCHEMA,
    ],
    powerbi: [
        UnifiedAssetType.POWERBI_DATASET,
        UnifiedAssetType.POWERBI_SEMANTIC_MODEL,
        UnifiedAssetType.POWERBI_DASHBOARD,
        UnifiedAssetType.POWERBI_REPORT,
        UnifiedAssetType.POWERBI_DATAFLOW,
    ],
    s3: [
        UnifiedAssetType.S3_BUCKET,
        UnifiedAssetType.S3_OBJECT,
    ],
    custom: [
        UnifiedAssetType.GENERIC,
        UnifiedAssetType.EXTERNAL_API,
        UnifiedAssetType.EXTERNAL_DATABASE,
    ],
};

// ============================================================================
// Helper Functions
// ============================================================================

/**
 * Get the category for a given asset type.
 */
export function getAssetCategory(assetType: UnifiedAssetType): AssetCategory {
    return ASSET_TYPE_CATEGORIES[assetType] || AssetCategory.OTHER;
}

/**
 * Check if an asset type supports schema (columns/fields).
 */
export function supportsSchema(assetType: UnifiedAssetType): boolean {
    return SCHEMA_SUPPORTING_TYPES.has(assetType);
}

/**
 * Get the connector type for a given asset type.
 */
export function getConnectorTypeForAsset(assetType: UnifiedAssetType): ConnectorType | null {
    for (const [connectorType, assetTypes] of Object.entries(CONNECTOR_ASSET_TYPES)) {
        if (assetTypes.includes(assetType)) {
            return connectorType as ConnectorType;
        }
    }
    return null;
}

/**
 * Get a display name for an asset type.
 */
export function getAssetTypeDisplayName(assetType: UnifiedAssetType): string {
    const displayNames: Record<UnifiedAssetType, string> = {
        // Unity Catalog
        [UnifiedAssetType.UC_TABLE]: "Unity Catalog Table",
        [UnifiedAssetType.UC_VIEW]: "Unity Catalog View",
        [UnifiedAssetType.UC_MATERIALIZED_VIEW]: "Unity Catalog Materialized View",
        [UnifiedAssetType.UC_STREAMING_TABLE]: "Unity Catalog Streaming Table",
        [UnifiedAssetType.UC_VOLUME]: "Unity Catalog Volume",
        [UnifiedAssetType.UC_VOLUME_FILE]: "Unity Catalog Volume File",
        [UnifiedAssetType.UC_FUNCTION]: "Unity Catalog Function",
        [UnifiedAssetType.UC_MODEL]: "Unity Catalog Model",
        [UnifiedAssetType.UC_NOTEBOOK]: "Notebook",
        [UnifiedAssetType.UC_JOB]: "Job",
        [UnifiedAssetType.UC_PIPELINE]: "Declarative Pipeline (DLT/SDP)",
        [UnifiedAssetType.UC_METRIC]: "Unity Catalog Metric",
        // Snowflake
        [UnifiedAssetType.SNOWFLAKE_TABLE]: "Snowflake Table",
        [UnifiedAssetType.SNOWFLAKE_VIEW]: "Snowflake View",
        [UnifiedAssetType.SNOWFLAKE_MATERIALIZED_VIEW]: "Snowflake MV",
        [UnifiedAssetType.SNOWFLAKE_STREAM]: "Snowflake Stream",
        [UnifiedAssetType.SNOWFLAKE_STAGE]: "Snowflake Stage",
        [UnifiedAssetType.SNOWFLAKE_FUNCTION]: "Snowflake Function",
        [UnifiedAssetType.SNOWFLAKE_PROCEDURE]: "Snowflake Procedure",
        [UnifiedAssetType.SNOWFLAKE_TASK]: "Snowflake Task",
        // BigQuery
        [UnifiedAssetType.BQ_TABLE]: "BigQuery Table",
        [UnifiedAssetType.BQ_VIEW]: "BigQuery View",
        [UnifiedAssetType.BQ_MATERIALIZED_VIEW]: "BigQuery Materialized View",
        [UnifiedAssetType.BQ_EXTERNAL_TABLE]: "BigQuery External Table",
        [UnifiedAssetType.BQ_ROUTINE]: "BigQuery Routine",
        [UnifiedAssetType.BQ_MODEL]: "BigQuery Model",
        // Kafka
        [UnifiedAssetType.KAFKA_TOPIC]: "Kafka Topic",
        [UnifiedAssetType.KAFKA_SCHEMA]: "Kafka Schema",
        // PowerBI
        [UnifiedAssetType.POWERBI_DATASET]: "Power BI Dataset",
        [UnifiedAssetType.POWERBI_SEMANTIC_MODEL]: "Power BI Semantic Model",
        [UnifiedAssetType.POWERBI_DASHBOARD]: "Power BI Dashboard",
        [UnifiedAssetType.POWERBI_REPORT]: "Power BI Report",
        [UnifiedAssetType.POWERBI_DATAFLOW]: "Power BI Dataflow",
        // Storage
        [UnifiedAssetType.S3_BUCKET]: "S3 Bucket",
        [UnifiedAssetType.S3_OBJECT]: "S3 Object",
        [UnifiedAssetType.ADLS_CONTAINER]: "ADLS Container",
        [UnifiedAssetType.ADLS_PATH]: "ADLS Path",
        [UnifiedAssetType.GCS_BUCKET]: "GCS Bucket",
        [UnifiedAssetType.GCS_OBJECT]: "GCS Object",
        // External
        [UnifiedAssetType.EXTERNAL_API]: "External API",
        [UnifiedAssetType.EXTERNAL_DATABASE]: "External Database",
        // Generic
        [UnifiedAssetType.GENERIC]: "Generic",
        [UnifiedAssetType.UNKNOWN]: "Unknown",
    };
    return displayNames[assetType] || assetType;
}

/**
 * Get an icon name for an asset type (for use with icon libraries).
 */
export function getAssetTypeIcon(assetType: UnifiedAssetType): string {
    const iconMap: Partial<Record<UnifiedAssetType, string>> = {
        // UC
        [UnifiedAssetType.UC_TABLE]: "table",
        [UnifiedAssetType.UC_VIEW]: "eye",
        [UnifiedAssetType.UC_MATERIALIZED_VIEW]: "layers",
        [UnifiedAssetType.UC_STREAMING_TABLE]: "activity",
        [UnifiedAssetType.UC_VOLUME]: "hard-drive",
        [UnifiedAssetType.UC_FUNCTION]: "code",
        [UnifiedAssetType.UC_MODEL]: "brain",
        [UnifiedAssetType.UC_NOTEBOOK]: "file-text",
        [UnifiedAssetType.UC_JOB]: "play-circle",
        [UnifiedAssetType.UC_METRIC]: "bar-chart-2",
        // Snowflake
        [UnifiedAssetType.SNOWFLAKE_TABLE]: "table",
        [UnifiedAssetType.SNOWFLAKE_VIEW]: "eye",
        // Kafka
        [UnifiedAssetType.KAFKA_TOPIC]: "message-square",
        // PowerBI
        [UnifiedAssetType.POWERBI_DASHBOARD]: "layout-dashboard",
        [UnifiedAssetType.POWERBI_REPORT]: "file-bar-chart",
        [UnifiedAssetType.POWERBI_SEMANTIC_MODEL]: "box",
    };
    return iconMap[assetType] || "file";
}

// ============================================================================
// Asset Info Interfaces
// ============================================================================

/**
 * Basic information about an asset, returned by list operations.
 */
export interface AssetInfo {
    identifier: string;
    name: string;
    asset_type: UnifiedAssetType;
    connector_type: ConnectorType;
    description?: string | null;
    path?: string | null;
    url?: string | null;
    catalog?: string | null;
    schema?: string | null;
}

/**
 * Column information for assets with schema.
 */
export interface ColumnInfo {
    name: string;
    data_type: string;
    logical_type?: string | null;
    nullable: boolean;
    description?: string | null;
    is_primary_key: boolean;
    is_partition_key: boolean;
    default_value?: string | null;
    tags: Record<string, string>;
    properties: Record<string, unknown>;
}

/**
 * Schema information for assets that have columnar structure.
 */
export interface SchemaInfo {
    columns: ColumnInfo[];
    primary_key?: string[] | null;
    partition_columns?: string[] | null;
    clustering_columns?: string[] | null;
    schema_version?: string | null;
}

/**
 * Ownership information for an asset.
 */
export interface AssetOwnership {
    owner?: string | null;
    owner_email?: string | null;
    steward?: string | null;
    team?: string | null;
}

/**
 * Statistics about an asset.
 */
export interface AssetStatistics {
    row_count?: number | null;
    size_bytes?: number | null;
    partition_count?: number | null;
    file_count?: number | null;
    last_modified?: string | null;
    last_accessed?: string | null;
}

/**
 * Full metadata for an asset.
 */
export interface AssetMetadata extends AssetInfo {
    comment?: string | null;
    location?: string | null;
    schema_info?: SchemaInfo | null;
    ownership?: AssetOwnership | null;
    statistics?: AssetStatistics | null;
    tags: Record<string, string>;
    properties: Record<string, unknown>;
    created_at?: string | null;
    updated_at?: string | null;
    created_by?: string | null;
    updated_by?: string | null;
    status?: string | null;
    exists: boolean;
    validation_message?: string | null;
}

/**
 * Result of validating an asset's existence.
 */
export interface AssetValidationResult {
    identifier: string;
    exists: boolean;
    validated: boolean;
    asset_type?: UnifiedAssetType | null;
    message?: string | null;
    details: Record<string, unknown>;
}

/**
 * Sample data from an asset.
 */
export interface SampleData {
    columns: string[];
    rows: unknown[][];
    total_rows?: number | null;
    sample_size: number;
    truncated: boolean;
}

