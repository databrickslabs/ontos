import type { ImportDepth } from './schema-import';

/** A saved Schema Importer selection the Connector Sync job imports again on a schedule. */
export interface ConnectorSync {
  id: string;
  name: string;
  connection_id: string;
  selected_paths: string[];
  depth: ImportDepth;
  excluded_paths: string[];
  interval_minutes: number;
  retire_after_misses: number;
  enabled: boolean;
  last_run_id?: string | null;
  last_run_at?: string | null;
  /** completed | incomplete | failed */
  last_status?: string | null;
  last_complete_sync_at?: string | null;
  next_due_at?: string | null;
  created_by?: string | null;
  created_at?: string | null;
  /** Set when the scheduled job could not be installed or started. */
  job_warning?: string | null;
}

export interface ConnectorSyncCreate {
  name: string;
  connection_id: string;
  selected_paths: string[];
  depth: ImportDepth;
  excluded_paths: string[];
  interval_minutes: number;
  retire_after_misses: number;
}

/** Interval choices (minutes); the job runs hourly, so an hour is the shortest. */
export const SYNC_INTERVALS = [60, 1440, 10080] as const;
export const DEFAULT_SYNC_INTERVAL = 1440;
export const DEFAULT_RETIRE_AFTER = 3;
