/**
 * Results of steps removed from the workflow after the execution ran.
 *
 * The dialog lists the workflow's current steps, so a step that ran and was
 * removed later didn't show anywhere. Its results now stay (no row id, with
 * the step's step_id and name) and are listed under "Removed steps".
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import type { ProcessWorkflow, WorkflowExecution } from '@/types/process-workflow';

const get = vi.fn();
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get }) }));

import i18n from '@/i18n/config';
import {
  WorkflowExecutionDialog, getLastStepRun, getRemovedStepRuns, getStepsProgress,
} from './workflow-execution-dialog';

const STEPS = [
  { id: 'row-1', step_id: 'check', name: 'Check', step_type: 'validation' },
  { id: 'row-3', step_id: 'notify', name: 'Notify', step_type: 'notification' },
];

function execution(overrides: Partial<WorkflowExecution> = {}): WorkflowExecution {
  return {
    id: 'ex-1', workflow_id: 'wf-1', workflow_name: 'Kept results',
    status: 'succeeded', success_count: 3, failure_count: 0,
    step_executions: [
      { id: 'r1', step_id: 'row-1', step_key: 'check', step_name: 'Check', status: 'succeeded', passed: true },
      { id: 'r2', step_id: null, step_key: 'old-webhook', step_name: 'Old Webhook', status: 'failed', passed: false, error_message: 'Webhook failed' },
      { id: 'r3', step_id: null, step_key: 'old-notify', step_name: 'Old Notify', status: 'succeeded', passed: true },
    ],
    ...overrides,
  } as WorkflowExecution;
}

describe('getRemovedStepRuns', () => {
  it('lists the runs of steps no longer in the workflow, in the order they ran', () => {
    const runs = getRemovedStepRuns(STEPS as any, execution());
    expect(runs.map(r => r.step_name)).toEqual(['Old Webhook', 'Old Notify']);
  });

  it('counts a removed step added back with its step_id as that step', () => {
    const ex = execution({
      step_executions: [
        { id: 'r1', step_id: null, step_key: 'notify', step_name: 'Notify', status: 'succeeded', passed: true },
      ] as any,
    });
    expect(getRemovedStepRuns(STEPS as any, ex)).toEqual([]);
    expect(getLastStepRun(STEPS[1] as any, ex)?.id).toBe('r1');
  });
});

describe('getStepsProgress', () => {
  it('counts the current steps that completed, out of the current steps', () => {
    // success_count is 3: one current step and two removed ones
    expect(getStepsProgress(STEPS as any, execution())).toEqual({ done: 1, total: 2, removed: 2 });
  });
});

describe('WorkflowExecutionDialog', () => {
  const workflow = { id: 'wf-1', name: 'Kept results', steps: STEPS } as unknown as ProcessWorkflow;

  beforeEach(() => {
    get.mockReset();
    get.mockImplementation(async (url: string) => (
      url === '/api/workflows/wf-1' ? { data: workflow } : { data: execution() }
    ));
  });
  afterEach(async () => { await i18n.changeLanguage('en'); });

  it('shows the removed steps with their names and states', async () => {
    render(<WorkflowExecutionDialog execution={execution()} open onOpenChange={vi.fn()} />);

    const section = await screen.findByTestId('removed-step-runs');
    expect(within(section).getByText('Removed steps')).toBeTruthy();
    expect(within(section).getByText('Old Webhook')).toBeTruthy();
    expect(within(section).getByText('Webhook failed')).toBeTruthy();
    expect(within(section).getByText('Old Notify')).toBeTruthy();
    expect(within(section).queryByText('Check')).toBeNull();
  });

  it('names the section in the UI language', async () => {
    await i18n.changeLanguage('pt');
    render(<WorkflowExecutionDialog execution={execution()} open onOpenChange={vi.fn()} />);

    const section = await screen.findByTestId('removed-step-runs');
    expect(within(section).getByText('Etapas removidas')).toBeTruthy();
    expect(within(section).getByText('Falhou')).toBeTruthy();
  });

  it('shows progress over the current steps, with the removed ones apart', async () => {
    render(<WorkflowExecutionDialog execution={execution()} open onOpenChange={vi.fn()} />);

    // success_count is 3, the workflow has 2 steps now: not "3/2 steps"
    expect(await screen.findByText('1/2 steps (+2 removed)')).toBeTruthy();
    expect(screen.queryByText('3/2 steps')).toBeNull();
  });

  it('shows the progress in the UI language', async () => {
    await i18n.changeLanguage('pt');
    render(<WorkflowExecutionDialog execution={execution()} open onOpenChange={vi.fn()} />);

    expect(await screen.findByText('1/2 etapas (+2 removidas)')).toBeTruthy();
  });

  it('uses the singular for one removed step', async () => {
    await i18n.changeLanguage('pt');
    const one = execution({ step_executions: execution().step_executions.slice(0, 2) });
    get.mockImplementation(async (url: string) => (
      url === '/api/workflows/wf-1' ? { data: workflow } : { data: one }
    ));
    render(<WorkflowExecutionDialog execution={one} open onOpenChange={vi.fn()} />);

    expect(await screen.findByText('1/2 etapas (+1 removida)')).toBeTruthy();
  });

  it('shows no section when every result belongs to a current step', async () => {
    get.mockImplementation(async (url: string) => (
      url === '/api/workflows/wf-1'
        ? { data: workflow }
        : { data: execution({ step_executions: [execution().step_executions[0]] }) }
    ));
    render(<WorkflowExecutionDialog execution={execution()} open onOpenChange={vi.fn()} />);

    await screen.findByText('Check');
    expect(screen.queryByTestId('removed-step-runs')).toBeNull();
    expect(await screen.findByText('1/2 steps')).toBeTruthy();
  });
});
