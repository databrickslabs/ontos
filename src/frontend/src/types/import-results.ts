// Mirrors the backend `BatchImportResult` (src/backend/src/models/import_results.py).
// One import operation may span several uploaded files, each holding a single
// entity or an array; every entity yields one ImportItemResult and the summary
// counters drive the truthful "N created, M skipped, K failed" report.

export type ImportItemStatus = 'created' | 'skipped' | 'failed';

export interface ImportItemResult {
  index: number;
  source_file?: string | null;
  source_id?: string | null;
  entity_id?: string | null;
  name?: string | null;
  status: ImportItemStatus;
  message?: string | null;
}

export interface BatchImportResult {
  created: number;
  skipped: number;
  failed: number;
  total: number;
  items: ImportItemResult[];
  created_ids: string[];
}

/** Build a concise human summary line, e.g. "3 created, 1 skipped, 2 failed". */
export function summarizeImport(result: BatchImportResult): string {
  const parts = [`${result.created} created`];
  if (result.skipped) parts.push(`${result.skipped} skipped`);
  if (result.failed) parts.push(`${result.failed} failed`);
  return parts.join(', ');
}
