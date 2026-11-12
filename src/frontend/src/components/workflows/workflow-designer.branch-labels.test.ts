/** A conditional's edges are its true and false branches, not pass and fail (#1418). */
import { describe, it, expect, vi } from 'vitest';

vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }) }));

import i18n from '@/i18n/config';
import { branchEdgeLook } from './workflow-designer';

const t = i18n.getFixedT('en');

describe('branchEdgeLook', () => {
  it('labels a conditional edge True / False', () => {
    expect(branchEdgeLook('conditional', 'pass', t).label).toBe('True');
    expect(branchEdgeLook('conditional', 'fail', t).label).toBe('False');
  });

  it('labels them in the UI language', () => {
    expect(branchEdgeLook('conditional', 'fail', i18n.getFixedT('de')).label).toBe('Falsch');
  });

  it('labels other edges Pass / Fail', () => {
    expect(branchEdgeLook('validation', 'pass', t).label).toBe('Pass');
    expect(branchEdgeLook(undefined, 'fail', t).label).toBe('Fail');
  });
});
