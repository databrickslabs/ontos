import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FeatureAccessLevel } from '@/types/settings';

let canWrite = true;
vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({
    hasPermission: (_feature: string, level: FeatureAccessLevel) =>
      level === FeatureAccessLevel.READ_ONLY || canWrite,
  }),
}));

const toastMock = vi.fn();
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: toastMock }) }));

import GeneralSettings from './general-settings';

const baseResponse = {
  databricks_catalog: 'c',
  databricks_schema: 's',
  databricks_volume: 'v',
  app_audit_log_dir: 'audit',
  schema_import_child_limit: 500,
  ontos_instance_id: '123-ontos',
  ontos_instance_name: 'ontos',
  ontos_instance_id_default: '123-ontos',
  ontos_instance_name_default: 'ontos',
};

let fetchMock: ReturnType<typeof vi.fn>;

function mockFetch(getBody: Record<string, unknown> = baseResponse) {
  fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'PUT') return { ok: true, json: async () => ({}) } as Response;
    return { ok: true, json: async () => getBody } as Response;
  });
  vi.stubGlobal('fetch', fetchMock);
}

function lastPutBody() {
  const puts = fetchMock.mock.calls.filter(([, init]) => init?.method === 'PUT');
  const call = puts[puts.length - 1];
  return JSON.parse(call![1].body as string);
}

describe('GeneralSettings - instance identity', () => {
  beforeEach(() => {
    canWrite = true;
    toastMock.mockClear();
  });
  afterEach(() => vi.unstubAllGlobals());

  it('renders the current instance id and name', async () => {
    mockFetch();
    render(<GeneralSettings />);
    expect(await screen.findByLabelText('Instance ID')).toHaveValue('123-ontos');
    expect(screen.getByLabelText('Instance Name')).toHaveValue('ontos');
  });

  it('does not pin the defaults when the fields are untouched', async () => {
    mockFetch();
    render(<GeneralSettings />);
    await screen.findByLabelText('Instance ID');
    await userEvent.click(screen.getByRole('button', { name: /save settings/i }));
    await waitFor(() => expect(lastPutBody()).toBeDefined());
    expect(lastPutBody().ontos_instance_id).toBe('');
    expect(lastPutBody().ontos_instance_name).toBe('');
  });

  it('edits and saves overrides', async () => {
    mockFetch();
    render(<GeneralSettings />);
    const id = await screen.findByLabelText('Instance ID');
    const name = screen.getByLabelText('Instance Name');
    await userEvent.clear(id);
    await userEvent.type(id, 'estate-eu-1');
    await userEvent.clear(name);
    await userEvent.type(name, 'EU Estate');
    await userEvent.click(screen.getByRole('button', { name: /save settings/i }));
    await waitFor(() => expect(lastPutBody().ontos_instance_id).toBe('estate-eu-1'));
    expect(lastPutBody().ontos_instance_name).toBe('EU Estate');
  });

  it('blocks saving an invalid id and shows the validation message', async () => {
    mockFetch();
    render(<GeneralSettings />);
    const id = await screen.findByLabelText('Instance ID');
    await userEvent.clear(id);
    await userEvent.type(id, 'bad id!');
    expect(screen.getByText(/Use 1-128 letters, digits/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /save settings/i }));
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PUT')).toBe(false);
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: 'destructive' }));
  });

  it('shows a server-side coded rejection translated', async () => {
    fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        return {
          ok: false,
          json: async () => ({
            detail: { code: 'instance_id_invalid', message: 'english fallback', params: { max_length: 128 } },
          }),
        } as Response;
      }
      return { ok: true, json: async () => baseResponse } as Response;
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<GeneralSettings />);
    await screen.findByLabelText('Instance ID');
    await userEvent.click(screen.getByRole('button', { name: /save settings/i }));
    await waitFor(() => expect(toastMock).toHaveBeenCalled());
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({
        variant: 'destructive',
        description: expect.stringContaining('Use 1-128 letters, digits'),
      })
    );
  });

  it('maps instance_name_invalid to the length and control-character message', async () => {
    fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        return {
          ok: false,
          json: async () => ({
            detail: { code: 'instance_name_invalid', message: 'english fallback', params: { max_length: 128 } },
          }),
        } as Response;
      }
      return { ok: true, json: async () => baseResponse } as Response;
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<GeneralSettings />);
    await screen.findByLabelText('Instance Name');
    await userEvent.click(screen.getByRole('button', { name: /save settings/i }));
    await waitFor(() => expect(toastMock).toHaveBeenCalled());
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({
        variant: 'destructive',
        description: 'Use at most 128 characters, without control characters.',
      })
    );
  });

  it('is read-only for users without write access', async () => {
    canWrite = false;
    mockFetch();
    render(<GeneralSettings />);
    expect(await screen.findByLabelText('Instance ID')).toBeDisabled();
    expect(screen.getByLabelText('Instance Name')).toBeDisabled();
    expect(screen.queryByRole('button', { name: /save settings/i })).not.toBeInTheDocument();
  });
});

describe('GeneralSettings - write asset descriptions to Unity Catalog', () => {
  beforeEach(() => {
    canWrite = true;
    toastMock.mockClear();
  });
  afterEach(() => vi.unstubAllGlobals());

  it('is off by default and saves the switch', async () => {
    mockFetch();
    render(<GeneralSettings />);
    const toggle = await screen.findByLabelText('Write asset descriptions to Unity Catalog');
    expect(toggle).not.toBeChecked();
    await userEvent.click(toggle);
    await userEvent.click(screen.getByRole('button', { name: /save settings/i }));
    await waitFor(() => expect(lastPutBody().uc_description_writeback_enabled).toBe(true));
  });

  it('saves the bulk import write limit', async () => {
    mockFetch({ ...baseResponse, uc_description_writeback_enabled: true,
      uc_description_import_write_limit: 100 });
    render(<GeneralSettings />);
    const limit = await screen.findByLabelText('Max descriptions written per bulk import');
    expect(limit).toHaveValue(100);
    await userEvent.clear(limit);
    await userEvent.type(limit, '25');
    await userEvent.click(screen.getByRole('button', { name: /save settings/i }));
    await waitFor(() => expect(lastPutBody().uc_description_import_write_limit).toBe(25));
  });

  it('shows the stored value', async () => {
    mockFetch({ ...baseResponse, uc_description_writeback_enabled: true });
    render(<GeneralSettings />);
    expect(
      await screen.findByLabelText('Write asset descriptions to Unity Catalog')
    ).toBeChecked();
  });
});
