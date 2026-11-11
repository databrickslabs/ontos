/**
 * The Git token is write-only: the page never gets it back, so saving the
 * form without retyping it must keep the saved token.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const toast = vi.fn();
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast }) }));
vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({ hasPermission: () => true }),
}));

import i18n from '@/i18n/config';
import GitSettings from './git-settings';

let puts: Record<string, unknown>[] = [];

function serve(tokenSaved: boolean) {
  puts = [];
  globalThis.fetch = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const path = String(url);
    if (path === '/api/settings' && init?.method === 'PUT') {
      puts.push(JSON.parse(String(init.body)));
      return { ok: true, json: async () => ({}) } as Response;
    }
    if (path === '/api/settings') {
      return {
        ok: true,
        json: async () => ({
          git_repo_url: 'https://example.com/gov.git',
          git_branch: 'main',
          git_username: 'x-access-token',
          git_password_set: tokenSaved,
        }),
      } as Response;
    }
    if (path === '/api/settings/git/status') {
      return {
        ok: true,
        json: async () => ({ clone_status: 'not_cloned', pending_changes_count: 0, changed_files: [] }),
      } as Response;
    }
    throw new Error(`unexpected fetch ${path}`);
  }) as unknown as typeof fetch;
}

describe('GitSettings token', () => {
  beforeEach(async () => {
    toast.mockReset();
    await i18n.changeLanguage('pt');
  });

  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('keeps the saved token when the form is saved without retyping it', async () => {
    serve(true);
    render(<GitSettings />);

    const token = await screen.findByPlaceholderText('Salvo. Deixe vazio para mantê-lo.');
    expect(token).toHaveValue('');
    fireEvent.click(screen.getByRole('button', { name: /Salvar|Save/ }));

    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]).not.toHaveProperty('git_password');
    expect(puts[0]).toMatchObject({ git_username: 'x-access-token' });
  });

  it('sends a token that was typed', async () => {
    serve(false);
    render(<GitSettings />);

    const token = await screen.findByLabelText(/Token/);
    fireEvent.change(token, { target: { name: 'gitToken', value: 'ghp_new' } });
    fireEvent.click(screen.getByRole('button', { name: /Salvar|Save/ }));

    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]).toMatchObject({ git_password: 'ghp_new' });
  });

  it('removes the saved token on request', async () => {
    serve(true);
    render(<GitSettings />);

    fireEvent.click(await screen.findByRole('button', { name: 'Remover token salvo' }));

    await waitFor(() => expect(puts).toEqual([{ git_password_clear: true }]));
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Remover token salvo' })).not.toBeInTheDocument(),
    );
  });
});
