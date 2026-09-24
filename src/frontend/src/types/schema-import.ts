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
