/** A conditional's edges are its true and false branches, not pass and fail (#1418). */
import { describe, it, expect, vi } from 'vitest';

vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }) }));

import { branchEdgeLook } from './workflow-designer';

describe('branchEdgeLook', () => {
  it('labels a conditional edge True / False', () => {
    expect(branchEdgeLook('conditional', 'pass').label).toBe('True');
    expect(branchEdgeLook('conditional', 'fail').label).toBe('False');
  });

  it('labels other edges Pass / Fail', () => {
    expect(branchEdgeLook('validation', 'pass').label).toBe('Pass');
    expect(branchEdgeLook(undefined, 'fail').label).toBe('Fail');
  });
});
