/**
 * A Conditional step that evaluated cleanly is completed and shows the branch it
 * took (#1418). Before, a false condition was shown as a failed step.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { ProcessWorkflow, WorkflowExecution } from '@/types/process-workflow';

const get = vi.fn();
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get }) }));

import i18n from '@/i18n/config';
import { WorkflowExecutionDialog, getConditionalBranch, getStepExecutionState } from './workflow-execution-dialog';

const STEPS = [
  { id: 'row-1', step_id: 'check', name: 'Check Condition', step_type: 'conditional' },
  { id: 'row-2', step_id: 'done', name: 'Done', step_type: 'pass' },
  { id: 'row-3', step_id: 'stop', name: 'Stop', step_type: 'fail' },
];

function finished(branch: 'true' | 'false'): WorkflowExecution {
  return {
    id: 'ex-1', workflow_id: 'wf-1', workflow_name: 'Test',
    status: branch === 'true' ? 'succeeded' : 'failed', success_count: 1, failure_count: branch === 'true' ? 0 : 1,
    step_executions: [
      { id: 'r1', step_id: 'row-1', status: 'succeeded', passed: true,
        result_data: { condition: '1 != 1', result: branch === 'true', branch } },
      { id: 'r2', step_id: branch === 'true' ? 'row-2' : 'row-3',
        status: branch === 'true' ? 'succeeded' : 'failed', passed: branch === 'true' },
    ],
  } as unknown as WorkflowExecution;
}

function open(ex: WorkflowExecution) {
  const workflow = { id: 'wf-1', name: 'Test', steps: STEPS } as unknown as ProcessWorkflow;
  get.mockImplementation(async (url: string) => (
    url === '/api/workflows/wf-1' ? { data: workflow } : { data: ex }
  ));
  render(<WorkflowExecutionDialog execution={ex} open onOpenChange={vi.fn()} />);
}

describe('getConditionalBranch', () => {
  it('reads the branch of a conditional run', () => {
    expect(getConditionalBranch({ result_data: { branch: 'false' } } as any)).toBe('false');
  });

  it('ignores runs without a branch', () => {
    expect(getConditionalBranch({ result_data: { result: false } } as any)).toBeUndefined();
    expect(getConditionalBranch(undefined)).toBeUndefined();
  });
});

describe('WorkflowExecutionDialog conditional branch', () => {
  beforeEach(() => get.mockReset());
  afterEach(async () => { await i18n.changeLanguage('en'); });

  it('shows a false condition as completed with the false branch', async () => {
    open(finished('false'));

    expect(await screen.findByText('Condition was false: took the false branch')).toBeInTheDocument();
    const row = screen.getByText('Check Condition').closest('.rounded-lg');
    expect(row).toHaveTextContent('Completed');
    expect(row).not.toHaveTextContent('Failed');
  });

  it('shows the true branch', async () => {
    open(finished('true'));

    expect(await screen.findByText('Condition was true: took the true branch')).toBeInTheDocument();
  });

  it('shows the step on the branch not taken as skipped, not pending', async () => {
    open(finished('true'));

    await screen.findByText('Condition was true: took the true branch');
    const row = screen.getByText('Stop').closest('.rounded-lg');
    expect(row).toHaveTextContent('Skipped');
  });

  it('shows the branch in the UI language', async () => {
    await i18n.changeLanguage('de');
    open(finished('false'));

    expect(await screen.findByText('Bedingung war falsch: Falsch-Zweig ausgeführt')).toBeInTheDocument();
  });
});

describe('getStepExecutionState of steps that never ran', () => {
  const step = { id: 'row-2', step_id: 'approve' };

  it('is skipped in a finished execution', () => {
    const ex = { status: 'succeeded', current_step_id: null, step_executions: [] } as unknown as WorkflowExecution;
    expect(getStepExecutionState(step, ex)).toBe('skipped');
  });

  it('is pending for the step a cancelled execution stopped at', () => {
    const ex = { status: 'cancelled', current_step_id: 'approve', step_executions: [] } as unknown as WorkflowExecution;
    expect(getStepExecutionState(step, ex)).toBe('pending');
  });

  it('is skipped in a finished run even if it is the stale current step', () => {
    const ex = { status: 'succeeded', current_step_id: 'approve', step_executions: [] } as unknown as WorkflowExecution;
    expect(getStepExecutionState(step, ex)).toBe('skipped');
  });

  it('is pending while the execution is paused', () => {
    const ex = { status: 'paused', current_step_id: 'other', step_executions: [] } as unknown as WorkflowExecution;
    expect(getStepExecutionState(step, ex)).toBe('pending');
  });
});
