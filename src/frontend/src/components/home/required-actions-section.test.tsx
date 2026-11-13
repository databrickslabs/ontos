import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/utils';
import { useNotificationsStore } from '@/stores/notifications-store';
import type { Notification } from '@/types/notification';
import RequiredActionsSection from './required-actions-section';

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
});
