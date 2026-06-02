// Mirrors src/backend/src/models/term_mappings.py — keep these in lock-step.
// See PRD #469 for the user-facing contract these shapes back.

export type RunStatus =
  | 'pending'
  | 'suggesting'
  | 'suggested'
  | 'applying'
  | 'applied'
  | 'undone'
  | 'failed';

export type SuggestionStatus =
  | 'pending'
  | 'accepted'
  | 'rejected'
  | 'applied'
  | 'superseded'
  | 'needs_clarification';

export type SuggestionKind = 'entity_assignment' | 'attribute_assignment';

export type TermMappingEngine = 'heuristic' | 'llm_judge';

export type TermMappingTargetEntityType =
  | 'data_product'
  | 'data_contract'
  | 'data_contract_schema'
  | 'data_contract_property'
  | 'dataset'
  | 'asset';

export interface RunTargetFilter {
  entity_types?: TermMappingTargetEntityType[];
  domain_ids?: string[];
  contract_ids?: string[];
  product_ids?: string[];
  asset_type_names?: string[];
  limit?: number;
}

export interface RunCreatePayload {
  /** If omitted, backend defaults to every enabled urn:semantic-model:* context. */
  ontology_contexts?: string[];
  /** Opt-in shipped taxonomies (e.g. urn:taxonomy:databricks_ontology). */
  include_shipped?: string[];
  target_filter?: RunTargetFilter;
  engines?: TermMappingEngine[];
  comment?: string;
}

export interface RunStats {
  targets?: number;
  suggestions_total?: number;
  suggestions_pending?: number;
  suggestions_accepted?: number;
  suggestions_rejected?: number;
  suggestions_auto_apply?: number;
  links_created?: number;
  links_skipped?: number;
  // Backend may add llm_calls/llm_tokens_in/out once Phase 4 lands.
  [key: string]: unknown;
}

export interface RunSummary {
  id: string;
  status: RunStatus;
  comment?: string | null;
  stats: RunStats;
  created_by?: string | null;
  created_at: string;
  finished_at?: string | null;
  applied_at?: string | null;
}

export interface Run extends RunSummary {
  ontology_contexts: string[];
  include_shipped: string[];
  target_filter: RunTargetFilter;
  engines: string[];
  error?: string | null;
  applied_link_ids: string[];
  started_at?: string | null;
  undone_at?: string | null;
}

export interface Suggestion {
  id: string;
  run_id: string;
  source_entity_type: string;
  source_entity_id: string;
  source_label?: string | null;
  suggestion_kind: SuggestionKind;
  target_concept_iri: string;
  target_concept_label?: string | null;
  confidence: number;
  reason: string;
  auto_apply: boolean;
  engine: TermMappingEngine;
  engine_metadata?: Record<string, unknown> | null;
  status: SuggestionStatus;
  decided_by?: string | null;
  decided_at?: string | null;
  custom_iri?: string | null;
  applied_link_id?: string | null;
  warnings?: string[] | null;
  review_request_id?: string | null;
  reviewed_asset_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface SuggestionDecision {
  id: string;
  decision: 'accept' | 'reject' | 'clarify';
  custom_iri?: string;
  comment?: string;
}

export interface SuggestionDecisionBatch {
  decisions: SuggestionDecision[];
}

export interface SuggestionDecisionResult {
  accepted: number;
  rejected: number;
  skipped: number;
  errors: string[];
}

export interface ApplyResult {
  run_id: string;
  links_created: number;
  links_skipped: number;
  errors: string[];
}

export interface UndoResult {
  run_id: string;
  links_removed: number;
  suggestions_reverted: number;
  errors: string[];
}

export interface PendingSuggestionCount {
  entity_type: string;
  entity_id: string;
  pending: number;
  auto_apply: number;
}

// ---------- Review spawn ----------

export interface GenerateReviewRequest {
  reviewer_email: string;
  requester_email?: string;
  notes?: string;
  include_accepted?: boolean;
}

export interface GenerateReviewResponse {
  run_id: string;
  review_request_id: string;
  suggestion_count: number;
  message: string;
}

// ---------- Inline suggester ----------

export interface InlineSuggestRequest {
  source_entity_type: TermMappingTargetEntityType;
  source_entity_id: string;
  ontology_contexts?: string[];
  include_shipped?: string[];
  limit?: number;
}

export interface InlineSuggestion {
  target_concept_iri: string;
  target_concept_label?: string | null;
  confidence: number;
  reason: string;
  auto_apply: boolean;
}

export interface InlineSuggestResponse {
  source_entity_type: string;
  source_entity_id: string;
  suggestions: InlineSuggestion[];
}

// ---------- UI helpers ----------

export const SHIPPED_OPT_IN_CONTEXTS: { value: string; label: string }[] = [
  { value: 'urn:taxonomy:databricks_ontology', label: 'Databricks ontology' },
  { value: 'urn:taxonomy:odcs-ontology', label: 'ODCS ontology' },
];

export const TARGET_ENTITY_TYPE_LABELS: Record<TermMappingTargetEntityType, string> = {
  asset: 'Asset / Column',
  data_contract: 'Data Contract',
  data_contract_schema: 'Contract Schema',
  data_contract_property: 'Contract Property',
  data_product: 'Data Product',
  dataset: 'Dataset (legacy)',
};

/** Confidence bucket for UI badge coloring. Mirrors backend AUTO_ACCEPT/REJECT. */
export type ConfidenceBucket = 'high' | 'medium' | 'low';

export function bucketConfidence(c: number): ConfidenceBucket {
  if (c >= 0.9) return 'high';
  if (c > 0.4) return 'medium';
  return 'low';
}
