/**
 * The designer shows validation warnings (Check) and the stored trigger warnings, on the
 * node they concern and in a summary, and saving still goes through with warnings (#1438).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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
      {['before_update', 'on_create'].map(v => (
        <option key={v} value={v}>{v}</option>
      ))}
    </select>
  ),
}));

const TRIGGER_TYPES = [
  { value: 'before_update', entity_types: ['data_contract'] },
  { value: 'on_create', entity_types: ['data_contract'] },
].map(o => ({ ...o, label: o.value, workflow_type: 'process', group: 'validation_gates' }));

// A conditional with a step on its true branch only: no step on the false branch
function storedWorkflow(triggerWarnings: unknown[] = []) {
  return {
    id: 'wf-1', name: 'Gate', description: '', workflow_type: 'process',
    is_active: false, is_default: false, version: 1, scope: { type: 'all', ids: [] },
    trigger: { type: 'on_create', entity_types: ['data_contract'] },
    trigger_warnings: triggerWarnings,
    steps: [
      {
        step_id: 'check', name: 'Check', step_type: 'conditional',
        config: { condition: 'x == 1' }, on_pass: 'ok', order: 0,
      },
      {
        step_id: 'ok', name: 'OK', step_type: 'pass', config: {}, order: 1,
      },
    ],
  };
}

const VALIDATE_WARNING = {
  code: 'conditional_branch_missing',
  message: 'Conditional step \'check\' has no step on its false branch',
  params: { step: 'check', branch: 'false' },
};

function renderDesigner(workflow: ReturnType<typeof storedWorkflow>) {
  api.get.mockImplementation(async (url: string) => {
    if (url === '/api/workflows/wf-1') return { data: workflow };
    if (url === '/api/workflows/trigger-types') return { data: TRIGGER_TYPES };
    return { data: [] };
  });
  api.post.mockImplementation(async (url: string) => {
    if (url.startsWith('/api/workflows/validate')) {
      return { data: { valid: true, errors: [], warnings: [VALIDATE_WARNING.message], issues: [], warning_issues: [VALIDATE_WARNING] } };
    }
    return { data: [] };
  });
  api.put.mockImplementation(async () => ({ data: { id: 'wf-1' } }));
  return render(
    <MemoryRouter initialEntries={['/workflows/wf-1']}>
      <WorkflowDesigner workflowId="wf-1" />
    </MemoryRouter>,
  );
}

const checkButton = () => screen.findByRole('button', { name: 'Check' });
const saveButton = () => screen.getByRole('button', { name: /^Save/, hidden: true });

describe('WorkflowDesigner warnings', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
    api.put.mockReset();
    api.toast.mockReset();
  });

  it('shows the stored trigger warnings on the trigger node and in the summary', async () => {
    const { container } = renderDesigner(storedWorkflow([
      { code: 'stored_entity_type_unknown', message: 'x', params: { triggerType: 'on_create', entityType: 'dataset' } },
    ]));

    const summary = await screen.findByTestId('workflow-warnings');
    expect(summary.textContent).toContain(i18n.getFixedT('en')('workflows:designer.validationWarnings.stored_entity_type_unknown', { triggerType: 'on_create', entityType: 'dataset', defaultValue: 'x' }));
    await waitFor(() => {
      expect(container.querySelector('.react-flow__node-trigger')?.className).toContain('ring-amber-500');
    });
  });

  it('Check shows the validation warnings on the node and in the summary, and saving still goes through', async () => {
    const { container } = renderDesigner(storedWorkflow());
    await waitFor(() => expect(screen.getByDisplayValue('Gate')).toBeTruthy());

    fireEvent.click(await checkButton());

    const summary = await screen.findByTestId('workflow-warnings');
    expect(summary.textContent).toContain('"check"');
    expect(summary.textContent).toContain('False');
    await waitFor(() => {
      expect(container.querySelector('.react-flow__node-conditional')?.className).toContain('ring-amber-500');
    });

    fireEvent.click(saveButton());
    await waitFor(() => expect(api.put).toHaveBeenCalledWith('/api/workflows/wf-1', expect.anything()));
    expect(api.toast).toHaveBeenLastCalledWith(expect.objectContaining({ title: 'Success' }));
    expect(api.toast).not.toHaveBeenCalledWith(expect.objectContaining({ variant: 'destructive' }));
  });

  it('hides a check result once the draft changes', async () => {
    renderDesigner(storedWorkflow());
    await waitFor(() => expect(screen.getByDisplayValue('Gate')).toBeTruthy());

    fireEvent.click(await checkButton());
    await screen.findByTestId('workflow-warnings');

    fireEvent.change(screen.getByDisplayValue('Gate'), { target: { value: 'Gate 2' } });
    await waitFor(() => expect(screen.queryByTestId('workflow-warnings')).toBeNull());
  });
});
