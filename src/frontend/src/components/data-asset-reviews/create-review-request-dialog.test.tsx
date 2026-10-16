/**
 * The dialog sends the new review request to the route the backend serves
 * (#965): `POST /api/data-asset-reviews`. With a trailing slash the request
 * reached the frontend fallback route and failed with "Method Not Allowed".
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import CreateReviewRequestDialog from './create-review-request-dialog';

vi.mock('@/components/ui/tree-view', () => ({
  TreeView: ({ data, onSelectChange }: { data: any[]; onSelectChange: (i: { id: string }) => void }) => {
    const flat = (items: any[]): any[] => items.flatMap((i) => [i, ...flat(i.children || [])]);
    return (
      <div>
        {flat(data).map((item) => (
          <button key={item.id} type="button" onClick={() => onSelectChange({ id: item.id })}>
            {item.id}
          </button>
        ))}
      </div>
    );
  },
}));

vi.mock('@/components/common/principal-picker', () => ({
  PrincipalPicker: ({ onChange }: { onChange: (v: string | null) => void }) => (
    <input aria-label="reviewer" onChange={(e) => onChange(e.target.value)} />
  ),
}));

const CATALOGS = [{
  id: 'main', name: 'main', type: 'catalog',
  children: [{
    id: 'main.sales', name: 'sales', type: 'schema',
    children: [{ id: 'main.sales.orders', name: 'orders', type: 'table' }],
  }],
}];

describe('CreateReviewRequestDialog', () => {
  it('posts the request to /api/data-asset-reviews', async () => {
    const get = vi.fn(async (url: string) => (
      url === '/api/user/info' ? { data: { email: 'rita@example.com' } } : { data: CATALOGS }
    ));
    const post = vi.fn(async () => ({ data: { id: 'r-1' } }));
    const onSubmitSuccess = vi.fn();

    render(
      <CreateReviewRequestDialog
        isOpen
        onOpenChange={vi.fn()}
        api={{ get, post } as any}
        onSubmitSuccess={onSubmitSuccess}
      />,
    );

    await userEvent.click(await screen.findByRole('button', { name: 'main.sales.orders' }));
    await userEvent.type(screen.getByLabelText('reviewer'), 'sam@example.com');
    await userEvent.click(screen.getByRole('button', { name: /Submit Request/ }));

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post).toHaveBeenCalledWith('/api/data-asset-reviews', expect.objectContaining({
      requester_email: 'rita@example.com',
      reviewer_email: 'sam@example.com',
      asset_fqns: ['main.sales.orders'],
    }));
    expect(onSubmitSuccess).toHaveBeenCalledWith({ id: 'r-1' });
  });
});
