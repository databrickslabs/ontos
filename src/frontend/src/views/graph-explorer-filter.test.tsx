/**
 * Focused tests for the ?filterType= URL parameter handling in GraphExplorerView.
 * Phase 2b: verifies that the filterType param is read and applied as a node type filter.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// ---- Mocks ----

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (opts && typeof opts === 'object') {
        let result = key;
        for (const [k, v] of Object.entries(opts)) {
          result = result.replace(`{{${k}}}`, String(v));
        }
        return result;
      }
      return key;
    },
    i18n: { language: 'en' },
  }),
}));

// Mock use-toast
vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({
    toast: vi.fn(),
  }),
}));

// Mock heavy child components to keep tests lightweight
vi.mock('@/components/graph-explorer/graph-visualization', () => ({
  default: vi.fn(() => <div data-testid="graph-viz" />),
  __esModule: true,
}));

vi.mock('@/components/graph-explorer/graph-controls', () => ({
  default: vi.fn(() => <div data-testid="graph-controls" />),
  __esModule: true,
}));

vi.mock('@/components/graph-explorer/graph-table-view', () => ({
  GraphTableView: vi.fn(() => <div data-testid="graph-table-view" />),
}));

vi.mock('@/components/graph-explorer/diagram-manager', () => ({
  DiagramManager: vi.fn(() => <div data-testid="diagram-manager" />),
}));

vi.mock('@/components/graph-explorer/node-palette', () => ({
  default: vi.fn(() => <div data-testid="node-palette" />),
  __esModule: true,
}));

vi.mock('@/components/graph-explorer/node-search', () => ({
  default: vi.fn(() => <div data-testid="node-search" />),
  __esModule: true,
}));

vi.mock('@/components/graph-explorer/node-edge-form', () => ({
  NodeForm: vi.fn(() => null),
  EdgeForm: vi.fn(() => null),
}));

vi.mock('@/components/graph-explorer/graph-query-panel', () => ({
  default: vi.fn(() => <div data-testid="query-panel" />),
  __esModule: true,
}));

vi.mock('@/components/graph-explorer/graph-context-menu', () => ({
  GraphContextMenu: vi.fn(() => null),
}));

vi.mock('@/components/graph-explorer/concept-tooltip', () => ({
  ConceptTooltip: vi.fn(() => null),
}));

import GraphExplorerView from './graph-explorer';

describe('GraphExplorerView - filterType URL param', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Mock fetch to prevent actual API calls
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ nodes: [], edges: [], truncated: false }),
    });
  });

  it('shows filterType banner when ?filterType= is in the URL', async () => {
    render(
      <MemoryRouter initialEntries={['/graph-explorer?filterType=Person']}>
        <GraphExplorerView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText(/filterType\.active/)).toBeInTheDocument();
    });
  });

  it('does not show filterType banner when param is absent', () => {
    render(
      <MemoryRouter initialEntries={['/graph-explorer']}>
        <GraphExplorerView />
      </MemoryRouter>,
    );

    expect(screen.queryByText(/filterType\.active/)).not.toBeInTheDocument();
  });

  it('clears the filter when the clear button is clicked', async () => {
    render(
      <MemoryRouter initialEntries={['/graph-explorer?filterType=Person']}>
        <GraphExplorerView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText(/filterType\.active/)).toBeInTheDocument();
    });

    const clearBtn = screen.getByText('filterType.clear');
    fireEvent.click(clearBtn);

    await waitFor(() => {
      expect(screen.queryByText(/filterType\.active/)).not.toBeInTheDocument();
    });
  });
});
