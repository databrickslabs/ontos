/**
 * Data Catalog / Data Dictionary Types
 * 
 * TypeScript types for the Data Dictionary feature,
 * mirroring the backend Pydantic models.
 */

// =============================================================================
// Enums
// =============================================================================

export type LineageDirection = 'upstream' | 'downstream' | 'both';

export type AssetType = 'table' | 'view' | 'external' | 'notebook' | 'job' | 'dashboard';

// =============================================================================
// Column & Table Types
// =============================================================================

/**
 * Single row in the Data Dictionary view.
 * Represents a column with its table/contract context.
 */
export interface ColumnDictionaryEntry {
  /** Technical column name (e.g., 'src_issuer_id') */
  column_name: string;
  /** Business-friendly label if available */
  column_label: string | null;
  /** Data type (e.g., 'STRING', 'INT') */
  column_type: string;
  /** Column description/comment */
  description: string | null;
  /** Whether column allows NULL values */
  nullable: boolean;
  /** Column ordinal position in table */
  position: number;
  /** Whether column is part of primary key */
  is_primary_key?: boolean;
  /** Data classification (e.g., PII, Confidential) */
  classification?: string | null;
  /** Short table/schema object name */
  table_name: string;
  /** Fully qualified name: contract.schema_object or catalog.schema.table */
  table_full_name: string;
  /** Schema/Contract name */
  schema_name: string;
  /** Catalog/Version */
  catalog_name: string;
  /** TABLE, VIEW, DATASET, or CONTRACT */
  table_type: string;
  /** Data source provenance: 'contract', 'asset', or 'both' */
  source: 'contract' | 'asset' | 'both';
  /** Source Asset ID when from Asset DB */
  asset_id?: string | null;
  /** Parent System name in asset hierarchy */
  system_name?: string | null;
  /** ID of the source Data Contract */
  contract_id?: string | null;
  /** Name of the source Data Contract */
  contract_name?: string | null;
  /** Version of the source Data Contract */
  contract_version?: string | null;
  /** Status of the source Data Contract */
  contract_status?: string | null;
  /** Business terms/concepts linked to this column */
  business_terms?: { iri: string; label?: string; type?: string }[];
}

/**
 * Column information within a table.
 */
export interface ColumnInfo {
  name: string;
  type_text: string;
  type_name?: string | null;
  position: number;
  nullable: boolean;
  comment?: string | null;
  partition_index?: number | null;
  mask?: Record<string, unknown> | null;
}

/**
 * Full table information with all columns.
 */
export interface TableInfo {
  /** catalog.schema.table */
  full_name: string;
  name: string;
  schema_name: string;
  catalog_name: string;
  /** MANAGED, EXTERNAL, or VIEW */
  table_type: string;
  owner?: string | null;
  comment?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  created_by?: string | null;
  updated_by?: string | null;
  storage_location?: string | null;
  data_source_format?: string | null;
  columns: ColumnInfo[];
  row_count?: number | null;
  size_bytes?: number | null;
  tags?: Record<string, string> | null;
}

/**
 * Lightweight table/schema object info for dropdown/list views.
 */
export interface TableListItem {
  full_name: string;
  name: string;
  schema_name: string;
  catalog_name: string;
  /** TABLE, VIEW, or CONTRACT */
  table_type: string;
  column_count: number;
  comment?: string | null;
  /** ID of the source Data Contract */
  contract_id?: string | null;
  /** Name of the source Data Contract */
  contract_name?: string | null;
  /** Version of the source Data Contract */
  contract_version?: string | null;
  /** Status of the source Data Contract */
  contract_status?: string | null;
}

// =============================================================================
// Response Types
// =============================================================================

/**
 * Response for the main Data Dictionary view.
 */
export interface DataDictionaryResponse {
  table_count: number;
  column_count: number;
  columns: ColumnDictionaryEntry[];
  offset: number;
  limit: number;
  has_more: boolean;
  table_filter?: string | null;
}

/**
 * Response for column search.
 */
export interface ColumnSearchResponse {
  query: string;
  total_count: number;
  columns: ColumnDictionaryEntry[];
  has_more: boolean;
  offset: number;
  limit: number;
  filters_applied: {
    catalog?: string | null;
    schema?: string | null;
    table?: string | null;
    asset_type?: string | null;
    system?: string | null;
  };
}

/**
 * Available filter values for the faceted filter UI.
 */
export interface HierarchyFilters {
  asset_types: string[];
  systems: string[];
  catalogs: string[];
  schemas: string[];
}

/**
 * Response for table dropdown list.
 */
export interface TableListResponse {
  tables: TableListItem[];
  total_count: number;
  total_column_count: number;
}

// =============================================================================
// Lineage Types
// =============================================================================

/**
 * Node in a lineage graph.
 */
export interface LineageNode {
  /** Unique node ID (usually FQN) */
  id: string;
  /** Display name */
  name: string;
  /** Asset type */
  type: AssetType;
  catalog?: string | null;
  schema?: string | null;
  owner?: string | null;
  comment?: string | null;
  /** For external nodes */
  external_system?: string | null;
  external_url?: string | null;
  /** Whether this is the queried node */
  is_root: boolean;
  /** Distance from root node */
  depth: number;
}

/**
 * Column-level mapping in lineage edge.
 */
export interface ColumnMapping {
  source_column: string;
  target_column: string;
  transformation?: string | null;
}

/**
 * Edge in a lineage graph.
 */
export interface LineageEdge {
  /** Source node ID */
  source: string;
  /** Target node ID */
  target: string;
  /** Optional column-level detail */
  column_mappings?: ColumnMapping[] | null;
  query_id?: string | null;
  created_at?: string | null;
}

/**
 * Complete lineage graph for visualization.
 */
export interface LineageGraph {
  nodes: LineageNode[];
  edges: LineageEdge[];
  /** ID of the queried node */
  root_node: string;
  direction: LineageDirection;
  upstream_count: number;
  downstream_count: number;
  external_count: number;
}

// =============================================================================
// Impact Analysis Types
// =============================================================================

/**
 * An asset impacted by a change.
 */
export interface ImpactedAsset {
  id: string;
  name: string;
  type: AssetType;
  full_name?: string | null;
  /** Path from source to this asset */
  impact_path: string[];
  /** Hops from source */
  distance: number;
  /** Affected columns (if column-level analysis) */
  affected_columns?: string[] | null;
  /** Owner for notification */
  owner?: string | null;
}

/**
 * Result of impact analysis for a table or column change.
 */
export interface ImpactAnalysis {
  /** Table being changed */
  source_table: string;
  /** Column being changed (if column-level) */
  source_column?: string | null;
  impacted_tables: ImpactedAsset[];
  impacted_views: ImpactedAsset[];
  impacted_external: ImpactedAsset[];
  total_impacted_count: number;
  max_depth: number;
  /** Owners to notify */
  affected_owners: string[];
}

