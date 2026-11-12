/**
 * Enabling workflows from the list: an overlap (409) asks for confirmation, a
 * refused activation (`workflow_invalid`, e.g. a policy_check step without an
 * existing policy) is a failure that shows its translated reason.
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

const base = {
  is_active: false, is_default: false,
  trigger: { type: 'on_request_review', entity_types: ['data_contract'] },
  steps: [{ id: 'row-1', step_id: 's1', name: 'Notify', step_type: 'notification', order: 1 }],
};
const WORKFLOWS = [
  { ...base, id: 'wf-overlap', name: 'Overlapping review' },
  { ...base, id: 'wf-invalid', name: 'Unrunnable gate' },
  { ...base, id: 'wf-ok', name: 'Plain review' },
];

const json = (status: number, body: unknown) => ({
  ok: status < 400, status, json: async () => body,
});
const OVERLAP = json(409, {
  detail: {
    code: 'workflow_activation_overlap',
    params: { conflicts: [{
      id: 'active-1', name: 'Active review', trigger_type: 'on_request_review',
      entity_types: ['data_contract'], scope_type: 'all',
    }] },
  },
});
const REFUSAL = json(400, {
  detail: {
    code: 'workflow_invalid',
    message: "Step 'naming-check': the policy to check is not selected",
    params: { issues: [{
      code: 'policy_check_policy_missing',
      message: "Step 'naming-check': the policy to check is not selected",
      params: { step: 'naming-check', policyId: '' },
    }] },
  },
});

function mockServer() {
  get.mockImplementation(async (url: string) => {
    if (url.startsWith('/api/workflows/executions')) return { data: { executions: [], total: 0 } };
    if (url.startsWith('/api/workflows')) return { data: { workflows: WORKFLOWS, total: 3 } };
    return { data: { sessions: [], total: 0 } };
  });
  const fetchMock = vi.fn(async (url: string) => {
    const id = WORKFLOWS.find(w => url.includes(`/${w.id}/`))!.id;
    if (id === 'wf-invalid') return REFUSAL;
    if (id === 'wf-overlap' && !url.includes('confirm_overlap=true')) return OVERLAP;
    return json(200, { ...WORKFLOWS.find(w => w.id === id), is_active: true });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

const toastWith = (variant: string | undefined) =>
  toastMock.mock.calls.map(([arg]) => arg).filter(arg => arg.variant === variant);

describe('Workflows list activation refusals', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
    get.mockReset();
    toastMock.mockReset();
    vi.unstubAllGlobals();
  });

  it('bulk enable: overlap to the dialog, refusal as a failure with its reason', async () => {
    const fetchMock = mockServer();
    const user = userEvent.setup();
    render(<MemoryRouter><Workflows /></MemoryRouter>);
    await screen.findByText('Plain review');
    await user.click(screen.getByRole('checkbox', { name: /select all/i }));
    await user.click(screen.getByRole('button', { name: 'Enable (3)' }));

    // only the overlapping workflow asks for confirmation
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Overlapping review')).toBeInTheDocument();
    expect(within(dialog).queryByText('Unrunnable gate')).toBeNull();
    expect(within(dialog).queryByText('Plain review')).toBeNull();

    await waitFor(() => expect(toastWith('destructive')).toHaveLength(1));
    expect(toastWith(undefined).map(arg => arg.description)).toEqual(['1 workflow enabled.']);
    const [failure] = toastWith('destructive');
    expect(failure.description).toBe(
      '1 workflow failed to update. Unrunnable gate: Step "naming-check" needs an existing '
      + "compliance policy. Select one in the step's settings.",
    );

    await user.click(within(dialog).getByRole('button', { name: 'Activate anyway' }));
    await waitFor(() => expect(toastWith(undefined)).toHaveLength(2));
    expect(toastWith(undefined)[1].description).toBe('1 workflow enabled.');
    expect(toastWith('destructive')).toHaveLength(1);
    const confirmed = fetchMock.mock.calls.map(([url]) => url)
      .filter(url => url.includes('confirm_overlap=true'));
    expect(confirmed).toEqual([
      '/api/workflows/wf-overlap/toggle-active?is_active=true&confirm_overlap=true',
    ]);
  });

  it('single toggle: a refusal shows its reason in Portuguese, without a dialog', async () => {
    mockServer();
    await i18n.changeLanguage('pt');
    const user = userEvent.setup();
    render(<MemoryRouter><Workflows /></MemoryRouter>);
    const row = (await screen.findByText('Unrunnable gate')).closest('tr')!;
    await user.click(within(row).getByRole('switch'));

    await waitFor(() => expect(toastWith('destructive')).toHaveLength(1));
    expect(toastWith('destructive')[0].description).toBe(
      'A etapa "naming-check" precisa de uma política de conformidade existente. '
      + 'Selecione uma nas configurações da etapa.',
    );
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
