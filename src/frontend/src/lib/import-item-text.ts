import type { TFunction } from 'i18next';
import type { BatchImportResult, ImportItemResult } from '@/types/import-results';

/** Codes of the lifecycle import messages (`common:deprecation.import.<code>`). */
const IMPORT_CODES = new Set([
  'imported_date_invalid',
  'replacement_is_self',
  'replacement_leads_back',
  'imported_replacement_dropped',
  'imported_replacement_leads_back',
  'imported_status_mapped',
]);

/** The items an import report lists: those not created, and created ones with a note. */
export function reportedImportItems(result: BatchImportResult): ImportItemResult[] {
  return result.items.filter((i) => i.status !== 'created' || !!i.message);
}

/** One line of an import report, translated when the backend sent a known code. */
export function importItemLine(item: ImportItemResult, t: TFunction): string {
  const name = item.name || item.source_id || `#${item.index}`;
  const notes = item.notes ?? [];
  if (notes.length && item.code && IMPORT_CODES.has(item.code)) {
    // Several notes: each one translated on its own (the message joins their English texts)
    const texts = [{ code: item.code, params: item.params, message: null }, ...notes]
      .map((note) => noteText(note, t))
      .filter((text): text is string => !!text);
    if (texts.length === notes.length + 1) return `• ${name}: ${texts.join(' ')}`;
  }
  const fallback = item.message ?? item.status;
  const text = item.code && IMPORT_CODES.has(item.code)
    ? t(`common:deprecation.import.${item.code}`, { ...(item.params ?? {}), defaultValue: fallback })
    : fallback;
  return `• ${name}: ${text}`;
}

type ImportNote = NonNullable<ImportItemResult['notes']>[number];

function noteText(note: ImportNote, t: TFunction): string | null {
  if (note.code && IMPORT_CODES.has(note.code)) {
    return t(`common:deprecation.import.${note.code}`, { ...(note.params ?? {}), defaultValue: note.message ?? '' });
  }
  return note.message ?? null;
}
