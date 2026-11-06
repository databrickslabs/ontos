/** After an import, the selection can be saved as a connector sync. */
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import i18n from '@/i18n/config';
import { renderWithProviders } from '@/test/utils';
import KeepInSyncPanel from './keep-in-sync-panel';

const api = vi.hoisted(() => ({ post: vi.fn() }));
vi.mock('@/hooks/use-api', () => ({ useApi: () => api }));

const renderPanel = (selectedPaths = ['p~p1']) => renderWithProviders(
  <KeepInSyncPanel connectionId="c-1" selectedPaths={selectedPaths} depth="full_recursive"
    excludedPaths={['p~p1.p~p2']} defaultName="Finance" />,
);

describe('KeepInSyncPanel', () => {
  beforeEach(() => api.post.mockReset());

  it('saves the selection with the chosen schedule', async () => {
    api.post.mockResolvedValue({ data: { id: 's-1', name: 'Finance', next_due_at: new Date().toISOString(), job_warning: null } });
    renderPanel();

    fireEvent.click(screen.getByRole('button', { name: i18n.t('database-schema:sync.keepInSync') }));
    fireEvent.change(screen.getByLabelText(i18n.t('database-schema:sync.retireAfter')), { target: { value: '5' } });
    fireEvent.click(screen.getByRole('button', { name: i18n.t('database-schema:sync.save') }));

    await waitFor(() => expect(screen.getByTestId('keep-in-sync-saved')).toBeInTheDocument());
    expect(api.post).toHaveBeenCalledWith('/api/connector-syncs', {
      name: 'Finance', connection_id: 'c-1', selected_paths: ['p~p1'], depth: 'full_recursive',
      excluded_paths: ['p~p1.p~p2'], interval_minutes: 1440, retire_after_misses: 5,
    });
  });

  it('shows why the schedule is not running', async () => {
    api.post.mockResolvedValue({ data: { id: 's-1', name: 'Finance', job_warning: 'enable it in Settings → Jobs' } });
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: i18n.t('database-schema:sync.keepInSync') }));
    fireEvent.click(screen.getByRole('button', { name: i18n.t('database-schema:sync.save') }));
    expect(await screen.findByText('enable it in Settings → Jobs')).toBeInTheDocument();
  });

  it('offers nothing without a selection', () => {
    renderPanel([]);
    expect(screen.queryByRole('button', { name: i18n.t('database-schema:sync.keepInSync') })).not.toBeInTheDocument();
  });
});
