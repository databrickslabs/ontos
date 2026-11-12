/**
 * The approver and recipient selects have their own options for the
 * owner-derived tokens (DomainOwner, ContractApprover), and a step that
 * stores one of them shows it selected and saves it unchanged.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import i18n from '@/i18n/config';
import WorkflowDesigner from './workflow-designer';

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), toast: vi.fn() }));

vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: api.get, post: api.post, put: api.put }) }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: api.toast }) }));
vi.mock('./template-vars-inspector', () => ({ default: () => null }));

const ROLES = [{ id: 'r-steward', name: 'DataSteward', source: 'app', has_groups: true }];

function workflowWith(approvers: string, recipients: string) {
  return {
    id: 'wf-1', name: 'Review', description: '', is_active: true, workflow_type: 'approval',
    trigger: { type: 'on_request_review', entity_types: ['data_product'] },
    steps: [
      {
        step_id: 'approve', name: 'Approve', step_type: 'approval', order: 0,
        config: { approvers, timeout_days: 7 }, on_pass: 'notify', on_fail: null,
        position: { x: 0, y: 0 },
      },
      {
        step_id: 'notify', name: 'Notify', step_type: 'notification', order: 1,
        config: { recipients, template: 'x' }, on_pass: null, on_fail: null,
        position: { x: 0, y: 150 },
      },
    ],
  };
}

function renderDesigner() {
  return render(
    <MemoryRouter initialEntries={['/workflows/wf-1']}>
      <WorkflowDesigner workflowId="wf-1" />
    </MemoryRouter>,
  );
}

function mockApi(approvers: string, recipients: string) {
  api.get.mockImplementation(async (url: string) => {
    if (url === '/api/workflows/wf-1') return { data: workflowWith(approvers, recipients) };
    if (url.startsWith('/api/workflows/roles')) return { data: ROLES };
    return { data: [] };
  });
  api.put.mockImplementation(async (_url: string, body: unknown) => ({ data: body }));
}

async function openStep(name: string) {
  fireEvent.click(await screen.findByText(name));
  return screen.findByRole('dialog');
}

function savedStep(stepId: string) {
  const call = api.put.mock.calls.find(([url]) => url === '/api/workflows/wf-1');
  return call?.[1].steps.find((s: { step_id: string }) => s.step_id === stepId);
}

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  api.post.mockResolvedValue({ data: {} });
});

afterEach(async () => {
  await i18n.changeLanguage('en');
});

async function save() {
  fireEvent.click(screen.getByRole('button', { name: /^Save/ }));
  await waitFor(() => expect(api.put).toHaveBeenCalled());
}

describe('WorkflowDesigner owner-derived approvers', () => {
  it.each([
    ['DomainOwner', 'Domain owners'],
    ['domain_owners', 'Domain owners'],
    ['ContractApprover', 'Contract approvers'],
  ])('shows a stored %s approver on its own option and saves it unchanged', async (stored, label) => {
    mockApi(stored, 'requester');
    renderDesigner();
    const dialog = await openStep('Approve');
    expect(within(dialog).getAllByRole('combobox')[0]).toHaveTextContent(label);
    expect(within(dialog).getByRole('switch')).toHaveAttribute('aria-checked', 'false');
    fireEvent.click(within(dialog).getByTestId('step-config-done'));
    await save();
    expect(savedStep('approve').config.approvers).toBe(stored);
  });

  it('shows a stored ContractApprover recipient on its own option and saves it unchanged', async () => {
    mockApi('requester', 'ContractApprover');
    renderDesigner();
    const dialog = await openStep('Notify');
    expect(within(dialog).getAllByRole('combobox')[0]).toHaveTextContent('Contract approvers');
    expect(within(dialog).getByRole('switch')).toHaveAttribute('aria-checked', 'false');
    fireEvent.click(within(dialog).getByTestId('step-config-done'));
    await save();
    expect(savedStep('notify').config.recipients).toBe('ContractApprover');
  });

  it('keeps a role name on the role option, and a custom principal as custom', async () => {
    mockApi('DataSteward,alice@x.com', 'requester');
    renderDesigner();
    const dialog = await openStep('Approve');
    expect(within(dialog).getAllByRole('combobox')[0]).toHaveTextContent('DataSteward');
    expect(within(dialog).getByRole('switch')).toHaveAttribute('aria-checked', 'true');
  });

  it('labels the options in the user language', async () => {
    await i18n.changeLanguage('pt');
    mockApi('DomainOwner', 'requester');
    renderDesigner();
    const dialog = await screen.findByText('Approve').then(async (el) => {
      fireEvent.click(el);
      return screen.findByRole('dialog');
    });
    expect(within(dialog).getAllByRole('combobox')[0]).toHaveTextContent('Responsáveis pelo domínio');
  });
});
