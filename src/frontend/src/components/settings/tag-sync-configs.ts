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
