/**
 * Settings dialog: loads the admin settings, and saves the edited limits,
 * switches and endpoint list (one per line or comma-separated).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SettingsDialog from './settings-dialog';

const api = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));
const toast = vi.hoisted(() => vi.fn());

vi.mock('@/hooks/use-api', () => ({ useApi: () => api }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast }) }));

const SETTINGS = {
  max_tables_per_run: 500,
  max_active_runs_per_user: 1,
  allow_data_sampling: false,
  sample_size: 5,
  send_column_metadata: true,
  allowed_endpoints: ['other-endpoint'],
  default_endpoint: 'my-endpoint',
  endpoints: ['my-endpoint', 'other-endpoint'],
};

describe('SettingsDialog', () => {
  beforeEach(() => {
    api.get.mockReset().mockResolvedValue({ data: SETTINGS });
    api.put.mockReset().mockResolvedValue({ data: SETTINGS });
    toast.mockReset();
  });

  it('saves the edited settings', async () => {
    const onOpenChange = vi.fn();
    render(<SettingsDialog isOpen onOpenChange={onOpenChange} />);

    const maxTables = await screen.findByLabelText('Tables per run');
    expect(maxTables).toHaveValue(500);
    expect(screen.getByText(/default endpoint, my-endpoint, is always allowed/)).toBeInTheDocument();
    await userEvent.clear(maxTables);
    await userEvent.type(maxTables, '50');
    await userEvent.click(screen.getByLabelText('Send column statistics'));
    await userEvent.click(screen.getByLabelText('Allow sample data'));
    const endpoints = screen.getByLabelText('Additional serving endpoints');
    await userEvent.clear(endpoints);
    await userEvent.type(endpoints, 'a-endpoint, b-endpoint{enter}c-endpoint');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    expect(api.put).toHaveBeenCalledWith('/api/metadata-generation/settings', {
      max_tables_per_run: 50,
      max_active_runs_per_user: 1,
      allow_data_sampling: true,
      sample_size: 5,
      send_column_metadata: false,
      allowed_endpoints: ['a-endpoint', 'b-endpoint', 'c-endpoint'],
    });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('shows the API error and stays open', async () => {
    api.put.mockResolvedValue({ data: null, error: "'bad name' is not a valid serving endpoint name" });
    const onOpenChange = vi.fn();
    render(<SettingsDialog isOpen onOpenChange={onOpenChange} />);

    await screen.findByLabelText('Tables per run');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByText(/not a valid serving endpoint name/)).toBeInTheDocument();
    expect(onOpenChange).not.toHaveBeenCalled();
  });
});
