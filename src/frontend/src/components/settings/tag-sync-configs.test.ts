import { describe, it, expect } from 'vitest';
import type { TagSyncConfig } from '@/types/workflow-configurations';
import {
  LIFECYCLE_STATUS_MAPPING,
  defaultLifecycleEntry,
  findEntryIndex,
  supportsLifecycleMapping,
  upsertEntry,
} from './tag-sync-configs';

const lifecycle: TagSyncConfig = {
  entity_type: 'data_product', mapping: LIFECYCLE_STATUS_MAPPING, enabled: true,
  tag_key_format: 'ontos_lifecycle_status', tag_value_format: '{PRODUCT.STATUS}',
};
const name: TagSyncConfig = {
  entity_type: 'data_product', enabled: true,
  tag_key_format: 'ontos_product_name', tag_value_format: '{PRODUCT.NAME}',
};

describe('tag sync config entries', () => {
  it('finds the main entry and the lifecycle entry apart, whatever the order', () => {
    const configs = [lifecycle, name];

    expect(findEntryIndex(configs, 'data_product')).toBe(1);
    expect(findEntryIndex(configs, 'data_product', LIFECYCLE_STATUS_MAPPING)).toBe(0);
    expect(findEntryIndex(configs, 'data_contract')).toBe(-1);
  });

  it('treats a null mapping as the main entry', () => {
    expect(findEntryIndex([{ ...name, mapping: null }], 'data_product')).toBe(0);
  });

  it('defaults the lifecycle entries like the job YAML', () => {
    expect(defaultLifecycleEntry('data_product')).toEqual(lifecycle);
    expect(defaultLifecycleEntry('data_contract')).toEqual({
      entity_type: 'data_contract', mapping: LIFECYCLE_STATUS_MAPPING, enabled: false,
      tag_key_format: 'ontos_lifecycle_status', tag_value_format: '{CONTRACT.STATUS}',
    });
    expect(defaultLifecycleEntry('asset').tag_value_format).toBe('');
  });

  it('only products and contracts have a lifecycle entry', () => {
    expect(supportsLifecycleMapping('data_product')).toBe(true);
    expect(supportsLifecycleMapping('data_contract')).toBe(true);
    expect(supportsLifecycleMapping('data_domain')).toBe(false);
  });

  it('updates the entry in place or appends the fallback, without mutating', () => {
    const configs = [name];

    expect(upsertEntry(configs, 0, lifecycle, { enabled: false })).toEqual([
      { ...name, enabled: false },
    ]);
    expect(upsertEntry(configs, -1, lifecycle, { enabled: false })).toEqual([
      name, { ...lifecycle, enabled: false },
    ]);
    expect(configs).toEqual([name]);
  });
});
