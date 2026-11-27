import { describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { DataDomain } from '@/types/data-domain';

// Record the `nodes` array identity handed to React Flow on each render and count the
// fit-to-view calls (jsdom can't lay out a real flow).
const seenNodes: unknown[] = [];
const fitView = vi.fn();

vi.mock('reactflow', () => ({
  __esModule: true,
  default: ({ nodes }: { nodes: unknown }) => {
    seenNodes.push(nodes);
    return null;
  },
  ReactFlowProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useReactFlow: () => ({ fitView }),
  MarkerType: { ArrowClosed: 'arrowclosed' },
  Position: { Top: 'top', Bottom: 'bottom', Left: 'left', Right: 'right' },
  Handle: () => null,
}));

import { DataDomainMiniGraph } from './data-domain-mini-graph';

const domain = {
  id: 'd1',
  name: 'Retail',
  parent_info: null,
  children_info: [{ id: 'd2', name: 'Retail Operations' }],
} as unknown as DataDomain;

describe('DataDomainMiniGraph', () => {
  it('keeps the same nodes (no new fit-to-view) when the parent re-renders', () => {
    seenNodes.length = 0;
    fitView.mockClear();
    vi.useFakeTimers();
    try {
      const onNodeClick = vi.fn();
      const view = render(
        <MemoryRouter>
          <DataDomainMiniGraph currentDomain={domain} onNodeClick={onNodeClick} />
        </MemoryRouter>,
      );
      vi.advanceTimersByTime(100);
      // Same props again, as when the host page re-renders on each search keystroke.
      view.rerender(
        <MemoryRouter>
          <DataDomainMiniGraph currentDomain={domain} onNodeClick={onNodeClick} />
        </MemoryRouter>,
      );
      vi.advanceTimersByTime(100);

      expect(seenNodes.length).toBeGreaterThanOrEqual(2);
      expect(new Set(seenNodes).size).toBe(1);
      expect(fitView).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });
});
