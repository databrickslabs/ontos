/**
 * The timeline shows a placeholder until its first response, instead of
 * flashing the "No comments yet" empty state.
 */
import { screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import i18n from '@/i18n/config';
import { renderWithProviders } from '@/test/utils';
import { CommentTimeline } from './comment-timeline';

// Stable references, as the real hooks return: fetchTimeline depends on them
const mockGet = vi.fn();
const api = { get: mockGet, post: vi.fn(), put: vi.fn(), delete: vi.fn() };
const toaster = { toast: vi.fn() };
const project = { currentProject: null };
vi.mock('@/hooks/use-api', () => ({ useApi: () => api }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => toaster }));
vi.mock('@/stores/project-store', () => ({ useProjectContext: () => project }));

const emptyTitle = () => i18n.t('comments:empty.allTitle');

describe('CommentTimeline loading state', () => {
  let resolveTimeline!: (v: unknown) => void;

  beforeEach(() => {
    vi.clearAllMocks();
    mockGet.mockImplementation((url: string) =>
      url.includes('/timeline')
        ? new Promise((r) => { resolveTimeline = r; })
        : Promise.resolve({ data: [] }),
    );
  });

  it('shows no empty state before the timeline has loaded', async () => {
    renderWithProviders(<CommentTimeline entityType="data_product" entityId="p1" />);
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(expect.stringContaining('/timeline')));
    expect(screen.queryByText(emptyTitle())).not.toBeInTheDocument();

    resolveTimeline({ data: { timeline: [], total_count: 0 } });
    expect(await screen.findByText(emptyTitle())).toBeInTheDocument();
  });

  it('shows the empty state after a failed load, not a placeholder forever', async () => {
    renderWithProviders(<CommentTimeline entityType="data_product" entityId="p1" />);
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(expect.stringContaining('/timeline')));

    resolveTimeline({ error: 'boom' });
    expect(await screen.findByText(emptyTitle())).toBeInTheDocument();
  });
});
