// Types for Sync Domains (#761) — bidirectional Ontos <-> Unity Catalog domain sync.
// Mirrors src/backend/src/models/domain_sync.py.

export type SyncDirection = 'import_from_uc' | 'export_to_uc';

export type SyncAction = 'create' | 'match' | 'skip' | 'error';

export interface DomainSyncNode {
  name: string;
  level: number; // 1 = root domain, 2 = subdomain, 3+ = too deep
  action: SyncAction;
  reason?: string | null;
  parent_name?: string | null;
  ontos_id?: string | null;
  uc_domain_id?: string | null;
}

export interface DomainSyncPreview {
  direction: SyncDirection;
  nodes: DomainSyncNode[];
  to_create: number;
  to_match: number;
  to_skip: number;
  warnings: string[];
}

export interface DomainSyncResult {
  direction: SyncDirection;
  created: number;
  matched: number;
  skipped: number;
  errors: number;
  error_messages: string[];
  nodes: DomainSyncNode[];
}

export interface ImportSyncRequest {
  target_root_id?: string | null;
}

export interface ExportSyncRequest {
  anchor_domain_id?: string | null;
}
