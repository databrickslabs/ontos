export interface BrowseNode {
  name: string;
  node_type: string;
  path: string;
  has_children: boolean;
  description: string | null;
  asset_type: string | null;
  connector_type: string | null;
}

export interface BrowseResponse {
  connection_id: string;
  path: string | null;
  nodes: BrowseNode[];
  error?: string | null;
  error_detail?: string | null;
  truncated?: boolean;
  truncated_at?: number | null;
}

export type ImportDepth = 'selected_only' | 'one_level' | 'full_recursive';

export interface ImportRequest {
  connection_id: string;
  selected_paths: string[];
  depth: ImportDepth;
  dry_run?: boolean;
  excluded_paths?: string[];
  path_mappings?: Record<string, string>;
}

export interface ImportPreviewItem {
  path: string;
  name: string;
  asset_type: string;
  will_create: boolean;
  existing_asset_id: string | null;
  parent_path: string | null;
  is_ancestor: boolean;
}

export interface ImportResultItem {
  path: string;
  name: string;
  asset_type: string;
  action: 'created' | 'skipped' | 'error';
  asset_id: string | null;
  error: string | null;
  parent_path: string | null;
}

export interface ImportResult {
  created: number;
  skipped: number;
  errors: number;
  error_messages: string[];
  items: ImportResultItem[];
  system_asset_id: string | null;
}

export type SchemaImportRunStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled';

export interface StartImportRunResponse {
  run_id: string;
  status: SchemaImportRunStatus;
}

export interface SchemaImportRunDetail {
  id: string;
  status: SchemaImportRunStatus;
  progress_message?: string | null;
  error?: string | null;
  connection_id?: string | null;
  total_items?: number | null;
  processed_items: number;
  created_count: number;
  skipped_count: number;
  error_count: number;
  result?: ImportResult | null;
  created_at?: string | null;
  updated_at?: string | null;
  completed_at?: string | null;
}
