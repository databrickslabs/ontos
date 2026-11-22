/**
 * A failed step that the run went on past (fail_flow_on_failure off on a best-effort
 * step) shows as non-fatal in a succeeded run, not as a plain failure (#859 review B9).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { ProcessWorkflow, WorkflowExecution } from '@/types/process-workflow';

const get = vi.fn();
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get }) }));

import i18n from '@/i18n/config';
import { WorkflowExecutionDialog } from './workflow-execution-dialog';

const STEPS = [
  { id: 'row-1', step_id: 'notify', name: 'Notify Reviewer', step_type: 'notification' },
  { id: 'row-2', step_id: 'done', name: 'Done', step_type: 'pass' },
];

function run(nonFatal: boolean): WorkflowExecution {
  return {
    id: 'ex-1', workflow_id: 'wf-1', workflow_name: 'Test',
    status: 'succeeded', success_count: 1, failure_count: 1,
    step_executions: [
      {
        id: 'r1', step_id: 'row-1', step_key: 'notify', status: 'failed', passed: false,
        result_data: nonFatal ? { non_fatal: true } : {},
      },
      { id: 'r2', step_id: 'row-2', step_key: 'done', status: 'succeeded', passed: true },
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

describe('WorkflowExecutionDialog non-fatal step', () => {
  beforeEach(() => get.mockReset());
  afterEach(async () => { await i18n.changeLanguage('en'); });

  it('marks a failed step the run continued past as non-fatal', async () => {
    open(run(true));

    expect(await screen.findByText('Failed, the run continued')).toBeInTheDocument();
  });

  it('does not mark a failed step as non-fatal without the marker', async () => {
    open(run(false));

    await screen.findByText('Notify Reviewer');
    expect(screen.queryByText('Failed, the run continued')).not.toBeInTheDocument();
  });
});
