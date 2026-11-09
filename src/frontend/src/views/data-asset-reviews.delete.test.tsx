import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const toast = vi.fn();
const getMock = vi.fn();
const deleteMock = vi.fn();

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast }) }));
vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: getMock, delete: deleteMock }),
}));
vi.mock('@/stores/project-store', () => ({
  useProjectContext: () => ({ currentProject: null, hasProjectContext: false }),
}));
vi.mock('@/components/ui/toaster', () => ({ Toaster: () => null }));
vi.mock('@/components/common/relative-date', () => ({ RelativeDate: () => null }));
vi.mock('@/components/common/list-view-skeleton', () => ({ ListViewSkeleton: () => null }));
vi.mock('@/components/data-asset-reviews/create-review-request-dialog', () => ({
  default: () => null,
}));
vi.mock('@/components/ui/data-table', () => ({
  DataTable: ({ columns, data }: any) => (
    <div>
      {data.map((row: any) => (
        <div key={row.id}>
          {columns
            .find((c: any) => c.id === 'actions')
            .cell({ row: { original: row } })}
        </div>
      ))}
    </div>
  ),
}));

import DataAssetReviews from './data-asset-reviews';

describe('DataAssetReviews delete', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    getMock.mockResolvedValue({ data: [{ id: 'r1', title: 'T', status: 'queued' }] });
  });

  it('shows the error toast and does not refresh the list when DELETE fails', async () => {
    deleteMock.mockResolvedValue({ data: null, error: 'boom' });
    render(
      <MemoryRouter>
        <DataAssetReviews />
      </MemoryRouter>,
    );
    const btn = await screen.findByTitle('common:tooltips.deleteRequest');
    fireEvent.click(btn);
    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        expect.objectContaining({ variant: 'destructive', description: 'boom' }),
      ),
    );
    expect(toast).not.toHaveBeenCalledWith(
      expect.objectContaining({ description: 'data-asset-reviews:toast.requestDeleted' }),
    );
    expect(getMock).toHaveBeenCalledTimes(1);
  });

  it('shows success and refreshes the list when DELETE succeeds', async () => {
    deleteMock.mockResolvedValue({ data: null });
    render(
      <MemoryRouter>
        <DataAssetReviews />
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByTitle('common:tooltips.deleteRequest'));
    await waitFor(() => expect(getMock).toHaveBeenCalledTimes(2));
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ description: 'data-asset-reviews:toast.requestDeleted' }),
    );
  });
});
