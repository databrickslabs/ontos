import type { Translate } from './status-labels';

/**
 * The toast text after data product files were uploaded: one sentence that
 * names a single file or counts several, then the number of products.
 */
export function productUploadSuccessText(
  files: { name: string }[],
  created: number,
  t: Translate,
): string {
  return files.length === 1
    ? t('data-products:upload.successMessage', { filename: files[0].name, count: created })
    : t('data-products:upload.successMessage', { context: 'files', files: files.length, count: created });
}
