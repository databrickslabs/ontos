import type { TagSyncConfig } from '@/types/workflow-configurations';

/**
 * Entries of a tag_sync_configs list.
 *
 * Per entity type, the main entry is the first one without a `mapping` id. An entry
 * with `mapping: 'lifecycle_status'` is the lifecycle status tag of that entity type;
 * the backend adds the YAML default one to saved lists that lack it.
 */
export const LIFECYCLE_STATUS_MAPPING = 'lifecycle_status';

const LIFECYCLE_VALUE_FORMATS: Record<string, string> = {
  data_contract: '{CONTRACT.STATUS}',
  data_product: '{PRODUCT.STATUS}',
};

export function supportsLifecycleMapping(entityType: string): boolean {
  return entityType in LIFECYCLE_VALUE_FORMATS;
}

/** Index of the entry for this entity type and mapping (none = the main entry), or -1. */
export function findEntryIndex(
  configs: TagSyncConfig[],
  entityType: string,
  mapping?: string,
): number {
  return configs.findIndex(
    (c) => c.entity_type === entityType && (c.mapping ?? undefined) === mapping,
  );
}

/** Asset entry with `mapping: 'maturity'`: the maturity level of a table or view asset. */
export const MATURITY_MAPPING = 'maturity';

/** The variables of the maturity entry; the job reads them only when an entry uses one. */
export const MATURITY_VARIABLES = ['{ASSET.MATURITY}', '{ASSET.MATURITY_ORDER}'];

/** Prefix of {ASSET.MATURITY_AT_LEAST:<order>}: "true" when the level number is >= order. */
export const MATURITY_AT_LEAST_PREFIX = '{ASSET.MATURITY_AT_LEAST:';

/** A well-formed threshold variable; the job resolves only these (see uc_tag_sync.py). */
const MATURITY_AT_LEAST_TOKEN = /\{ASSET\.MATURITY_AT_LEAST:(\d+)\}/g;

/** True when a key or value formats a maturity variable (level name, number or threshold). */
export function usesMaturityVariable(format: string): boolean {
  return MATURITY_VARIABLES.some((v) => format.includes(v))
    || format.includes(MATURITY_AT_LEAST_PREFIX);
}

/** True when a threshold variable is malformed, e.g. `{ASSET.MATURITY_AT_LEAST:x}`. */
export function hasInvalidMaturityThreshold(format: string): boolean {
  const opened = format.split(MATURITY_AT_LEAST_PREFIX).length - 1;
  const valid = (format.match(MATURITY_AT_LEAST_TOKEN) ?? []).length;
  return opened !== valid;
}

/** Replace valid threshold variables with "true" or "false" for a level number. */
export function resolveMaturityThresholds(format: string, levelOrder: number | null): string {
  return format.replace(MATURITY_AT_LEAST_TOKEN, (_match, order: string) =>
    levelOrder !== null && levelOrder >= Number(order) ? 'true' : 'false');
}

export function supportsMaturityMapping(entityType: string): boolean {
  return entityType === 'asset';
}

/** Same as the YAML default: disabled until an admin turns it on. */
export function defaultMaturityEntry(): TagSyncConfig {
  return {
    entity_type: 'asset',
    mapping: MATURITY_MAPPING,
    enabled: false,
    tag_key_format: 'ontos_maturity',
    tag_value_format: '{ASSET.MATURITY}',
  };
}

/** Same as the YAML default: the product entry is enabled, the contract entry isn't. */
export function defaultLifecycleEntry(entityType: string): TagSyncConfig {
  return {
    entity_type: entityType as TagSyncConfig['entity_type'],
    mapping: LIFECYCLE_STATUS_MAPPING,
    enabled: entityType === 'data_product',
    tag_key_format: 'ontos_lifecycle_status',
    tag_value_format: LIFECYCLE_VALUE_FORMATS[entityType] ?? '',
  };
}

/** Return a new list with the entry at `index` (or `fallback`, appended) updated. */
export function upsertEntry(
  configs: TagSyncConfig[],
  index: number,
  fallback: TagSyncConfig,
  updates: Partial<TagSyncConfig>,
): TagSyncConfig[] {
  const next = [...configs];
  if (index >= 0) {
    next[index] = { ...next[index], ...updates };
  } else {
    next.push({ ...fallback, ...updates });
  }
  return next;
}
