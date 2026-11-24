/**
 * A workflow stored with only unknown entity types (the removed `dataset`) matched no event.
 * The designer sends the unknown types back on save, doesn't auto-fill a type over them, and
 * once the user removes the last one refuses to save until a known type is picked, so the
 * workflow never becomes "any entity" (#1151).
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
  id: 'wf-1', name: 'Contract Purpose Gate', description: '', workflow_type: 'process',
  is_active: false, is_default: false, version: 1, scope: { type: 'all', ids: [] },
  trigger: { type: 'before_update', entity_types: [], unknown_entity_types: ['dataset'] },
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

// The trigger settings sheet is modal: the header's Save button is outside it
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
  return screen.findByTestId('unknown-entity-types');
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

describe('WorkflowDesigner with unknown stored entity types', () => {
  // The backend answers 200 to this body (the trigger is unchanged, so it isn't checked):
  // test_a_designer_save_that_keeps_the_trigger_succeeds in the route tests
  it('saves the unknown types back and does not auto-fill a known one', async () => {
    const { container } = renderDesigner();
    await openTrigger(container);
    expect(screen.getByRole('checkbox', { name: 'Data contract' })).not.toBeChecked();

    fireEvent.click(saveButton());

    await waitFor(() => expect(putBodies()).toHaveLength(1));
    expect(putBodies()[0].trigger).toMatchObject({
      type: 'before_update', entity_types: [], unknown_entity_types: ['dataset'],
    });
  });

  it('refuses to save once the last unknown type is removed, until a known type is picked',
    async () => {
      const { container } = renderDesigner();
      await openTrigger(container);
      fireEvent.click(screen.getByRole('button', { name: 'Remove dataset' }));

      expect(await screen.findByTestId('entity-type-required')).toHaveTextContent(
        'Pick at least one entity type. With none, this workflow would fire for every entity.',
      );
      fireEvent.click(saveButton());
      await waitFor(() => expect(api.toast).toHaveBeenCalled());
      expect(api.toast.mock.calls[0][0].description).toContain('Pick at least one entity type');
      expect(putBodies()).toHaveLength(0);

      fireEvent.click(screen.getByRole('checkbox', { name: 'Data contract' }));
      expect(screen.queryByTestId('entity-type-required')).toBeNull();
      fireEvent.click(saveButton());

      await waitFor(() => expect(putBodies()).toHaveLength(1));
      expect(putBodies()[0].trigger.entity_types).toEqual(['data_contract']);
      expect(putBodies()[0].trigger).not.toHaveProperty('unknown_entity_types');
    });
});
