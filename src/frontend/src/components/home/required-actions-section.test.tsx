import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { renderWithProviders } from '@/test/utils';
import { useNotificationsStore } from '@/stores/notifications-store';
import type { Notification } from '@/types/notification';
import RequiredActionsSection, { approvalEntityName } from './required-actions-section';

function approval(
  id: string, entityName: string, extra: Record<string, unknown> = {},
): Notification {
  return {
    id,
    type: 'action_required',
    title: 'Approval requested',
    created_at: '2026-11-06T12:00:00Z',
    read: false,
    can_delete: false,
    action_type: 'workflow_approval',
    action_payload: {
      execution_id: `exec-${id}`,
      step_id: 'approve',
      entity_name: entityName,
      requester_email: 'requester@example.com',
      ...extra,
    },
  };
}

describe('RequiredActionsSection workflow approvals', () => {
  beforeEach(() => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ contracts: [], products: [] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  function setNotifications(notifications: Notification[]) {
    useNotificationsStore.setState({
      notifications,
      unreadCount: notifications.filter(n => !n.read).length,
      isLoading: false,
      error: null,
      fetchNotifications: vi.fn(),
      markAsRead: vi.fn(),
    } as never);
  }

  it('leaves out an approval already decided, keeps the pending one', async () => {
    setNotifications([
      approval('pending', 'Pending Product'),
      // Decided (by this user or another member of the target group/role):
      // the backend marks it read and handled.
      { ...approval('decided', 'Decided Product', {
        handled: true,
        decision: 'approved',
        handled_by: 'someone@example.com',
      }), read: true },
    ]);

    renderWithProviders(<RequiredActionsSection />);

    expect(await screen.findByText('Pending Product')).toBeInTheDocument();
    expect(screen.queryByText('Decided Product')).not.toBeInTheDocument();
  });

  it('keeps a pending approval the user marked as read', async () => {
    setNotifications([{ ...approval('read', 'Read But Pending'), read: true }]);

    renderWithProviders(<RequiredActionsSection />);

    expect(await screen.findByText('Read But Pending')).toBeInTheDocument();
  });

  it('marks an approval past its timeout_days as overdue (#1119)', async () => {
    setNotifications([
      approval('late', 'Late Product', { overdue_since: '2026-11-09T12:00:00Z' }),
      approval('on-time', 'On Time Product'),
    ]);

    renderWithProviders(<RequiredActionsSection />);

    const late = (await screen.findByText('Late Product')).closest('tr')!;
    expect(late).toHaveTextContent('Overdue');
    const onTime = screen.getByText('On Time Product').closest('tr')!;
    expect(onTime).not.toHaveTextContent('Overdue');
  });
});

describe('RequiredActionsSection approvals queue', () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    useNotificationsStore.setState({
      notifications: [], unreadCount: 0, isLoading: false, error: null,
      fetchNotifications: vi.fn(), markAsRead: vi.fn(),
    } as never);
    fetchMock.mockReset();
    fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => ({}) });
    vi.stubGlobal('fetch', fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it('reads the queue by default', async () => {
    renderWithProviders(<RequiredActionsSection />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      '/api/approvals/queue', expect.anything(),
    ));
  });

  it('skips the queue request when fetchQueue is false', async () => {
    renderWithProviders(<RequiredActionsSection fetchQueue={false} />);
    await screen.findByText(/./);
    expect(fetchMock).not.toHaveBeenCalledWith('/api/approvals/queue', expect.anything());
  });
});

describe('approvalEntityName (#1615)', () => {
  it("names an access request's entity by the backend's name, never the requester's", () => {
    expect(approvalEntityName({
      entity_type: 'access_grant', entity_name: 'Spoofed', underlying_entity_name: 'Orders',
      underlying_entity_id: 'p-1',
    })).toBe('Orders');
    expect(approvalEntityName({
      entity_type: 'access_grant', entity_name: 'Spoofed', underlying_entity_id: 'p-1',
    })).toBe('p-1');
    expect(approvalEntityName({ entity_type: 'data_product', entity_name: 'Orders' }))
      .toBe('Orders');
    expect(approvalEntityName(null)).toBe('');
  });
});
