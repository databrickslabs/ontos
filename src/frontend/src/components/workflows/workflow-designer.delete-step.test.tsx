/**
 * Deleting a step clears the links other steps had to it, so the workflow
 * still saves, and a save the backend refuses says why in the user's language.
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

const STEP_TYPES = [
  {
    type: 'conditional', name: 'Conditional', description: '', icon: 'git-branch',
    config_schema: { type: 'object', properties: { condition: { type: 'string' } }, required: ['condition'] },
    has_pass_branch: true, has_fail_branch: true,
  },
  {
    type: 'script', name: 'Script', description: '', icon: 'code',
    config_schema: {
      type: 'object',
      properties: {
        language: { type: 'string', enum: ['python', 'sql'], default: 'python' },
        code: { type: 'string' },
        timeout_seconds: { type: 'integer', default: 60, minimum: 1 },
      },
      required: ['code'],
    },
    has_pass_branch: true, has_fail_branch: true,
  },
];

function renderDesigner() {
  return render(
    <MemoryRouter initialEntries={['/workflows/new?type=process']}>
      <WorkflowDesigner workflowId="new" />
    </MemoryRouter>,
  );
}

async function addConditional(label: string, conditionLabel: string) {
  fireEvent.click(await screen.findByRole('button', { name: label }));
  const dialog = await screen.findByRole('dialog');
  fireEvent.change(within(dialog).getByLabelText(conditionLabel), {
    target: { value: "obj.name CONTAINS 'email'" },
  });
  return dialog;
}

function savedWorkflow() {
  const call = api.post.mock.calls.find(([url]) => url === '/api/workflows');
  return call?.[1];
}

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  api.get.mockImplementation(async (url: string) => ({
    data: url === '/api/workflows/step-types' ? STEP_TYPES : [],
  }));
  api.post.mockImplementation(async (url: string) => (
    url === '/api/workflows/check-condition'
      ? { data: { valid: true, code: null, params: {}, message: null } }
      : { data: {} }
  ));
});

afterEach(async () => {
  await i18n.changeLanguage('en');
});

describe('WorkflowDesigner deleting a step', () => {
  it('clears the link the previous step had to the deleted step', async () => {
    renderDesigner();
    fireEvent.change(await screen.findByPlaceholderText(/workflow name/i), { target: { value: 'Delete a step' } });
    const first = await addConditional('Conditional', 'Condition');
    fireEvent.click(within(first).getByTestId('step-config-done'));

    // A new step is linked from the last one (its on_pass), then deleted.
    const second = await addConditional('Conditional', 'Condition');
    fireEvent.click(within(second).getByTitle('Delete Step'));

    fireEvent.click(screen.getByRole('button', { name: /^Save/ }));

    await waitFor(() => expect(savedWorkflow()).toBeDefined());
    const steps = savedWorkflow().steps;
    expect(steps).toHaveLength(1);
    expect(steps[0].on_pass).toBeUndefined();
    expect(steps[0].on_fail).toBeUndefined();
  });

  it('removes the step when its node is deleted with the keyboard', async () => {
    const { container } = renderDesigner();
    fireEvent.change(await screen.findByPlaceholderText(/workflow name/i), { target: { value: 'Keyboard delete' } });
    const first = await addConditional('Conditional', 'Condition');
    fireEvent.click(within(first).getByTestId('step-config-done'));
    const second = await addConditional('Conditional', 'Condition');
    fireEvent.click(within(second).getByTestId('step-config-done'));

    const stepNodes = () => Array.from(container.querySelectorAll('.react-flow__node'))
      .filter(n => !n.classList.contains('react-flow__node-trigger'));
    await waitFor(() => expect(stepNodes()).toHaveLength(2));
    // Select the node with the keyboard (jsdom can't drag), then press Delete
    const last = stepNodes()[1] as HTMLElement;
    last.focus();
    fireEvent.keyDown(last, { key: 'Enter', code: 'Enter' });
    fireEvent.keyUp(last, { key: 'Enter', code: 'Enter' });
    await waitFor(() => expect(last.classList.contains('selected')).toBe(true));
    fireEvent.keyDown(last, { key: 'Delete', code: 'Delete' });
    fireEvent.keyUp(last, { key: 'Delete', code: 'Delete' });
    await waitFor(() => expect(stepNodes()).toHaveLength(1));

    fireEvent.click(screen.getByRole('button', { name: /^Save/ }));

    await waitFor(() => expect(savedWorkflow()).toBeDefined());
    const steps = savedWorkflow().steps;
    expect(steps).toHaveLength(1);
    expect(steps[0].on_pass).toBeUndefined();
  });

  it('keeps the trigger node when it is deleted with the keyboard', async () => {
    const { container } = renderDesigner();
    const trigger = await waitFor(() => {
      const node = container.querySelector('.react-flow__node-trigger');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    trigger.focus();
    fireEvent.keyDown(trigger, { key: 'Enter', code: 'Enter' });
    fireEvent.keyUp(trigger, { key: 'Enter', code: 'Enter' });
    fireEvent.keyDown(trigger, { key: 'Delete', code: 'Delete' });
    fireEvent.keyUp(trigger, { key: 'Delete', code: 'Delete' });
    await new Promise(resolve => setTimeout(resolve, 50));
    expect(container.querySelector('.react-flow__node-trigger')).not.toBeNull();
  });

  it('shows the errors of a refused save in the user language', async () => {
    await i18n.changeLanguage('pt');
    api.post.mockImplementation(async (url: string) => {
      if (url === '/api/workflows/check-condition') {
        return { data: { valid: true, code: null, params: {}, message: null } };
      }
      return {
        data: null,
        error: "Step 'prepare' references unknown step 'old-check' in on_pass",
        errorCode: 'workflow_invalid',
        errorParams: {
          issues: [{
            code: 'step_unknown_reference',
            message: "Step 'prepare' references unknown step 'old-check' in on_pass",
            params: { step: 'prepare', target: 'old-check', field: 'on_pass' },
          }],
        },
      };
    });
    renderDesigner();
    fireEvent.change(await screen.findByPlaceholderText(/nome do fluxo de trabalho/i), { target: { value: 'Recusado' } });
    const step = await addConditional('Condicional', 'Condição');
    fireEvent.click(within(step).getByTestId('step-config-done'));

    fireEvent.click(screen.getByRole('button', { name: /^Salvar/ }));

    await waitFor(() => expect(api.toast).toHaveBeenCalled());
    expect(api.toast.mock.calls[0][0].description).toBe(
      'A etapa "prepare" aponta o ramo de sucesso para "old-check", que não está no workflow.',
    );
  });
});
