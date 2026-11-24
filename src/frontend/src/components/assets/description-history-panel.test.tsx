import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '@/i18n/config';

import { DescriptionHistoryPanel, hasDescriptionHistory } from './description-history-panel';

const getMock = vi.fn();
const postMock = vi.fn();
const toastMock = vi.fn();
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: getMock, post: postMock }) }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: toastMock }) }));

const entry = (n: number, over = {}) => ({
  id: `e${n}`,
  timestamp: '2026-11-20T10:00:00Z',
  username: `user${n}@example.com`,
  source: 'manual',
  object_type: 'table',
  before: `text ${n - 1}`,
  after: `text ${n}`,
  ...over,
});

function renderPanel(props = {}) {
  const onRestored = vi.fn();
  render(
    <DescriptionHistoryPanel
      assetId="a1" currentDescription="text 2" canRestore onRestored={onRestored} {...props}
    />
  );
  return { onRestored };
}

describe('hasDescriptionHistory', () => {
  it('applies to tables, views and columns', () => {
    expect(['Table', 'view', ' Column '].every(hasDescriptionHistory)).toBe(true);
    expect(hasDescriptionHistory('Dashboard')).toBe(false);
    expect(hasDescriptionHistory('Metric View')).toBe(false);
    expect(hasDescriptionHistory(null)).toBe(false);
  });
});

describe('DescriptionHistoryPanel', () => {
  beforeEach(() => {
    getMock.mockReset();
    postMock.mockReset();
    toastMock.mockReset();
  });

  afterEach(async () => {
    await act(async () => {
      await i18n.changeLanguage('en');
    });
  });

  it('lists who changed the description, from where, with the text before and after', async () => {
    getMock.mockResolvedValue({
      data: { asset_id: 'a1', total: 2, items: [entry(2, { source: 'uc_reset' }), entry(1)] },
    });
    renderPanel();

    expect(await screen.findByText('user2@example.com')).toBeInTheDocument();
    expect(screen.getByText('Unity Catalog comment')).toBeInTheDocument();
    expect(screen.getByText('Edit')).toBeInTheDocument();
    expect(getMock).toHaveBeenCalledWith('/api/assets/a1/description/history?skip=0&limit=5');
    expect(screen.getAllByText('text 1').length).toBeGreaterThan(0);
  });

  it('says so when nothing changed yet', async () => {
    getMock.mockResolvedValue({ data: { asset_id: 'a1', total: 0, items: [] } });
    renderPanel();

    expect(await screen.findByText('No changes to the description yet.')).toBeInTheDocument();
  });

  it('shows a load error', async () => {
    getMock.mockResolvedValue({ data: null, error: 'boom' });
    renderPanel();

    expect(await screen.findByRole('alert')).toHaveTextContent('boom');
  });

  it('restores the new text of an entry and reloads the asset', async () => {
    getMock.mockResolvedValue({ data: { asset_id: 'a1', total: 1, items: [entry(1)] } });
    postMock.mockResolvedValue({ data: { id: 'a1', warnings: [] } });
    const { onRestored } = renderPanel({ currentDescription: 'something else' });

    await userEvent.click(await screen.findByRole('button', { name: 'Restore the new text' }));

    await waitFor(() => expect(onRestored).toHaveBeenCalled());
    expect(postMock).toHaveBeenCalledWith('/api/assets/a1/description/restore', {
      entry_id: 'e1', version: 'after',
    });
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Description restored' })
    );
  });

  it('restores the previous text of an entry', async () => {
    getMock.mockResolvedValue({ data: { asset_id: 'a1', total: 1, items: [entry(1)] } });
    postMock.mockResolvedValue({ data: { id: 'a1', warnings: [] } });
    renderPanel({ currentDescription: 'something else' });

    await userEvent.click(
      await screen.findByRole('button', { name: 'Restore the previous text' })
    );

    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith('/api/assets/a1/description/restore', {
        entry_id: 'e1', version: 'before',
      })
    );
  });

  it('tells the user when Unity Catalog kept another comment', async () => {
    getMock.mockResolvedValue({ data: { asset_id: 'a1', total: 1, items: [entry(1)] } });
    postMock.mockResolvedValue({
      data: {
        id: 'a1',
        warnings: [{
          code: 'uc_description_existing_comment', message: 'english',
          params: { object: 'main.sales.orders' },
        }],
      },
    });
    renderPanel({ currentDescription: 'something else' });

    await userEvent.click(await screen.findByRole('button', { name: 'Restore the new text' }));

    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith(
        expect.objectContaining({
          description: expect.stringContaining('Unity Catalog already has another comment'),
        })
      )
    );
  });

  it('disables restoring the text the asset already has', async () => {
    getMock.mockResolvedValue({ data: { asset_id: 'a1', total: 1, items: [entry(2)] } });
    renderPanel({ currentDescription: 'text 2' });

    expect(await screen.findByRole('button', { name: 'Restore the new text' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Restore the previous text' })).toBeEnabled();
  });

  it('has no restore buttons without write access', async () => {
    getMock.mockResolvedValue({ data: { asset_id: 'a1', total: 1, items: [entry(1)] } });
    renderPanel({ canRestore: false });

    await screen.findByText('user1@example.com');
    expect(screen.queryByRole('button', { name: /Restore/ })).not.toBeInTheDocument();
  });

  it('shows a refused restore with its coded message and stays as it was', async () => {
    getMock.mockResolvedValue({ data: { asset_id: 'a1', total: 1, items: [entry(1)] } });
    postMock.mockResolvedValue({
      data: null, error: 'english', errorCode: 'description_history_entry_not_found',
    });
    const { onRestored } = renderPanel({ currentDescription: 'something else' });

    await userEvent.click(await screen.findByRole('button', { name: 'Restore the new text' }));

    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({
        variant: 'destructive',
        description: 'That change is not in the history of this asset.',
      }))
    );
    expect(onRestored).not.toHaveBeenCalled();
  });

  it('loads the next page', async () => {
    getMock
      .mockResolvedValueOnce({
        data: { asset_id: 'a1', total: 6, items: [1, 2, 3, 4, 5].map((n) => entry(n)) },
      })
      .mockResolvedValueOnce({ data: { asset_id: 'a1', total: 6, items: [entry(6)] } });
    renderPanel();

    await userEvent.click(await screen.findByRole('button', { name: 'Show 1 more' }));

    expect(await screen.findByText('user6@example.com')).toBeInTheDocument();
    expect(getMock).toHaveBeenLastCalledWith('/api/assets/a1/description/history?skip=5&limit=5');
    expect(screen.getByText('user1@example.com')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Show/ })).not.toBeInTheDocument();
  });

  it('speaks Portuguese', async () => {
    await act(async () => {
      await i18n.changeLanguage('pt');
    });
    getMock.mockResolvedValue({
      data: { asset_id: 'a1', total: 1, items: [entry(1, { source: 'restore' })] },
    });
    renderPanel();

    const title = await screen.findByText('Histórico da descrição');
    expect(title).toBeInTheDocument();
    expect(screen.getByText('Restauração')).toBeInTheDocument();
    expect(within(document.body).getByRole('button', { name: 'Restaurar o texto novo' }))
      .toBeInTheDocument();
  });
});
