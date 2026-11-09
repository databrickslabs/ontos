/**
 * The domain sync page and its result summary are in the user's language.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import i18n from '@/i18n/config';
import SyncDomainsView, { syncSummaryText } from './sync-domains';

const api = vi.hoisted(() => ({
  get: async () => ({ data: [] }),
  post: async () => ({ data: null }),
  toast: () => {},
}));

vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: api.get, post: api.post }) }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: api.toast }) }));

afterEach(async () => {
  await i18n.changeLanguage('en');
});

describe('syncSummaryText', () => {
  const result = { created: 2, matched: 1, skipped: 0, errors: 0 };

  it('is one sentence in Portuguese, with the errors only when there were any', async () => {
    await i18n.changeLanguage('pt');
    expect(syncSummaryText(result, i18n.t)).toBe('Criados: 2, vinculados: 1, ignorados: 0.');
    expect(syncSummaryText({ ...result, errors: 3 }, i18n.t)).toBe(
      'Criados: 2, vinculados: 1, ignorados: 0, erros: 3.',
    );
  });

  it('keeps the English sentence in English', () => {
    expect(syncSummaryText(result, i18n.t)).toBe('Created: 2, matched: 1, skipped: 0.');
  });
});

describe('SyncDomainsView', () => {
  it('shows the page in Portuguese', async () => {
    await i18n.changeLanguage('pt');
    render(<SyncDomainsView />);

    expect(await screen.findByRole('heading', { name: 'Sincronizar domínios' })).toBeInTheDocument();
    expect(screen.getByText('Importar do Unity Catalog')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Pré-visualizar' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Aplicar' })).toBeInTheDocument();
    expect(screen.queryByText('Preview')).not.toBeInTheDocument();
  });

  it('describes the export flow, anchor and top-level target after switching direction', async () => {
    render(<SyncDomainsView />);
    expect(await screen.findByText('Place under')).toBeInTheDocument();
    expect(screen.getByText('Unity Catalog → Ontos')).toBeInTheDocument();
    expect(screen.getByText('Top level (no parent)')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('radio', { name: /Export to Unity Catalog/ }));

    expect(await screen.findByText('Anchor')).toBeInTheDocument();
    expect(screen.getByText('Its children become UC roots; grandchildren become subdomains.')).toBeInTheDocument();
    expect(screen.getByText('Ontos → Unity Catalog')).toBeInTheDocument();
    expect(screen.getByText('Top-level domains')).toBeInTheDocument();
    expect(screen.queryByText('Place under')).not.toBeInTheDocument();
  });
});
