/**
 * Step states in the execution dialog (#962).
 *
 * The executions list carries no step results, and step results reference the
 * step's row id (`id`), not its `step_id`, so every step without a result
 * showed "Pending" after it had run.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import type { ProcessWorkflow, WorkflowExecution } from '@/types/process-workflow';

const get = vi.fn();
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get }) }));

import i18n from '@/i18n/config';
import {
  WorkflowExecutionDialog, getStepErrorText, getStepExecutionState,
} from './workflow-execution-dialog';

const STEPS = [
  { id: 'row-1', step_id: 'notify-requester', name: 'Confirm Request Received', step_type: 'notification' },
  { id: 'row-2', step_id: 'request-approval', name: 'Request Data Steward Approval', step_type: 'approval' },
  { id: 'row-3', step_id: 'notify-approved', name: 'Notify Approval', step_type: 'notification' },
];

function execution(overrides: Partial<WorkflowExecution> = {}): WorkflowExecution {
  return {
    id: 'ex-1', workflow_id: 'wf-1', workflow_name: 'Data Contract Review Request',
    status: 'paused', current_step_id: 'request-approval', success_count: 1, failure_count: 0,
    step_executions: [], ...overrides,
  } as WorkflowExecution;
}

const RUN = (stepRowId: string, passed = true) => ({
  id: `run-${stepRowId}-${Math.random()}`, step_id: stepRowId, status: passed ? 'succeeded' : 'failed', passed,
});

describe('getStepExecutionState', () => {
  it('finds a step result by the step row id', () => {
    const ex = execution({ step_executions: [RUN('row-1')] as any });
    expect(getStepExecutionState(STEPS[0] as any, ex)).toBe('succeeded');
    expect(getStepExecutionState(STEPS[1] as any, ex)).toBe('current');
    expect(getStepExecutionState(STEPS[2] as any, ex)).toBe('pending');
  });

  it('counts a step that ran twice by its last run', () => {
    const ex = execution({
      status: 'failed', current_step_id: 'request-approval',
      step_executions: [RUN('row-2'), RUN('row-2', false)] as any,
    });
    expect(getStepExecutionState(STEPS[1] as any, ex)).toBe('failed');
  });
});

describe('WorkflowExecutionDialog', () => {
  beforeEach(() => get.mockReset());

  it('loads the step results of an execution opened from the list', async () => {
    const workflow = { id: 'wf-1', name: 'Data Contract Review Request', steps: STEPS } as unknown as ProcessWorkflow;
    get.mockImplementation(async (url: string) => (
      url === '/api/workflows/wf-1'
        ? { data: workflow }
        : { data: execution({ step_executions: [RUN('row-1')] as any }) }
    ));

    // A row of the executions list: no step results
    render(<WorkflowExecutionDialog execution={execution()} open onOpenChange={vi.fn()} />);

    await waitFor(() => expect(get).toHaveBeenCalledWith('/api/workflows/executions/ex-1'));
    const first = await screen.findByText('Confirm Request Received');
    await waitFor(() => {
      const card = first.closest('[class*="border-emerald-500"]');
      expect(card).not.toBeNull();
    });
  });

  it("shows the execution's status in the UI language", async () => {
    const workflow = { id: 'wf-1', name: 'Data Contract Review Request', steps: STEPS } as unknown as ProcessWorkflow;
    const failed = execution({ status: 'failed', current_step_id: undefined });
    get.mockImplementation(async (url: string) => (
      url === '/api/workflows/wf-1' ? { data: workflow } : { data: failed }
    ));
    await i18n.changeLanguage('pt');
    try {
      render(<WorkflowExecutionDialog execution={failed} open onOpenChange={vi.fn()} />);
      expect(await screen.findByText('Falhou')).toBeInTheDocument();
    } finally {
      await i18n.changeLanguage('en');
    }
  });
});

describe('step errors', () => {
  const LOAD_FAILED = {
    error_message: 'Could not load data_product p-1 to evaluate the rule',
    result_data: {
      error_code: 'rule_entity_load_failed',
      error_params: { entityType: 'data_product', entityId: 'p-1' },
    },
  };

  it('translates an error that has a code, with its parameters', async () => {
    await i18n.changeLanguage('pt');
    try {
      expect(getStepErrorText(LOAD_FAILED, i18n.t)).toBe(
        'Não foi possível carregar data_product p-1 para avaliar a regra',
      );
    } finally {
      await i18n.changeLanguage('en');
    }
  });

  it('shows an error without a code as stored', () => {
    expect(getStepErrorText({ error_message: 'Policy not found: x' }, i18n.t)).toBe(
      'Policy not found: x',
    );
  });

  it('falls back to the stored text for an unknown code', () => {
    expect(getStepErrorText({
      error_message: 'Something else', result_data: { error_code: 'not_a_known_code' },
    }, i18n.t)).toBe('Something else');
  });

  it('shows the error under the step that failed', async () => {
    const steps = [{ id: 'row-1', step_id: 'check-contract', name: 'Check Contract', step_type: 'validation' }];
    const workflow = { id: 'wf-1', name: 'Gate', steps } as unknown as ProcessWorkflow;
    const failed = execution({
      status: 'failed', current_step_id: undefined,
      step_executions: [{ ...RUN('row-1', false), ...LOAD_FAILED }] as any,
    });
    get.mockImplementation(async (url: string) => (
      url === '/api/workflows/wf-1' ? { data: workflow } : { data: failed }
    ));

    render(<WorkflowExecutionDialog execution={failed} open onOpenChange={vi.fn()} />);

    expect(await screen.findByText('Could not load data_product p-1 to evaluate the rule'))
      .toBeInTheDocument();
  });
});
