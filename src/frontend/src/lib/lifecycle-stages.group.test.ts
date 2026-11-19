/**
 * A row's lifecycle group is found by the id products (camelCase) and contracts
 * (snake_case) send.
 */
import { describe, it, expect } from 'vitest';
import { groupOfRow } from './lifecycle-stages';
import type { LifecycleStageGroup } from '@/types/lifecycle-stage-groups';

const group = (id: string, isDefault: boolean) => ({
  id, is_default_for_type: isDefault, stages: [], transitions: [],
} as unknown as LifecycleStageGroup);
const GROUPS = [group('g-default', true), group('g-custom', false)];

describe('groupOfRow', () => {
  it('finds the group of a contract by lifecycle_stage_group_id', () => {
    expect(groupOfRow({ lifecycle_stage_group_id: 'g-custom' }, GROUPS)?.id).toBe('g-custom');
  });

  it('finds the group of a product by lifecycleStageGroupId', () => {
    expect(groupOfRow({ lifecycleStageGroupId: 'g-custom' }, GROUPS)?.id).toBe('g-custom');
  });

  it('falls back to the default group', () => {
    expect(groupOfRow({}, GROUPS)?.id).toBe('g-default');
  });
});
