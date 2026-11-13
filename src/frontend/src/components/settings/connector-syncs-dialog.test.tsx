/** The syncs of a connection: run now, enable/disable, delete. */
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import i18n from '@/i18n/config';
import { renderWithProviders } from '@/test/utils';
import type { Connection } from '@/types/connections';
import { ConnectorSyncsDialog } from './connector-syncs-dialog';

const api = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() }));
vi.mock('@/hooks/use-api', () => ({ useApi: () => api }));
vi.mock('@/stores/permissions-store', () => ({ usePermissions: () => ({ hasPermission: () => true }) }));

const CONNECTION = { id: 'c-1', name: 'Tableau Cloud' } as Connection;
const SYNC = {
  id: 's-1', name: 'Finance', connection_id: 'c-1', selected_paths: ['p~p1'], depth: 'full_recursive',
  excluded_paths: [], interval_minutes: 1440, retire_after_misses: 3, enabled: true,
  last_status: 'incomplete', last_run_at: new Date().toISOString(), last_run_id: 'r-1',
  next_due_at: new Date().toISOString(),
};

describe('ConnectorSyncsDialog', () => {
  beforeEach(() => {
    Object.values(api).forEach((fn) => fn.mockReset());
    api.get.mockResolvedValue({ data: [SYNC] });
  });

  it('lists the syncs with their last run', async () => {
    renderWithProviders(<ConnectorSyncsDialog connection={CONNECTION} onOpenChange={() => {}} />);
    expect(await screen.findByText('Finance')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/api/connector-syncs?connection_id=c-1');
    expect(screen.getByText(i18n.t('settings:connectors.syncs.status.incomplete'))).toBeInTheDocument();
    expect(screen.getByText(new RegExp(i18n.t('database-schema:sync.intervals.1440')))).toBeInTheDocument();
  });

  it('runs a sync now and disables it', async () => {
    api.post.mockResolvedValue({ data: { job_run_id: 7 } });
    api.put.mockResolvedValue({ data: { ...SYNC, enabled: false, next_due_at: null } });
    renderWithProviders(<ConnectorSyncsDialog connection={CONNECTION} onOpenChange={() => {}} />);

    fireEvent.click(await screen.findByRole('button', { name: i18n.t('settings:connectors.syncs.runNow') }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/connector-syncs/s-1/run', {}));

    fireEvent.click(screen.getByRole('switch', { name: i18n.t('settings:connectors.syncs.enabled') }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith('/api/connector-syncs/s-1', { enabled: false }));
    await waitFor(() => expect(screen.getByRole('switch')).not.toBeChecked());
  });

  it('deletes a sync', async () => {
    api.delete.mockResolvedValue({});
    renderWithProviders(<ConnectorSyncsDialog connection={CONNECTION} onOpenChange={() => {}} />);
    fireEvent.click(await screen.findByRole('button', { name: i18n.t('common:delete') }));
    await waitFor(() => expect(screen.getByText(i18n.t('settings:connectors.syncs.none'))).toBeInTheDocument());
  });
});
