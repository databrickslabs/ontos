/**
 * The admins' notification of a contract's status change request has an
 * Approve/Deny action that opens the decision dialog (it had no action, so
 * the request could only be decided through the API).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '@/i18n/config';
import { renderWithProviders } from '@/test/utils';
import { useNotificationsStore } from '@/stores/notifications-store';
import type { Notification } from '@/types/notification';
import NotificationBell from './notification-bell';

// The dialog itself is tested on its own; here, what the action opens it with.
// (A Radix Dialog opened from the open DropdownMenu loops on focus in jsdom;
// the open menu hides the rest of the page, hence a test id, not a role.)
vi.mock('@/components/data-contracts/handle-status-change-request-dialog', () => ({
  default: (props: Record<string, unknown>) =>
    props.isOpen ? <div data-testid="status-change-dialog">{JSON.stringify(props)}</div> : null,
}));

const request: Notification = {
  id: 'n-scr',
  type: 'action_required',
  title: 'Status Change Request Pending',
  subtitle: 'Contract: Orders v1',
  description: "owner@example.com is requesting to change status from 'active' to 'deprecated'.",
  created_at: '2026-10-31T12:00:00Z',
  read: false,
  can_delete: true,
  action_type: 'handle_status_change_request',
  action_payload: {
    contract_id: 'c1',
    contract_name: 'Orders v1',
    requester_email: 'owner@example.com',
    from_status: 'active',
    target_status: 'deprecated',
    justification: 'Replaced by Orders v2',
  },
  data: {
    i18n: {
      title: 'notifications:contractStatusChangeRequest.title',
      description: 'notifications:contractStatusChangeRequest.description',
      statusNamespace: 'data-contracts',
      params: {
        requester: 'owner@example.com',
        fromStatus: 'active',
        toStatus: 'deprecated',
        justification: 'Replaced by Orders v2',
      },
    },
  },
};

async function openBell() {
  const user = userEvent.setup();
  renderWithProviders(<NotificationBell />);
  await user.click(screen.getByRole('button', { name: /1/ }));
  return user;
}

describe('NotificationBell: a contract status change request', () => {
  beforeEach(() => {
    useNotificationsStore.setState({
      notifications: [request],
      unreadCount: 1,
      isLoading: false,
      error: null,
      fetchNotifications: vi.fn(),
      markAsRead: vi.fn(),
    } as never);
  });

  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('opens the decision dialog from the notification action', async () => {
    const user = await openBell();

    await user.click(await screen.findByRole('button', { name: 'Approve/Deny' }));

    const dialog = await screen.findByTestId('status-change-dialog');
    const props = JSON.parse(dialog.textContent || '{}');
    expect(props).toMatchObject({
      contractId: 'c1',
      contractName: 'Orders v1',
      requesterEmail: 'owner@example.com',
      fromStatus: 'active',
      targetStatus: 'deprecated',
      justification: 'Replaced by Orders v2',
    });
  });

  it('shows the notification and its action in the user language', async () => {
    await i18n.changeLanguage('pt');
    await openBell();

    expect(
      await screen.findByText('Solicitação de Mudança de Status Pendente'),
    ).toBeInTheDocument();
    expect(screen.getByText(/de 'Ativo' para 'Obsoleto'/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Aprovar/Negar' })).toBeInTheDocument();
  });

  it('keeps the action on a read notification, as View Details', async () => {
    useNotificationsStore.setState({
      notifications: [{ ...request, read: true }],
      unreadCount: 0,
    } as never);
    const user = userEvent.setup();
    renderWithProviders(<NotificationBell />);
    await user.click(screen.getByRole('button'));

    await user.click(await screen.findByRole('button', { name: 'View Details' }));

    const dialog = await screen.findByTestId('status-change-dialog');
    expect(dialog).toHaveTextContent('"contractId":"c1"');
  });
});
