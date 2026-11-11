/**
 * The executions list and the workflows list show the entity type and the
 * step type in the UI language, not the raw backend value.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

const get = vi.fn();
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get, post: vi.fn(), delete: vi.fn() }) }));
vi.mock('@/stores/permissions-store', async (orig) => {
  const actual = await orig<Record<string, unknown>>();
  return { ...actual, usePermissions: () => ({ hasPermission: () => true }) };
});

vi.mock('@/components/settings/settings-page-wrapper', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

import i18n from '@/i18n/config';
import Workflows from './workflows';

const WORKFLOW = {
  id: 'wf-1', name: 'Data Contract Review Request', is_active: true, is_default: false,
  trigger: { type: 'on_request_review', entity_types: ['data_contract'] },
  steps: [{ id: 'row-1', step_id: 's1', name: 'Notify', step_type: 'notification', order: 1 }],
};
const EXECUTION = {
  id: 'ex-1', workflow_id: 'wf-1', workflow_name: 'Data Contract Review Request',
  status: 'paused', entity_type: 'data_contract', entity_name: 'orders', entity_id: 'c-1',
  success_count: 0, failure_count: 0, step_executions: [],
};

function mockApi() {
  get.mockImplementation(async (url: string) => {
    if (url.startsWith('/api/workflows/executions')) return { data: { executions: [EXECUTION], total: 1 } };
    if (url.startsWith('/api/workflows')) return { data: { workflows: [WORKFLOW], total: 1 } };
    return { data: { sessions: [], total: 0 } };
  });
}

describe('Workflows view labels', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
    get.mockReset();
    vi.unstubAllGlobals();
  });

  it('shows the entity type and the step type tooltip in Portuguese', async () => {
    mockApi();
    await i18n.changeLanguage('pt');
    const { container } = render(<MemoryRouter><Workflows /></MemoryRouter>);
    expect(await screen.findByText('Contrato')).toBeInTheDocument();
    await waitFor(() => expect(container.querySelector('[title="Notificação"]')).not.toBeNull());
    expect(screen.queryByText('data_contract')).toBeNull();
  });

  it('shows them in English', async () => {
    mockApi();
    const { container } = render(<MemoryRouter><Workflows /></MemoryRouter>);
    expect(await screen.findByText('Contract')).toBeInTheDocument();
    await waitFor(() => expect(container.querySelector('[title="Notification"]')).not.toBeNull());
  });

  it('collects every bulk activation conflict and localizes its labels', async () => {
    const workflows = [
      { ...WORKFLOW, id: 'wf-a', name: 'Review A', is_active: false },
      { ...WORKFLOW, id: 'wf-b', name: 'Review B', is_active: false },
    ];
    get.mockImplementation(async (url: string) => {
      if (url.startsWith('/api/workflows/executions')) return { data: { executions: [], total: 0 } };
      if (url.startsWith('/api/workflows')) return { data: { workflows, total: workflows.length } };
      return { data: { sessions: [], total: 0 } };
    });
    const fetchMock = vi.fn(async (url: string) => {
      const workflowId = url.includes('wf-a') ? 'wf-a' : 'wf-b';
      return {
        ok: false,
        status: 409,
        json: async () => ({
          detail: {
            code: 'workflow_activation_overlap',
            params: { conflicts: [{
              id: `active-${workflowId}`,
              name: `Active ${workflowId}`,
              trigger_type: 'on_request_review',
              entity_types: ['data_contract'],
              scope_type: 'all',
            }] },
          },
        }),
      };
    });
    vi.stubGlobal('fetch', fetchMock);

    const user = userEvent.setup();
    render(<MemoryRouter><Workflows /></MemoryRouter>);
    await screen.findByText('Review A');
    await user.click(screen.getByRole('checkbox', { name: /select all/i }));
    await user.click(screen.getByRole('button', { name: 'Enable (2)' }));

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Review A')).toBeInTheDocument();
    expect(within(dialog).getByText('Review B')).toBeInTheDocument();
    expect(within(dialog).getAllByText(/Trigger: Review Request/)).toHaveLength(2);
    expect(within(dialog).getAllByText(/Entities: Contract/)).toHaveLength(2);
    expect(within(dialog).queryByText(/on_request_review/)).toBeNull();
    expect(within(dialog).queryByText(/data_contract/)).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
