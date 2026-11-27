/**
 * Activating a workflow with an Evaluate Asset Maturity step needs write access to
 * Settings (#1414 follow-up): the 403 `workflow_step_requires_settings_write` shows its
 * translated text and the workflow stays inactive; another 403 is the generic failure.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

const get = vi.fn();
const toastMock = vi.fn();
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get, post: vi.fn(), delete: vi.fn() }) }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: toastMock }) }));
vi.mock('@/stores/permissions-store', async (orig) => {
  const actual = await orig<Record<string, unknown>>();
  return { ...actual, usePermissions: () => ({ hasPermission: () => true }) };
});
vi.mock('@/components/settings/settings-page-wrapper', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

import i18n from '@/i18n/config';
import Workflows from './workflows';

const NIGHTLY = {
  id: 'wf-nightly', name: 'Nightly Asset Maturity Evaluation', is_active: false,
  is_default: true,
  trigger: { type: 'scheduled', entity_types: [], schedule: '0 0 2 * * ?', timezone: 'UTC' },
  steps: [{
    id: 'row-1', step_id: 'evaluate-assets', name: 'Evaluate Asset Maturity',
    step_type: 'evaluate_asset_maturity', order: 0,
  }],
};

const forbidden = (code: string) => ({
  ok: false, status: 403,
  json: async () => ({ detail: { code, message: 'requires write access', params: {} } }),
});

function mockServer(code: string) {
  get.mockImplementation(async (url: string) => {
    if (url.startsWith('/api/workflows/executions')) return { data: { executions: [], total: 0 } };
    if (url.startsWith('/api/workflows')) return { data: { workflows: [NIGHTLY], total: 1 } };
    return { data: { sessions: [], total: 0 } };
  });
  const fetchMock = vi.fn(async () => forbidden(code));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

async function toggleNightly() {
  const user = userEvent.setup();
  render(<MemoryRouter><Workflows /></MemoryRouter>);
  const row = (await screen.findByText(NIGHTLY.name)).closest('tr')!;
  const toggle = within(row).getByRole('switch');
  await user.click(toggle);
  return toggle;
}

const destructive = () =>
  toastMock.mock.calls.map(([arg]) => arg).filter(arg => arg.variant === 'destructive');

describe('Workflows list: activating the asset maturity workflow', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
    get.mockReset();
    toastMock.mockReset();
    vi.unstubAllGlobals();
  });

  it('shows the translated Settings refusal and keeps the workflow inactive', async () => {
    await i18n.changeLanguage('pt');
    const fetchMock = mockServer('workflow_step_requires_settings_write');

    const toggle = await toggleNightly();

    await waitFor(() => expect(destructive()).toHaveLength(1));
    expect(destructive()[0].description).toBe(
      'Este workflow executa a avaliação de maturidade dos assets. '
      + 'Salvá-lo, ativá-lo ou executá-lo exige acesso de escrita em Configurações.',
    );
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/workflows/wf-nightly/toggle-active?is_active=true', expect.anything(),
    );
    expect(toggle).not.toBeChecked();
  });

  it('answers another 403 with the generic failure', async () => {
    mockServer('some_other_code');

    await toggleNightly();

    await waitFor(() => expect(destructive()).toHaveLength(1));
    expect(destructive()[0].description).toBe('Failed to update workflow status');
  });
});
