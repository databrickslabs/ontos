/** A 403 from the approvals queue is an empty queue; other failures show the translated error. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/utils';
import i18n from '@/i18n/config';

vi.mock('@/stores/notifications-store', () => ({
  useNotificationsStore: () => ({
    notifications: [],
    isLoading: false,
    fetchNotifications: vi.fn(),
    markAsRead: vi.fn(),
  }),
}));

import RequiredActionsSection from './required-actions-section';

const respond = (status: number, body: unknown = {}) =>
  vi.fn(async () => ({ ok: status < 400, status, json: async () => body }));

describe('RequiredActionsSection approvals queue', () => {
  beforeEach(() => {
    globalThis.fetch = respond(200) as any;
  });

  it('shows the empty state, not the HTTP status, on 403', async () => {
    globalThis.fetch = respond(403, { detail: 'forbidden' }) as any;
    renderWithProviders(<RequiredActionsSection />);
    expect(await screen.findByText('No pending actions.')).toBeTruthy();
    expect(screen.queryByText(/HTTP/)).toBeNull();
    expect(document.querySelector('.text-destructive')).toBeNull();
  });

  it('shows the loading state, not the empty state, until the queue answers', async () => {
    let release: (v: any) => void = () => {};
    globalThis.fetch = vi.fn(() => new Promise((r) => { release = r; })) as any;
    const { container } = renderWithProviders(<RequiredActionsSection />);
    expect(screen.queryByText('No pending actions.')).toBeNull();
    expect(container.querySelector('table')).toBeNull();
    release({
      ok: true,
      status: 200,
      json: async () => ({
        contracts: [{ id: 'c1', name: 'Contract One', status: 'draft' }],
        products: [],
      }),
    });
    expect(await screen.findByText('Contract One')).toBeTruthy();
    expect(screen.queryByText('No pending actions.')).toBeNull();
  });

  it('shows the translated error, not the HTTP status, on 500', async () => {
    globalThis.fetch = respond(500) as any;
    renderWithProviders(<RequiredActionsSection />);
    expect(await screen.findByText('Failed to load approvals')).toBeTruthy();
    expect(screen.queryByText(/HTTP/)).toBeNull();
  });

  it('shows the error in the new language after a language switch', async () => {
    globalThis.fetch = respond(500) as any;
    renderWithProviders(<RequiredActionsSection />);
    expect(await screen.findByText('Failed to load approvals')).toBeTruthy();
    try {
      await act(async () => { await i18n.changeLanguage('pt'); });
      expect(await screen.findByText('Falha ao carregar aprovações')).toBeTruthy();
      expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    } finally {
      await act(async () => { await i18n.changeLanguage('en'); });
    }
  });
});
