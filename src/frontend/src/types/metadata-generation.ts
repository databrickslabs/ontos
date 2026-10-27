// Metadata Generation (dbxmetagen) — mirrors src/backend/src/models/metadata_generation.py

export type GenerationRunStatus = 'pending' | 'running' | 'ingesting' | 'completed' | 'failed' | 'cancelled';

export type SuggestionStatus =
  | 'pending'
  | 'accepted'
  | 'rejected'
  | 'applied'
  | 'conflict'
  | 'not_applicable'
  | 'superseded';

export type CommentStyle = 'concise' | 'standard' | 'detailed';

export interface SelectionItem {
  type: 'catalog' | 'schema' | 'table';
  fqn: string;
}

export interface StartRunRequest {
  selection: SelectionItem[];
  comment_style: CommentStyle;
  model?: string | null;
  regenerate_existing: boolean;
  auto_submit: boolean;
}

export interface StartRunResponse {
  run_id: string;
  status: GenerationRunStatus;
}

export interface GenerationRunSummary {
  run_id: string;
  user_id: string;
  status: GenerationRunStatus;
  progress_message?: string | null;
  error?: string | null;
  selection: SelectionItem[];
  options: {
    comment_style?: CommentStyle;
    model?: string;
    regenerate_existing?: boolean;
    auto_submit?: boolean;
  };
  job_run_id?: string | null;
  suggestion_count: number;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export type SuggestionCounts = Record<SuggestionStatus, number>;

export interface GenerationRunDetail extends GenerationRunSummary {
  counts: SuggestionCounts;
}

export interface DescriptionSuggestion {
  id: string;
  run_id: string;
  kind: string;
  object_type: 'table' | 'view' | 'column';
  table_fqn: string;
  column_name?: string | null;
  base_text?: string | null;
  proposed_text: string;
  edited_text?: string | null;
  status: SuggestionStatus;
  review_request_id?: string | null;
  decided_by?: string | null;
  decided_at?: string | null;
  applied_by?: string | null;
  applied_at?: string | null;
  error?: string | null;
}

export interface SuggestionListResponse {
  suggestions: DescriptionSuggestion[];
  total: number;
}

export const TERMINAL_RUN_STATUSES: GenerationRunStatus[] = ['completed', 'failed', 'cancelled'];
