import type { TFunction } from 'i18next';
import type { BatchImportResult, ImportItemResult } from '@/types/import-results';
import { ODCS_API_VERSION_UNSUPPORTED } from '@/lib/odcs-api-version-error';

/** Codes of the lifecycle import messages (`common:deprecation.import.<code>`). */
const IMPORT_CODES = new Set([
  'imported_date_invalid',
  'replacement_is_self',
  'replacement_leads_back',
  'imported_replacement_dropped',
  'imported_replacement_leads_back',
  'imported_status_mapped',
  'imported_legacy_status',
  'imported_certified_as_active',
]);

/** Codes of status checks an import can fail, with the keys the status change dialogs use. */
const STATUS_CODE_KEYS: Record<string, string> = {
  certified_is_not_a_status: 'workflow-gates:certifiedIsNotAStatus',
};

/** Codes of the reasons a delivery failed (`common:importDelivery.reason.<code>`). */
const DELIVERY_CODES = new Set([
  'delivery_git_unavailable',
  'delivery_git_write_failed',
  'delivery_entity_not_found',
  'delivery_failed',
]);

/**
 * The items an import report lists: those not created, and created ones with a
 * note or whose delivery failed or is still queued.
 */
export function reportedImportItems(result: BatchImportResult): ImportItemResult[] {
  return result.items.filter(
    (i) => i.status !== 'created' || !!i.message || i.delivery?.status === 'failed'
      || i.delivery?.status === 'pending',
  );
}

/** Why a created item wasn't delivered, or null when it was (or nothing was to be). */
function deliveryText(item: ImportItemResult, t: TFunction): string | null {
  if (item.delivery?.status === 'pending') return t('common:importDeliveryOutbox.pending');
  if (item.delivery?.status !== 'failed') return null;
  const code = item.delivery.code && DELIVERY_CODES.has(item.delivery.code)
    ? item.delivery.code : 'delivery_failed';
  return t(`common:importDelivery.reason.${code}`, { ...(item.delivery.params ?? {}) });
}

/** One line of an import report, translated when the backend sent a known code. */
export function importItemLine(item: ImportItemResult, t: TFunction): string {
  const delivery = deliveryText(item, t);
  if (delivery && !item.message) {
    return `• ${item.name || item.source_id || `#${item.index}`}: ${delivery}`;
  }
  const line = noteLine(item, t);
  return delivery ? `${line} ${delivery}` : line;
}

function noteLine(item: ImportItemResult, t: TFunction): string {
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
  // Refused by a status check shared with the status change dialogs
  const statusKey = item.code ? STATUS_CODE_KEYS[item.code] : undefined;
  if (item.code === ODCS_API_VERSION_UNSUPPORTED) {
    // Refused for an apiVersion outside ODCS, as the create and edit dialogs explain it
    return `• ${name}: ${t('data-contracts:apiVersionErrors.unsupported', {
      apiVersion: String(item.params?.api_version ?? ''), defaultValue: fallback,
    })}`;
  }
  if (statusKey) {
    return `• ${name}: ${t(statusKey, { ...(item.params ?? {}), defaultValue: fallback })}`;
  }
  const text = item.code && IMPORT_CODES.has(item.code)
    ? t(`common:deprecation.import.${item.code}`, {
      ...(item.params ?? {}), defaultValue: fallback,
    })
    : fallback;
  return `• ${name}: ${text}`;
}

type ImportNote = NonNullable<ImportItemResult['notes']>[number];

function noteText(note: ImportNote, t: TFunction): string | null {
  if (note.code && IMPORT_CODES.has(note.code)) {
    return t(`common:deprecation.import.${note.code}`, {
      ...(note.params ?? {}), defaultValue: note.message ?? '',
    });
  }
  return note.message ?? null;
}
