// Corresponds to api/models/data_asset_reviews.py

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
} 