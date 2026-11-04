/**
 * The approval step's form sets "require every approver" (require_all, #1119)
 * and says that its timeout isn't enforced yet; a timeout of 0 (no timeout) is
 * kept, an empty one means the default of 7 days.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import i18n from '@/i18n/config';
import WorkflowDesigner from './workflow-designer';

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), toast: vi.fn() }));

vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: api.get, post: api.post, put: api.put }),
}));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: api.toast }) }));
vi.mock('./template-vars-inspector', () => ({ default: () => null }));

function workflowWith(config: Record<string, unknown>) {
  return {
    id: 'wf-1', name: 'Review', description: '', is_active: true, workflow_type: 'process',
    trigger: { type: 'manual', entity_types: ['data_product'] },
    steps: [
      {
        step_id: 'approve', name: 'Approve', step_type: 'approval', order: 0,
        config: { approvers: 'alice@x.com', ...config }, on_pass: null, on_fail: null,
        position: { x: 0, y: 0 },
      },
    ],
  };
}

function mockApi(config: Record<string, unknown>) {
  api.get.mockImplementation(async (url: string) => {
    if (url === '/api/workflows/wf-1') return { data: workflowWith(config) };
    return { data: [] };
  });
  api.put.mockImplementation(async (_url: string, body: unknown) => ({ data: body }));
}

async function openApproval() {
  render(
    <MemoryRouter initialEntries={['/workflows/wf-1']}>
      <WorkflowDesigner workflowId="wf-1" />
    </MemoryRouter>,
  );
  fireEvent.click(await screen.findByText('Approve'));
  return screen.findByRole('dialog');
}

async function savedConfig(dialog: HTMLElement, saveLabel: RegExp) {
  fireEvent.click(within(dialog).getByTestId('step-config-done'));
  fireEvent.click(screen.getByRole('button', { name: saveLabel }));
  await waitFor(() => expect(api.put).toHaveBeenCalled());
  return api.put.mock.calls[0][1].steps[0].config;
}

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  api.post.mockResolvedValue({ data: {} });
});

afterEach(async () => {
  await i18n.changeLanguage('en');
});

describe('WorkflowDesigner approval step: require every approver', () => {
  it('saves require_all when checked, keeping the timeout', async () => {
    mockApi({ timeout_days: 3 });
    const dialog = await openApproval();
    const box = within(dialog).getByRole('checkbox', { name: 'Require every approver' });
    expect(box).toHaveAttribute('aria-checked', 'false');
    expect(within(dialog).getByText(/any one member for a group or role/)).toBeInTheDocument();

    fireEvent.click(box);

    expect(await savedConfig(dialog, /^Save/)).toEqual({
      approvers: 'alice@x.com', timeout_days: 3, require_all: true,
    });
  });

  it('shows a stored require_all checked and saves it off when unchecked', async () => {
    mockApi({ require_all: true });
    const dialog = await openApproval();
    const box = within(dialog).getByRole('checkbox', { name: 'Require every approver' });
    expect(box).toHaveAttribute('aria-checked', 'true');

    fireEvent.click(box);

    expect((await savedConfig(dialog, /^Save/)).require_all).toBe(false);
  });

  it('says the timeout is not enforced yet and an empty one is the default', async () => {
    mockApi({});
    const dialog = await openApproval();

    const input = within(dialog).getByLabelText('Timeout (days)');
    expect(input).toHaveValue(null);
    expect(input).toHaveAttribute('placeholder', '7');
    expect(within(dialog).getByText(/Not enforced yet/)).toBeInTheDocument();
    expect(within(dialog).getByText(/0 means no timeout/)).toBeInTheDocument();
  });

  it('keeps a stored timeout of 0 (no timeout)', async () => {
    mockApi({ timeout_days: 0 });
    const dialog = await openApproval();

    expect(within(dialog).getByLabelText('Timeout (days)')).toHaveValue(0);
    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Require every approver' }));

    expect((await savedConfig(dialog, /^Save/)).timeout_days).toBe(0);
  });

  it('saves 0 when typed, also after emptying the field', async () => {
    mockApi({ timeout_days: 3 });
    const dialog = await openApproval();
    const input = within(dialog).getByLabelText('Timeout (days)');

    fireEvent.change(input, { target: { value: '0' } });
    expect(input).toHaveValue(0);
    fireEvent.change(input, { target: { value: '' } });
    expect(input).toHaveValue(null);
    fireEvent.change(input, { target: { value: '0' } });

    expect((await savedConfig(dialog, /^Save/)).timeout_days).toBe(0);
  });

  it('saves no timeout_days when emptied', async () => {
    mockApi({ timeout_days: 3 });
    const dialog = await openApproval();

    fireEvent.change(within(dialog).getByLabelText('Timeout (days)'), { target: { value: '' } });

    expect(await savedConfig(dialog, /^Save/)).not.toHaveProperty('timeout_days');
  });

  it('labels both in Portuguese', async () => {
    await i18n.changeLanguage('pt');
    mockApi({});
    const dialog = await openApproval();

    expect(within(dialog).getByRole('checkbox', { name: 'Exigir todos os aprovadores' }))
      .toBeInTheDocument();
    expect(within(dialog).getByText(/Ainda não aplicado/)).toBeInTheDocument();
    expect(within(dialog).getByText(/0 significa sem tempo limite/)).toBeInTheDocument();
  });
});
