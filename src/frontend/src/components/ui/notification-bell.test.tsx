import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '@/i18n/config';
import { renderWithProviders } from '@/test/utils';
import { useNotificationsStore } from '@/stores/notifications-store';
import type { Notification } from '@/types/notification';
import NotificationBell from './notification-bell';

const translated: Notification = {
  id: 'n-1',
  type: 'warning',
  title: 'Status change not applied',
  subtitle: 'Stale Request Demo',
  description: "The request to change the status from 'draft' to 'proposed' was approved, but ...",
  created_at: '2026-10-16T12:00:00Z',
  read: false,
  can_delete: true,
  data: {
    i18n: {
      title: 'notifications:statusChangeNotApplied.title',
      description: 'notifications:statusChangeNotApplied.statusChanged',
      params: { fromStatus: 'draft', toStatus: 'proposed', currentStatus: 'sandbox' },
    },
  },
};

const plain: Notification = {
  id: 'n-2',
  type: 'info',
  title: 'Job finished',
  description: 'The sync job finished.',
  created_at: '2026-10-16T12:01:00Z',
  read: false,
  can_delete: true,
};

async function openBell() {
  const user = userEvent.setup();
  renderWithProviders(<NotificationBell />);
  await user.click(screen.getByRole('button', { name: /2/ }));
}

describe('NotificationBell', () => {
  beforeEach(() => {
    useNotificationsStore.setState({
      notifications: [translated, plain],
      unreadCount: 2,
      isLoading: false,
      error: null,
      fetchNotifications: vi.fn(),
    } as never);
  });

  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('shows a notification sent with i18n keys in the user language', async () => {
    await i18n.changeLanguage('pt');
    await openBell();

    expect(await screen.findByText('Mudança de status não aplicada')).toBeInTheDocument();
    expect(screen.getByText(/o status agora é "sandbox"/)).toBeInTheDocument();
    // Subtitle (an entity name) and notifications without keys are shown as stored
    expect(screen.getByText('Stale Request Demo')).toBeInTheDocument();
    expect(screen.getByText('Job finished')).toBeInTheDocument();
    expect(screen.getByText('The sync job finished.')).toBeInTheDocument();
  });

  it('shows the English texts in English', async () => {
    await openBell();

    expect(await screen.findByText('Status change not applied')).toBeInTheDocument();
    expect(screen.getByText(/the status is now 'sandbox'/)).toBeInTheDocument();
  });

  it('labels its own controls in the user language', async () => {
    await i18n.changeLanguage('pt');
    await openBell();

    expect(await screen.findAllByRole('button', { name: 'Excluir notificação' })).toHaveLength(2);
  });

  it('shows the empty state in the user language', async () => {
    useNotificationsStore.setState({ notifications: [], unreadCount: 0 } as never);
    await i18n.changeLanguage('pt');
    const user = userEvent.setup();
    renderWithProviders(<NotificationBell />);
    await user.click(screen.getByRole('button'));

    expect(await screen.findByText('Nenhuma notificação')).toBeInTheDocument();
  });
});
