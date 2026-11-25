/** FitAfterRearrange fits once per Rearrange, also when fitView changes before the fit runs. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render } from '@testing-library/react';

import { FitAfterRearrange } from './workflow-designer';

const rf = vi.hoisted(() => ({ fitView: vi.fn() }));
vi.mock('reactflow', async (importOriginal) => {
  const actual = await importOriginal<typeof import('reactflow')>();
  return { ...actual, useReactFlow: () => ({ fitView: rf.fitView }) };
});

describe('FitAfterRearrange', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    rf.fitView = vi.fn();
  });
  afterEach(() => vi.useRealTimers());

  it('fits after a new version, and not before one', () => {
    const { rerender } = render(<FitAfterRearrange version={0} />);
    act(() => { vi.runAllTimers(); });
    expect(rf.fitView).not.toHaveBeenCalled();

    rerender(<FitAfterRearrange version={1} />);
    act(() => { vi.runAllTimers(); });
    expect(rf.fitView).toHaveBeenCalledTimes(1);
    expect(rf.fitView).toHaveBeenCalledWith({ maxZoom: 1, padding: 0.2 });
  });

  it('still fits when fitView changes identity before the timer runs', () => {
    const { rerender } = render(<FitAfterRearrange version={0} />);
    rerender(<FitAfterRearrange version={1} />);
    const first = rf.fitView;
    rf.fitView = vi.fn();
    rerender(<FitAfterRearrange version={1} />);
    act(() => { vi.runAllTimers(); });

    expect(first).not.toHaveBeenCalled();
    expect(rf.fitView).toHaveBeenCalledTimes(1);
  });
});
