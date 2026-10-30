import { lifecycleStatusLabel, type Translate } from './status-labels';

// Labels of the request details in the approval dialog. The request payload
// comes from the trigger (e.g. a status change request sends product_id,
// from_status, target_status, justification); known fields and the entity
// type are shown in the user's language, any other field as its humanised key.

const ENTITY_TYPE_FALLBACKS: Record<string, string> = {
  data_product: 'Data Product',
  data_contract: 'Data Contract',
  data_domain: 'Data Domain',
  data_asset_review: 'Data Asset Review',
  access_grant: 'Access Grant',
  asset: 'Asset',
  ontology_concept: 'Concept',
  concept: 'Concept',
};

/** Payload fields whose value is a lifecycle status. */
const STATUS_FIELDS = new Set(['status', 'from_status', 'to_status', 'target_status', 'current_status']);

function humanize(text: string): string {
  return text
    .replace(/_/g, ' ')
    .split(' ')
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(' ');
}

/** The entity type of the request, e.g. "Data Product". */
export function approvalEntityTypeLabel(entityType: string | undefined | null, t: Translate): string {
  if (!entityType) return t('workflows:approvalResponse.entityTypes.entity', { defaultValue: 'Entity' });
  const key = entityType.toLowerCase();
  return t(`workflows:approvalResponse.entityTypes.${key}`, {
    defaultValue: ENTITY_TYPE_FALLBACKS[key] ?? humanize(entityType),
  });
}

/** The label of a payload field, e.g. "Target status" for target_status. */
export function approvalFieldLabel(key: string, t: Translate): string {
  return t(`workflows:approvalResponse.fields.${key}`, {
    defaultValue: key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
  });
}

/** The value of a payload field as shown; statuses in the user's language. */
export function approvalFieldValue(
  key: string,
  val: unknown,
  entityType: string | undefined | null,
  t: Translate,
): string {
  if (STATUS_FIELDS.has(key) && typeof val === 'string') {
    return lifecycleStatusLabel(val, entityType, t);
  }
  if (Array.isArray(val)) return val.join(', ');
  if (typeof val === 'object' && val !== null) return JSON.stringify(val);
  return String(val);
}
