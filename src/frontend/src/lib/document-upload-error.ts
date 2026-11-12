import type { TFunction } from 'i18next';

/**
 * The text to show for a failed document upload: the translated text of a
 * `volume_invalid` refusal (`{detail: {code, message, params}}`), else the raw
 * response text. Takes the response body as text.
 */
export function documentUploadErrorText(body: string, t: TFunction): string {
  try {
    const detail = JSON.parse(body)?.detail;
    if (detail && typeof detail === 'object' && detail.code === 'volume_invalid') {
      return String(
        t('metadata:documents.messages.volume_invalid', {
          ...(detail.params ?? {}),
          defaultValue: detail.message,
        })
      );
    }
  } catch {
    // not JSON: show the text as it is
  }
  return body;
}
