/**
 * #1687 review: the Access Grants page decides by the workflow path's rule. Approvers who
 * aren't admins pick only the requested terms or narrower ones; an admin may pick wider
 * ones (the backend audits it as an override). Refusals show their coded text.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

import HandleAccessGrantDialog, { grantableDurations } from './handle-access-grant-dialog';

const api = vi.hoisted(() => ({
  admin: false,
  get: vi.fn(async () => ({ data: { duration_options: [7, 14, 30, 60, 90] } })),
  post: vi.fn(async (_url: string, _body: Record<string, unknown>) => ({ data: {} }) as any),
  toast: vi.fn(),
}));

vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: api.get, post: api.post }) }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: api.toast }) }));
vi.mock('@/hooks/use-is-ontos-admin', () => ({ useIsOntosAdmin: () => api.admin }));
// Radix Select through jsdom is slow and flaky: the options are what matters here
vi.mock('@/components/ui/select', () => ({
  Select: ({ children }: { children?: React.ReactNode }) => <div role="listbox">{children}</div>,
  SelectTrigger: ({ id }: { id?: string }) => <span data-testid={id} />,
  SelectValue: () => null,
  SelectContent: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  SelectItem: ({ value, children }: { value: string; children?: React.ReactNode }) => (
    <div role="option" aria-selected={false} data-value={value}>{children}</div>
  ),
}));

const REQUEST = {
  id: 'r-1',
  requester_email: 'rita@example.com',
  entity_type: 'data_product',
  entity_id: 'p-1',
  entity_name: 'Orders',
  requested_duration_days: 30,
  permission_level: 'WRITE',
  status: 'pending',
  created_at: '2026-11-20T10:00:00Z',
};

function renderDialog() {
  render(<HandleAccessGrantDialog isOpen onOpenChange={() => {}} request={REQUEST} />);
}

function optionValues(listbox: HTMLElement): string[] {
  return within(listbox).getAllByRole('option').map((o) => o.getAttribute('data-value') ?? '');
}

async function listboxes() {
  await waitFor(() => expect(api.get).toHaveBeenCalled());
  const [durations, levels] = await screen.findAllByRole('listbox');
  await waitFor(() => expect(optionValues(durations).length).toBeGreaterThan(0));
  return { durations, levels };
}

afterEach(() => {
  api.admin = false;
  api.post.mockClear();
  api.toast.mockClear();
});

describe('HandleAccessGrantDialog terms', () => {
  it('offers an approver the requested terms or narrower ones', async () => {
    renderDialog();
    const { durations, levels } = await listboxes();
    expect(optionValues(durations)).toEqual(['7', '14', '30']);
    expect(optionValues(levels)).toEqual(['READ', 'WRITE']);
    expect(screen.queryByText(/As an admin/)).toBeNull();
  });

  it('offers an admin wider terms and says it is an override', async () => {
    api.admin = true;
    renderDialog();
    const { durations, levels } = await listboxes();
    await waitFor(() => expect(optionValues(durations)).toEqual(['7', '14', '30', '60', '90']));
    expect(optionValues(levels)).toEqual(['READ', 'WRITE', 'MANAGE']);
    expect(screen.getByText(/As an admin/)).toBeInTheDocument();
  });

  it('shows a coded refusal in the UI language', async () => {
    api.post.mockResolvedValueOnce({
      data: {}, error: "You can't decide your own access request.",
      errorCode: 'own_access_request_approval', errorParams: null,
    });
    renderDialog();
    await listboxes();
    fireEvent.click(screen.getByRole('button', { name: /Approve/ }));
    await waitFor(() => expect(api.toast).toHaveBeenCalled());
    expect(api.toast.mock.calls[0][0]).toEqual(expect.objectContaining({
      variant: 'destructive', description: "You can't decide your own access request.",
    }));
  });

  it('keeps only durations up to the requested one for an approver', () => {
    expect(grantableDurations([7, 30, 90], 30, false)).toEqual([7, 30]);
    expect(grantableDurations([7, 30, 90], 30, true)).toEqual([7, 30, 90]);
  });
});
