// Corresponds to api/models/data_asset_reviews.py
import type { EntitySemanticLink } from '@/types/semantic-link';

// --- Enums --- //
export enum ReviewRequestStatus {
    QUEUED = "queued",
    IN_REVIEW = "in_review",
    APPROVED = "approved",
    NEEDS_REVIEW = "needs_review",
    DENIED = "denied",
    CANCELLED = "cancelled",
}

export enum ReviewedAssetStatus {
    PENDING = "pending",
    APPROVED = "approved",
    REJECTED = "rejected",
    NEEDS_CLARIFICATION = "needs_clarification",
}

/**
 * Asset types for data asset reviews.
 * 
 * These are simplified types for the review workflow. For detailed
 * platform-specific types, see UnifiedAssetType in assets.ts.
 */
export enum AssetType {
    // Unity Catalog / Databricks assets
    TABLE = "table",
    VIEW = "view",
    FUNCTION = "function",
    MODEL = "model",
    VOLUME = "volume",
    NOTEBOOK = "notebook",
    JOB = "job",
    PIPELINE = "pipeline",
    METRIC = "metric", // UC Metrics (AI/BI)
    
    // Cross-platform streaming
    STREAM = "stream",
    TOPIC = "topic", // Kafka topics
    
    // Visualization assets
    DASHBOARD = "dashboard",
    REPORT = "report",
    SEMANTIC_MODEL = "semantic_model", // PowerBI semantic models
    
    // Application entities
    DATA_CONTRACT = "data_contract",
    DATA_PRODUCT = "data_product",
    
    // MDM assets
    MDM_MATCH = "mdm_match",

    // Term-mapping suggestions (one ReviewedAsset == one MappingSuggestionDb)
    CONCEPT_MAPPING_SUGGESTION = "concept_mapping_suggestion",

    // Authority Relation reviews (asset_fqn = authority-relation://{id})
    AUTHORITY_RELATION = "authority_relation",
    // Knowledge system assets
    KNOWLEDGE_CONCEPT = "knowledge_concept",
    CONCEPT_CHANGESET = "concept_changeset",
    KNOWLEDGE_COLLECTION = "knowledge_collection",

    // Generic/external
    EXTERNAL = "external",
    OTHER = "other",
}

// --- Interfaces --- //

// Interface for an asset being reviewed
export interface ReviewedAsset {
    id?: string;
    asset_fqn: string;
    asset_type: AssetType;
    status: ReviewedAssetStatus;
    comments?: string | null;
    updated_at: string; // ISO date string
}

// Interface for creating a new review request
export interface DataAssetReviewRequestCreate {
    requester_email: string;
    reviewer_email: string;
    asset_fqns: string[];
    title?: string | null;
    notes?: string | null;
}

// Interface for the full data asset review request
export interface DataAssetReviewRequest {
    id: string;
    requester_email: string;
    reviewer_email: string;
    /** Human-readable title; backend always returns a populated value (derived if not user-set). */
    title: string;
    status: ReviewRequestStatus;
    notes?: string | null;
    created_at: string; // ISO date string
    updated_at: string; // ISO date string
    assets: ReviewedAsset[];
}

// Interface for updating the overall request status
export interface DataAssetReviewRequestUpdateStatus {
    status: ReviewRequestStatus;
    notes?: string | null;
}

// Interface for partial updates (PATCH) - title and/or notes
export interface DataAssetReviewRequestUpdate {
    title?: string | null;
    notes?: string | null;
}

// Interface for updating a specific asset's status
export interface ReviewedAssetUpdate {
    status: ReviewedAssetStatus;
    comments?: string | null;
}

// --- Types for Dropdowns/Distinct Values (if needed) --- //
export type ReviewStatus = ReviewRequestStatus | ReviewedAssetStatus;

// Type for Catalog items (similar to Catalog Commander)
export interface CatalogItem {
  id: string;       // FQN (e.g., catalog.schema.table)
  name: string;     // Display name (e.g., table name)
  type: 'catalog' | 'schema' | 'table' | 'view' | 'function' | 'model' | 'volume' | 'metric'; // Extended for multi-asset support
  children?: CatalogItem[];
  hasChildren?: boolean;
}

