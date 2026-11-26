/**
 * A description change of an asset is shown with translated labels (and the name of its
 * source), not as the raw key: value fallback of an unknown change.
 */
import { screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import { CommentTimeline } from './comment-timeline';

const mockGet = vi.fn();
const api = { get: mockGet, post: vi.fn(), put: vi.fn(), delete: vi.fn() };
const toaster = { toast: vi.fn() };
const project = { currentProject: null };
vi.mock('@/hooks/use-api', () => ({ useApi: () => api }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => toaster }));
vi.mock('@/stores/project-store', () => ({ useProjectContext: () => project }));

const change = {
  id: 'c1', type: 'change', entity_type: 'asset', entity_id: 'a1',
  title: 'Description Changed', username: 'user@example.com',
  timestamp: '2026-11-20T10:00:00Z',
  content: JSON.stringify({
    name: 'orders', object_type: 'table', location: 'main.sales.orders',
    before: null, after: 'Orders placed online', source: 'uc_reset',
  }),
  metadata: { action: 'description_changed' },
};

describe('CommentTimeline description changes', () => {
  beforeEach(() => {
    mockGet.mockImplementation((url: string) =>
      Promise.resolve(url.includes('/timeline')
        ? { data: { timeline: [change], total_count: 1 } }
        : { data: [] }));
  });

  it('shows translated labels, the text before and after and the source', async () => {
    renderWithProviders(<CommentTimeline entityType="asset" entityId="a1" />);

    expect(await screen.findByText('Before:')).toBeInTheDocument();
    expect(screen.getByText('After:')).toBeInTheDocument();
    expect(screen.getByText('Orders placed online')).toBeInTheDocument();
    expect(screen.getByText('(empty)')).toBeInTheDocument();
    expect(screen.getByText('Unity Catalog comment')).toBeInTheDocument();
    expect(screen.getByText('Description changed')).toBeInTheDocument();
    expect(screen.queryByText(/object type:/i)).not.toBeInTheDocument();
  });
});
