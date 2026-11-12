import type { TFunction } from 'i18next';

import type { SchemaImportRunDetail } from '@/types/schema-import';

type RunCounts = Pick<
  SchemaImportRunDetail,
  'processed_items' | 'total_items' | 'created_count' | 'skipped_count' | 'error_count'
>;

/** A background schema import's status in the user's language. */
export function asyncRunStatusLabel(status: string, t: TFunction): string {
  return t(`database-schema:preview.async.status.${status}`, { defaultValue: status });
}

/**
 * The progress line of a background schema import: one whole sentence with
 * the counts, errors only when there were any. Pure.
 */
export function asyncRunProgressText(run: RunCounts, t: TFunction): string {
  const counts = {
    processed: run.processed_items,
    total: run.total_items,
    created: run.created_count,
    skipped: run.skipped_count,
    errors: run.error_count,
  };
  return run.error_count
    ? t('database-schema:preview.async.progressWithErrors', counts)
    : t('database-schema:preview.async.progress', counts);
}
