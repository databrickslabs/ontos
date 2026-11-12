/**
 * A contract's status change request is decided from the Status Change
 * Request workflow's approval notification, as a product's (#1120). The
 * contract-specific notification and its decision dialog are gone: a
 * notification left from before has no action.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '@/i18n/config';
import { renderWithProviders } from '@/test/utils';
import { useNotificationsStore } from '@/stores/notifications-store';
import type { Notification } from '@/types/notification';
import NotificationBell from './notification-bell';

// What the action opens the dialog with. (A Radix Dialog opened from the open
// DropdownMenu loops on focus in jsdom; the open menu hides the rest of the
// page, hence a test id, not a role.)
vi.mock('@/components/workflows/workflow-approval-response-dialog', () => ({
  default: (props: Record<string, unknown>) =>
    props.isOpen ? <div data-testid="approval-dialog">{JSON.stringify(props)}</div> : null,
}));

const approval: Notification = {
  id: 'n-wf',
  type: 'action_required',
  title: 'Approval Required',
  subtitle: 'data_contract: Orders v1',
  description: 'Approval requested for data_contract Orders v1',
  created_at: '2026-10-31T12:00:00Z',
  read: false,
  can_delete: false,
  action_type: 'workflow_approval',
  action_payload: {
    execution_id: 'exec-1',
    step_id: 'request-approval',
    workflow_name: 'Status Change Request',
    entity_type: 'data_contract',
    entity_id: 'c1',
    entity_name: 'Orders v1',
    requester_email: 'owner@example.com',
  },
};

const legacy: Notification = {
  id: 'n-scr',
  type: 'action_required',
  title: 'Status Change Request Pending',
  subtitle: 'Contract: Orders v1',
  description: "owner@example.com is requesting to change status from 'active' to 'deprecated'.",
  created_at: '2026-10-31T11:00:00Z',
  read: false,
  can_delete: true,
  action_type: 'handle_status_change_request',
  action_payload: {
    contract_id: 'c1',
    requester_email: 'owner@example.com',
    from_status: 'active',
    target_status: 'deprecated',
  },
};

function setNotifications(notifications: Notification[]) {
  useNotificationsStore.setState({
    notifications,
    unreadCount: notifications.length,
    isLoading: false,
    error: null,
    fetchNotifications: vi.fn(),
    markAsRead: vi.fn(),
  } as never);
}

async function openBell() {
  const user = userEvent.setup();
  renderWithProviders(<NotificationBell />);
  await user.click(screen.getByRole('button', { name: /1/ }));
  return user;
}

describe('NotificationBell: a contract status change request', () => {
  beforeEach(() => setNotifications([approval]));

  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('opens the workflow approval dialog for the contract', async () => {
    const user = await openBell();

    await user.click(await screen.findByRole('button', { name: 'Approve/Deny' }));

    const dialog = await screen.findByTestId('approval-dialog');
    const props = JSON.parse(dialog.textContent || '{}');
    expect(props.notificationId).toBe('n-wf');
    expect(props.payload).toMatchObject({
      execution_id: 'exec-1',
      entity_type: 'data_contract',
      entity_id: 'c1',
      requester_email: 'owner@example.com',
    });
  });

  it('offers the approval in the user language', async () => {
    await i18n.changeLanguage('pt');
    await openBell();

    expect(await screen.findByRole('button', { name: 'Aprovar/Negar' })).toBeInTheDocument();
  });

  it('gives a notification of the former contract-only flow no decision action', async () => {
    setNotifications([legacy]);
    await openBell();

    expect(await screen.findByText('Status Change Request Pending')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Approve/Deny' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'View Details' })).not.toBeInTheDocument();
  });
});
