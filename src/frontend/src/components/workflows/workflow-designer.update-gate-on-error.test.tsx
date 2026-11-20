/**
 * A before_update gate has the fail-closed setting too: the designer shows it with the update
 * wording, loads the stored mode and sends it on save (without the status gates' exemptions).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import i18n from '@/i18n/config';
import WorkflowDesigner from './workflow-designer';

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), toast: vi.fn() }));

vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: api.get, post: api.post, put: api.put }),
}));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: api.toast }) }));
vi.mock('./template-vars-inspector', () => ({ default: () => null }));

const WORKFLOW = {
  id: 'wf-1', name: 'Contract Update Gate', description: '', workflow_type: 'process',
  is_active: false, is_default: false, version: 1, scope: { type: 'all', ids: [] },
  trigger: { type: 'before_update', entity_types: ['data_contract'], on_error: 'fail_open' },
  steps: [{
    id: 's-1', workflow_id: 'wf-1', step_id: 'ok', name: 'OK', step_type: 'pass', config: {},
    order: 0,
  }],
};
const TRIGGER_TYPES = [{
  value: 'before_update', label: 'Before entity is updated (validation)',
  workflow_type: 'process', entity_types: ['data_contract'], group: 'validation_gates',
}];

function renderDesigner() {
  return render(
    <MemoryRouter initialEntries={['/workflows/wf-1']}>
      <WorkflowDesigner workflowId="wf-1" />
    </MemoryRouter>,
  );
}

const saveButton = () => screen.getByRole('button', { name: /^Save/, hidden: true });

function putBodies() {
  return api.put.mock.calls.filter(([url]) => url === '/api/workflows/wf-1').map(call => call[1]);
}

async function openTrigger(container: HTMLElement) {
  const node = await waitFor(() => {
    const found = container.querySelector('.react-flow__node-trigger');
    expect(found).not.toBeNull();
    return found as HTMLElement;
  });
  fireEvent.click(node);
  return screen.findByRole('switch', {
    name: "Refuse the update if this gate can't be evaluated",
  });
}

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  api.get.mockImplementation(async (url: string) => {
    if (url === '/api/workflows/wf-1') return { data: WORKFLOW };
    if (url === '/api/workflows/trigger-types') return { data: TRIGGER_TYPES };
    return { data: [] };
  });
  api.put.mockImplementation(async () => ({ data: {} }));
  api.post.mockImplementation(async () => ({ data: {} }));
});

afterEach(async () => {
  await act(async () => {
    await i18n.changeLanguage('en');
  });
});

describe('WorkflowDesigner on a before_update gate', () => {
  it('shows the update wording and saves fail_closed once switched on', async () => {
    const { container } = renderDesigner();
    const toggle = await openTrigger(container);
    expect(toggle).not.toBeChecked();
    expect(screen.getByText(/the update is refused/)).toBeInTheDocument();

    fireEvent.click(toggle);
    fireEvent.click(saveButton());

    await waitFor(() => expect(putBodies()).toHaveLength(1));
    expect(putBodies()[0].trigger).toMatchObject({
      type: 'before_update', on_error: 'fail_closed',
    });
    expect(putBodies()[0].trigger).not.toHaveProperty('disabled_for');
  });
});
