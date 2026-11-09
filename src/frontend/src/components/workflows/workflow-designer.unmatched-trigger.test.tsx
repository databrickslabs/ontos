/**
 * A stored trigger that matched no event (only unknown entity types, or only known types its
 * trigger type never fires for) must not turn into "any entity" when the user changes it: the
 * designer asks for a known type, and stops holding back the auto-fill once the trigger type
 * changes (#1151).
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
// Radix Select hangs in jsdom: a native select stands in for the trigger picker
vi.mock('./trigger-picker', () => ({
  TriggerPicker: ({ value, onChange }: { value: string; onChange: (v: string) => void }) => (
    <select aria-label="Trigger" value={value} onChange={e => onChange(e.target.value)}>
      {['before_update', 'on_publish', 'on_request_deploy'].map(v => (
        <option key={v} value={v}>{v}</option>
      ))}
    </select>
  ),
}));

const TRIGGER_TYPES = [
  { value: 'before_update', entity_types: ['data_contract'] },
  { value: 'on_publish', entity_types: ['data_contract', 'data_product'] },
  { value: 'on_request_deploy', entity_types: ['data_contract'] },
].map(o => ({ ...o, label: o.value, workflow_type: 'process', group: 'validation_gates' }));

function storedWorkflow(entityTypes: string[], unknownEntityTypes: string[] = []) {
  return {
    id: 'wf-1', name: 'Gate', description: '', workflow_type: 'process',
    is_active: false, is_default: false, version: 1, scope: { type: 'all', ids: [] },
    trigger: {
      type: 'before_update', entity_types: entityTypes, unknown_entity_types: unknownEntityTypes,
    },
    steps: [{
      id: 's-1', workflow_id: 'wf-1', step_id: 'ok', name: 'OK', step_type: 'pass', config: {},
      order: 0,
    }],
  };
}

function renderDesigner(workflow: ReturnType<typeof storedWorkflow>) {
  api.get.mockImplementation(async (url: string) => {
    if (url === '/api/workflows/wf-1') return { data: workflow };
    if (url === '/api/workflows/trigger-types') return { data: TRIGGER_TYPES };
    return { data: [] };
  });
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

async function switchTrigger(container: HTMLElement, type: string) {
  const node = await waitFor(() => {
    const found = container.querySelector('.react-flow__node-trigger');
    expect(found).not.toBeNull();
    return found as HTMLElement;
  });
  fireEvent.click(node);
  const picker = await screen.findByRole('combobox', { name: 'Trigger', hidden: true });
  await waitFor(() => expect(picker).toHaveValue('before_update'));
  fireEvent.change(picker, { target: { value: type } });
}

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  api.put.mockImplementation(async () => ({ data: {} }));
  api.post.mockImplementation(async () => ({ data: {} }));
});

afterEach(async () => {
  await act(async () => {
    await i18n.changeLanguage('en');
  });
});

describe('WorkflowDesigner with a stored trigger that matched no event', () => {
  it('asks for a known type when a trigger of only unfired pairs is emptied', async () => {
    // before_update never fires for data_product; on_publish has two types, so no auto-fill
    const { container } = renderDesigner(storedWorkflow(['data_product']));
    await switchTrigger(container, 'on_publish');

    expect(await screen.findByTestId('entity-type-required')).toHaveTextContent(
      'Pick at least one entity type',
    );
    fireEvent.click(saveButton());
    await waitFor(() => expect(api.toast).toHaveBeenCalled());
    expect(api.toast.mock.calls[0][0].description).toContain('Pick at least one entity type');
    expect(putBodies()).toHaveLength(0);
  });

  it('auto-fills again once the trigger type of an unknown-type trigger changes', async () => {
    const { container } = renderDesigner(storedWorkflow([], ['dataset']));
    await switchTrigger(container, 'on_request_deploy');

    await waitFor(() => expect(
      screen.getByRole('checkbox', { name: 'Data contract', hidden: true }),
    ).toBeChecked());
  });

  it('does not ask for a type when the stored trigger fired', async () => {
    const { container } = renderDesigner(storedWorkflow(['data_contract']));
    await switchTrigger(container, 'on_publish');

    await screen.findByRole('checkbox', { name: 'Data product', hidden: true });
    expect(screen.queryByTestId('entity-type-required')).toBeNull();
  });
});
