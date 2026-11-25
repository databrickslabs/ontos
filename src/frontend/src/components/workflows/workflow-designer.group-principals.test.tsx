/**
 * A group picked as an approver or recipient is saved as `group:<name>`, so a
 * group named like a role token (`reviewer`) stays that group (#1151 item 5).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import type { Principal } from '@/types/directory';
import WorkflowDesigner from './workflow-designer';

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), toast: vi.fn() }));

vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: api.get, post: api.post, put: api.put }),
}));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: api.toast }) }));
vi.mock('./template-vars-inspector', () => ({ default: () => null }));

// Picking from the directory, without the directory: one button per principal
vi.mock('@/components/common/principal-picker', () => ({
  PrincipalPicker: ({ value, onChange, pickValue }: {
    value: string[];
    onChange: (next: string[]) => void;
    pickValue?: (p: Principal) => string;
  }) => {
    const pick = (p: Principal) => onChange([...value, pickValue ? pickValue(p) : p.id]);
    const group: Principal = { type: 'group', id: 'reviewer', display_name: 'reviewer' };
    const user: Principal = { type: 'user', id: 'rita@x.com', display_name: 'Rita' };
    return (
      <div>
        <button type="button" onClick={() => pick(group)}>pick group</button>
        <button type="button" onClick={() => pick(user)}>pick user</button>
      </div>
    );
  },
}));

function workflow() {
  return {
    id: 'wf-1', name: 'Review', description: '', is_active: true, workflow_type: 'approval',
    trigger: { type: 'on_request_review', entity_types: ['data_product'] },
    steps: [
      {
        step_id: 'approve', name: 'Approve', step_type: 'approval', order: 0,
        config: { approvers: 'requester', approvers_custom: true, timeout_days: 7 },
        on_pass: 'notify', on_fail: null, position: { x: 0, y: 0 },
      },
      {
        step_id: 'notify', name: 'Notify', step_type: 'notification', order: 1,
        config: { recipients: 'requester', recipients_custom: true, template: 'x' },
        on_pass: null, on_fail: null, position: { x: 0, y: 150 },
      },
    ],
  };
}

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  api.post.mockResolvedValue({ data: {} });
  api.get.mockImplementation(async (url: string) => {
    if (url === '/api/workflows/wf-1') return { data: workflow() };
    return { data: [] };
  });
  api.put.mockImplementation(async (_url: string, body: unknown) => ({ data: body }));
});

async function pickInStep(stepName: string) {
  fireEvent.click(await screen.findByText(stepName));
  const dialog = await screen.findByRole('dialog');
  fireEvent.click(within(dialog).getByRole('button', { name: 'pick group' }));
  fireEvent.click(within(dialog).getByRole('button', { name: 'pick user' }));
  fireEvent.click(within(dialog).getByTestId('step-config-done'));
}

async function savedConfig(stepId: string) {
  fireEvent.click(screen.getByRole('button', { name: /^Save/ }));
  await waitFor(() => expect(api.put).toHaveBeenCalled());
  const body = api.put.mock.calls.find(([url]) => url === '/api/workflows/wf-1')![1];
  return body.steps.find((s: { step_id: string }) => s.step_id === stepId).config;
}

describe('WorkflowDesigner group principals', () => {
  it.each([
    ['Approve', 'approve', 'approvers'],
    ['Notify', 'notify', 'recipients'],
  ])('saves a group picked in %s with the group: prefix', async (stepName, stepId, field) => {
    render(
      <MemoryRouter initialEntries={['/workflows/wf-1']}>
        <WorkflowDesigner workflowId="wf-1" />
      </MemoryRouter>,
    );

    await pickInStep(stepName);

    expect((await savedConfig(stepId))[field]).toBe('requester,group:reviewer,rita@x.com');
  });
});
