/**
 * Review details: assets are listed by their display name when they have one
 * (Description Suggestions: table or table.column), and the editor is told
 * when the review is closed, so nothing can be decided in it any more.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

const getMock = vi.fn();

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: getMock, put: vi.fn(), post: vi.fn() }) }));
vi.mock('@/components/ui/toaster', () => ({ Toaster: () => null }));
vi.mock('@/components/common/relative-date', () => ({ RelativeDate: () => null }));
vi.mock('@/components/ui/data-table', () => ({
  DataTable: ({ columns, data }: any) => (
    <div>
      {data.map((row: any) => (
        <div key={row.id}>
          {columns
            .filter((c: any) => c.accessorKey === 'asset_fqn' || c.id === 'actions')
            .map((c: any) => (
              <span key={c.accessorKey ?? c.id}>{c.cell({ row: { original: row } })}</span>
            ))}
        </div>
      ))}
    </div>
  ),
}));
vi.mock('@/components/data-asset-reviews/asset-review-editor', () => ({
  default: ({ reviewClosed }: { reviewClosed?: boolean }) => (
    <div data-testid="editor">{reviewClosed ? 'closed' : 'open'}</div>
  ),
}));

import DataAssetReviewDetails from './data-asset-review-details';

const review = (status: string) => ({
  id: 'rev-1',
  requester_email: 'a@x.com',
  reviewer_email: 'b@x.com',
  status,
  title: 'Descriptions for main.sales',
  notes: null,
  created_at: '2026-10-26T00:00:00Z',
  updated_at: '2026-10-26T00:00:00Z',
  assets: [
    {
      id: 'ra-1',
      asset_fqn: 'metagen://run-1/s-1',
      asset_type: 'metadata_suggestion',
      status: 'pending',
      updated_at: '2026-10-26T00:00:00Z',
      display_name: 'main.sales.orders.id',
    },
  ],
});

const renderDetails = () =>
  render(
    <MemoryRouter initialEntries={['/data-asset-reviews/rev-1']}>
      <Routes>
        <Route path="/data-asset-reviews/:requestId" element={<DataAssetReviewDetails />} />
      </Routes>
    </MemoryRouter>,
  );

describe('DataAssetReviewDetails labels and closed state', () => {
  beforeEach(() => getMock.mockReset());

  it('lists a suggestion by its display name, keeping the FQN as tooltip', async () => {
    getMock.mockResolvedValue({ data: review('in_review') });
    renderDetails();

    const label = await screen.findByText('main.sales.orders.id');
    expect(label).toHaveAttribute('title', 'metagen://run-1/s-1');
    expect(screen.queryByText('metagen://run-1/s-1')).not.toBeInTheDocument();
  });

  it.each([
    ['approved', 'closed'],
    ['denied', 'closed'],
    ['cancelled', 'closed'],
    ['in_review', 'open'],
  ])('tells the editor a %s review is %s', async (status, expected) => {
    getMock.mockResolvedValue({ data: review(status) });
    renderDetails();

    fireEvent.click(await screen.findByText('data-asset-reviews:details.review'));
    expect(await screen.findByTestId('editor')).toHaveTextContent(expected);
  });
});
