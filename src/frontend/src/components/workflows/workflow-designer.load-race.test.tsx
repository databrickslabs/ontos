/**
 * A designer load that was superseded (React.StrictMode runs the load effect twice in dev) must
 * not overwrite what the user did after the newer load finished.
 */
import { StrictMode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import WorkflowDesigner from './workflow-designer';

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), toast: vi.fn() }));

vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: api.get, post: api.post, put: api.put }),
}));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: api.toast }) }));
vi.mock('./template-vars-inspector', () => ({ default: () => null }));

const STEP_TYPES = [
  {
    type: 'conditional', name: 'Conditional', description: '', icon: 'git-branch',
    config_schema: {
      type: 'object', properties: { condition: { type: 'string' } }, required: ['condition'],
    },
    has_pass_branch: true, has_fail_branch: true,
  },
];

const WEBHOOK_STEP_TYPE = {
  type: 'webhook', name: 'Webhook', description: '', icon: 'globe',
  config_schema: { type: 'object', properties: {} },
  has_pass_branch: true, has_fail_branch: true,
};

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
});

describe('WorkflowDesigner overlapping loads', () => {
  it('keeps a step added before the first (superseded) load finishes', async () => {
    // The first step-types request (from the first, superseded effect run) answers last
    let releaseFirst: () => void = () => undefined;
    let stepTypeCalls = 0;
    api.get.mockImplementation(async (url: string) => {
      if (url === '/api/workflows/step-types') {
        stepTypeCalls += 1;
        if (stepTypeCalls === 1) {
          await new Promise<void>(resolve => { releaseFirst = resolve; });
        }
        return { data: STEP_TYPES };
      }
      return { data: [] };
    });

    const { container } = render(
      <StrictMode>
        <MemoryRouter initialEntries={['/workflows/new?type=process']}>
          <WorkflowDesigner workflowId="new" />
        </MemoryRouter>
      </StrictMode>,
    );
    const nodes = () => container.querySelectorAll('.react-flow__node');

    // The second run finishes first: the trigger shows and the user adds a step
    await waitFor(() => expect(nodes()).toHaveLength(1));
    fireEvent.click(await screen.findByRole('button', { name: 'Conditional' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByTestId('step-config-done'));
    await waitFor(() => expect(nodes()).toHaveLength(2));

    // The first run now finishes: it must not reset the canvas to the trigger alone
    await act(async () => {
      releaseFirst();
      await new Promise(resolve => setTimeout(resolve, 50));
    });
    expect(nodes()).toHaveLength(2);
  });

  function workflowFixture(id: string, name: string) {
    return {
      id, name, description: '', is_active: true, workflow_type: 'process',
      trigger: { type: 'on_create', entity_types: ['table'] },
      steps: [{
        step_id: `${id}-s1`, name: `${name} step`, step_type: 'conditional',
        config: { condition: 'true' }, order: 0,
      }],
    };
  }

  // Answers the preload requests at once; workflow requests are held until released
  function holdWorkflows(held: Record<string, () => void>, data: Record<string, unknown>) {
    api.get.mockImplementation(async (url: string) => {
      if (url === '/api/workflows/step-types') return { data: STEP_TYPES };
      const match = /^\/api\/workflows\/(wf-\d)$/.exec(url);
      if (!match) return { data: [] };
      await new Promise<void>(resolve => { held[match[1]] = resolve; });
      return { data: data[match[1]] };
    });
  }

  function renderWith(workflowId: string) {
    const ui = (idValue: string) => (
      <MemoryRouter initialEntries={['/workflows/x?type=process']}>
        <WorkflowDesigner workflowId={idValue} />
      </MemoryRouter>
    );
    const view = render(ui(workflowId));
    return { ...view, show: (idValue: string) => view.rerender(ui(idValue)) };
  }

  it('drops the response of an edit load that was superseded by another workflow', async () => {
    const held: Record<string, () => void> = {};
    holdWorkflows(held, {
      'wf-1': workflowFixture('wf-1', 'First'),
      'wf-2': workflowFixture('wf-2', 'Second'),
    });
    const { container, show } = renderWith('wf-1');
    await waitFor(() => expect(held['wf-1']).toBeDefined());

    show('wf-2');
    await waitFor(() => expect(held['wf-2']).toBeDefined());
    await act(async () => { held['wf-2'](); });
    const nameInput = await screen.findByPlaceholderText(/workflow name/i);
    await waitFor(() => expect(nameInput).toHaveValue('Second'));

    // The superseded first response arrives last: it must not replace the second workflow
    await act(async () => {
      held['wf-1']();
      await new Promise(resolve => setTimeout(resolve, 50));
    });
    expect(screen.getByPlaceholderText(/workflow name/i)).toHaveValue('Second');
    expect(container.querySelectorAll('.react-flow__node')).toHaveLength(2);
    expect(screen.queryByText('First step')).toBeNull();
  });

  it('shows the workflow without waiting for the picker lookups', async () => {
    // Slow lookups never answer: the workflow must still load
    api.get.mockImplementation(async (url: string) => {
      if (url === '/api/workflows/step-types') return { data: STEP_TYPES };
      if (url === '/api/workflows/wf-1') return { data: workflowFixture('wf-1', 'First') };
      return new Promise(() => undefined);
    });
    renderWith('wf-1');

    expect(await screen.findByPlaceholderText(/workflow name/i)).toHaveValue('First');
  });

  it('shows role names on a workflow that arrives after the roles', async () => {
    const held: Record<string, () => void> = {};
    const workflow = {
      ...workflowFixture('wf-1', 'First'),
      steps: [{
        step_id: 'approve', name: 'Approve', step_type: 'approval',
        config: { approvers: 'role-1' }, order: 0,
      }],
    };
    holdWorkflows(held, { 'wf-1': workflow });
    const roles = [{ id: 'role-1', name: 'Data Stewards', source: 'app' }];
    const preload = api.get.getMockImplementation()!;
    api.get.mockImplementation(async (url: string) =>
      url === '/api/workflows/roles' ? { data: roles } : preload(url));
    const { container } = renderWith('wf-1');
    await waitFor(() => expect(held['wf-1']).toBeDefined());
    // Let the roles response settle before the workflow answers
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });

    await act(async () => { held['wf-1'](); });
    await waitFor(() =>
      expect(container.querySelector('.react-flow__node')?.parentElement?.textContent).toContain('Data Stewards'));
  });

  it('lists UC HTTP connections only once a webhook step is opened', async () => {
    api.get.mockImplementation(async (url: string) => ({
      data: url === '/api/workflows/step-types' ? [...STEP_TYPES, WEBHOOK_STEP_TYPE] : [],
    }));
    render(
      <StrictMode>
        <MemoryRouter initialEntries={['/workflows/new?type=process']}>
          <WorkflowDesigner workflowId="new" />
        </MemoryRouter>
      </StrictMode>,
    );
    const connectionCalls = () =>
      api.get.mock.calls.filter(([url]) => url === '/api/workflows/http-connections').length;

    fireEvent.click(await screen.findByRole('button', { name: 'Conditional' }));
    fireEvent.click(within(await screen.findByRole('dialog')).getByTestId('step-config-done'));
    expect(connectionCalls()).toBe(0);

    fireEvent.click(await screen.findByRole('button', { name: 'Webhook' }));
    await screen.findByRole('dialog');
    await waitFor(() => expect(connectionCalls()).toBe(1));
  });

  it('does not stay loading when a new workflow replaces a pending edit load', async () => {
    const held: Record<string, () => void> = {};
    holdWorkflows(held, { 'wf-1': workflowFixture('wf-1', 'First') });
    const { show } = renderWith('wf-1');
    await waitFor(() => expect(held['wf-1']).toBeDefined());
    expect(screen.queryByPlaceholderText(/workflow name/i)).toBeNull(); // spinner

    show('new');
    expect(await screen.findByPlaceholderText(/workflow name/i)).toHaveValue('');

    await act(async () => {
      held['wf-1']();
      await new Promise(resolve => setTimeout(resolve, 50));
    });
    expect(screen.getByPlaceholderText(/workflow name/i)).toHaveValue('');
  });
});