// Type for Asset Definition (plain text)
export type AssetDefinition = string;

/** A dimension or measure of a Unity Catalog metric view. */
export interface MetricViewField {
    name: string;
    expr?: string | null;
    display_name?: string | null;
    comment?: string | null;
    /** A measure's window, only when its definition sets one */
    window?: MetricViewWindow[];
}

/** One entry of a measure's `window`. */
export interface MetricViewWindow {
    order?: string | null;
    range?: string | null;
    semiadditive?: string | null;
    offset?: string | number | null;
}

/** The definition a metric view's drift is checked against. */
export interface MetricViewBaseline {
    digest: string;
    approved_at?: string | null; // null: recorded from the first definition read, not approved
    request_id?: string | null;
    recorded_at?: string | null;
}

export type MetricViewDriftState = 'in_sync' | 'drifted' | 'unknown';

export interface MetricViewDrift {
    state: MetricViewDriftState;
    current_digest?: string | null; // null when the definition could not be parsed
    last_checked_at?: string | null;
}

export type MetricViewRefreshStatus = 'succeeded' | 'failed' | 'running' | 'canceled' | 'unknown';

/** The refresh state of a materialized metric view (its pipeline's latest update). */
export interface MetricViewRefresh {
    status: MetricViewRefreshStatus;
    schedule?: string | null;
    pipeline_id?: string | null;
    pipeline_url?: string | null;
    pipeline_state?: string | null;
    health?: string | null;
    latest_update_id?: string | null;
    latest_update_state?: string | null;
    latest_update_at?: string | null; // when the latest update started
}

/** The concept links of one dimension or measure (`uc_column`, `catalog.schema.view.field`). */
export interface MetricViewFieldLinks {
    name: string;
    kind?: 'dimension' | 'measure' | null; // null: no longer in the definition
    entity_id: string;
    links: EntitySemanticLink[];
}

/** A metric view's concept links: the view's own (`uc_table`) and each field's. */
export interface MetricViewLinks {
    view_entity_id: string;
    view_links: EntitySemanticLink[];
    fields: MetricViewFieldLinks[];
    removed_fields: MetricViewFieldLinks[]; // Fields with links, no longer in the definition
}

/**
 * GET /api/data-asset-reviews/{id}/assets/{id}/metric-view and
 * GET /api/assets/{id}/metric-view
 */
export interface MetricViewDefinition {
    definition: string; // The metric view's YAML
    metric_view: {
        version?: string | null;
        source?: string | null;
        filter?: string | null;
        joins: {
            name?: string | null;
            source?: string | null;
            on?: string | null;
            using?: string[] | null;
            cardinality?: string | null; // only when the definition sets it
        }[];
        dimensions: MetricViewField[];
        measures: MetricViewField[];
        materialization?: {
            schedule?: string | null;
            mode?: string | null;
            materialized_views: { name?: string | null; type?: string | null }[];
        } | null;
        parameters?: { name: string; data_type?: string | null; default?: unknown }[];
    } | null; // null when the YAML could not be parsed
    links?: MetricViewLinks | null;
    // GET /api/assets/{id}/metric-view only
    baseline?: MetricViewBaseline | null;
    drift?: MetricViewDrift | null;
    refresh?: MetricViewRefresh | null; // null when the view isn't materialized
}

// Type for Table Preview Data (reuse from Catalog Commander or define similarly)
export interface TablePreview {
  schema: Array<{ name: string; type: string; nullable: boolean }>;
  data: any[];
  total_rows?: number; // Optional based on backend capability
}

// --- LLM Analysis Types --- //
export interface AssetAnalysisResponse {
    request_id: string;
    asset_id: string;
    analysis_summary: string;
    model_used?: string | null;
    timestamp: string; // ISO date string
    // Security metadata for two-phased verification
    phase1_passed: boolean;
    render_as_markdown: boolean;
    // Code of a notice shown in the user's language (e.g. llm_analysis_refused)
    notice_code?: string | null;
} 