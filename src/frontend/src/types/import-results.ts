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
  /** Skip reason, error detail, or a note on a created entity. */
  message?: string | null;
  /** Code of the message, translated by the UI when known. */
  code?: string | null;
  params?: Record<string, unknown> | null;
}

export interface BatchImportResult {
  created: number;
  skipped: number;
  failed: number;
  total: number;
  items: ImportItemResult[];
  created_ids: string[];
}

/**
 * The summary line of an import in the user's language, e.g. "Created: 3,
 * skipped: 1, failed: 2." One whole sentence per combination of counts.
 */
export function summarizeImport(
  result: BatchImportResult,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  const key = `created${result.skipped ? 'Skipped' : ''}${result.failed ? 'Failed' : ''}`;
  return t(`common:importSummary.${key}`, {
    created: result.created,
    skipped: result.skipped,
    failed: result.failed,
  });
}
