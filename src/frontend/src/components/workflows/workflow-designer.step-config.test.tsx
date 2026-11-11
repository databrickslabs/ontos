/**
 * The designer saves Conditional and Script steps with the config entered in
 * their forms, and blocks a save the backend would reject (#943, #942).
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

async function addStep(label: string) {
  fireEvent.click(await screen.findByRole('button', { name: label }));
  return screen.findByRole('dialog');
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
  api.post.mockImplementation(async (url: string, body: { condition?: string }) => {
    if (url === '/api/workflows/check-condition') {
      return body.condition?.includes('==')
        ? { data: { valid: false, code: 'condition_syntax_error', params: { line: 1, column: 12 }, message: 'x' } }
        : { data: { valid: true, code: null, params: {}, message: null } };
    }
    return { data: {} };
  });
});

afterEach(async () => {
  await i18n.changeLanguage('en');
});

describe('WorkflowDesigner Conditional and Script steps', () => {
  it('saves a Conditional and a Script step with their config', async () => {
    renderDesigner();
    fireEvent.change(await screen.findByPlaceholderText(/workflow name/i), { target: { value: 'PII check' } });

    const conditional = await addStep('Conditional');
    fireEvent.change(within(conditional).getByLabelText('Condition'), {
      target: { value: "obj.name CONTAINS 'email'" },
    });
    fireEvent.click(within(conditional).getByTestId('step-config-done'));

    const script = await addStep('Script');
    fireEvent.change(within(script).getByLabelText('Code'), { target: { value: "result = {'passed': True}" } });
    fireEvent.change(within(script).getByLabelText('Timeout (seconds)'), { target: { value: '20' } });
    fireEvent.click(within(script).getByTestId('step-config-done'));

    fireEvent.click(screen.getByRole('button', { name: /^Save/ }));

    await waitFor(() => expect(savedWorkflow()).toBeDefined());
    const steps = savedWorkflow().steps;
    expect(steps.map((s: { step_type: string }) => s.step_type)).toEqual(['conditional', 'script']);
    expect(steps[0].config).toEqual({ condition: "obj.name CONTAINS 'email'" });
    expect(steps[1].config).toEqual({ code: "result = {'passed': True}", timeout_seconds: 20 });
    expect(api.post).toHaveBeenCalledWith('/api/workflows/check-condition', {
      condition: "obj.name CONTAINS 'email'",
    });
  });

  it('does not save a Conditional step without a condition, and says why', async () => {
    await i18n.changeLanguage('pt');
    renderDesigner();
    fireEvent.change(await screen.findByPlaceholderText(/nome do fluxo de trabalho/i), { target: { value: 'Sem condição' } });
    const conditional = await addStep('Condicional');
    fireEvent.click(within(conditional).getByTestId('step-config-done'));

    fireEvent.click(screen.getByRole('button', { name: /^Salvar/ }));

    await waitFor(() => expect(api.toast).toHaveBeenCalled());
    expect(api.toast.mock.calls[0][0].description).toMatch(/Informe uma condição\.$/);
    expect(savedWorkflow()).toBeUndefined();
    expect(await screen.findByRole('alert')).toHaveTextContent('Informe uma condição.');
  });

  it('does not save a condition that does not parse', async () => {
    renderDesigner();
    fireEvent.change(await screen.findByPlaceholderText(/workflow name/i), { target: { value: 'Bad condition' } });
    const conditional = await addStep('Conditional');
    fireEvent.change(within(conditional).getByLabelText('Condition'), { target: { value: "obj.name == 'x'" } });
    fireEvent.click(within(conditional).getByTestId('step-config-done'));

    fireEvent.click(screen.getByRole('button', { name: /^Save/ }));

    await waitFor(() => expect(api.toast).toHaveBeenCalled());
    expect(api.toast.mock.calls[0][0].description).toContain("The condition doesn't parse (line 1, column 12).");
    expect(savedWorkflow()).toBeUndefined();
  });

  it('does not save a Script step without code', async () => {
    renderDesigner();
    fireEvent.change(await screen.findByPlaceholderText(/workflow name/i), { target: { value: 'No code' } });
    const script = await addStep('Script');
    fireEvent.click(within(script).getByTestId('step-config-done'));

    fireEvent.click(screen.getByRole('button', { name: /^Save/ }));

    await waitFor(() => expect(api.toast).toHaveBeenCalled());
    expect(api.toast.mock.calls[0][0].description).toContain("Enter the script's code.");
    expect(savedWorkflow()).toBeUndefined();
  });
});
