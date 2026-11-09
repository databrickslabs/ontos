/**
 * Git settings with a volume that isn't mounted (#75): the working copy is
 * shown, and coded errors are shown in the user's language.
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

function respond(routes: Record<string, { ok?: boolean; body: unknown }>) {
  globalThis.fetch = vi.fn(async (url: RequestInfo | URL) => {
    const route = routes[String(url)];
    if (!route) throw new Error(`unexpected fetch ${String(url)}`);
    return {
      ok: route.ok ?? true,
      json: async () => route.body,
    } as Response;
  }) as unknown as typeof fetch;
}

const settings = { body: { git_repo_url: 'https://example.com/gov.git', git_branch: 'main' } };

describe('GitSettings', () => {
  beforeEach(async () => {
    toast.mockReset();
    await i18n.changeLanguage('pt');
  });

  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('shows an invalid volume setting in the user\'s language', async () => {
    respond({
      '/api/settings': settings,
      '/api/settings/git/status': {
        body: {
          clone_status: 'error',
          pending_changes_count: 0,
          changed_files: [],
          error_message: "The volume setting must be ...; got 'main.gov'",
          error_code: 'git_volume_invalid',
          error_params: { value: 'main.gov' },
        },
      },
    });

    render(<GitSettings />);

    expect(await screen.findByText(/A configuração de volume "main.gov" não indica um volume/))
      .toBeInTheDocument();
  });

  it('translates a coded clone error in the toast', async () => {
    respond({
      '/api/settings': settings,
      '/api/settings/git/status': {
        body: { clone_status: 'not_cloned', pending_changes_count: 0, changed_files: [] },
      },
      '/api/settings/git/clone': {
        ok: false,
        body: {
          detail: {
            code: 'git_volume_invalid',
            message: "The volume setting must be ...; got 'x y'",
            params: { value: 'x y' },
          },
        },
      },
    });

    render(<GitSettings />);
    fireEvent.click(await screen.findByRole('button', { name: /Clonar|Clone/ }));

    await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.objectContaining({
      variant: 'destructive',
      description: expect.stringContaining('A configuração de volume "x y"'),
    })));
  });

  it('shows the local working copy and a failed volume write', async () => {
    respond({
      '/api/settings': settings,
      '/api/settings/git/status': {
        body: {
          clone_status: 'cloned',
          pending_changes_count: 1,
          changed_files: [],
          volume_path: '/Volumes/main/gov/exports/git-export',
          working_copy_path: '/tmp/ontos/git-export/main.gov.exports',
          volume_sync_error_code: 'git_volume_sync_failed',
          volume_sync_error_params: { path: '/Volumes/main/gov/exports/git-export/orders.yaml' },
        },
      },
    });

    render(<GitSettings />);

    expect(await screen.findByText('/tmp/ontos/git-export/main.gov.exports')).toBeInTheDocument();
    expect(screen.getByText(/Cópia de trabalho/)).toBeInTheDocument();
    expect(screen.getByText('Exportação não gravada no volume')).toBeInTheDocument();
    expect(screen.getByText(
      /Não foi possível gravar \/Volumes\/main\/gov\/exports\/git-export\/orders.yaml no volume/,
    )).toBeInTheDocument();
  });
});
