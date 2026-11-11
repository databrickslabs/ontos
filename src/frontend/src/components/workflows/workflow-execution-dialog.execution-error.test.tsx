/**
 * The execution's error box in the execution dialog: when the error is the
 * failed step's coded error, it is shown in the UI language, like the step's
 * own error above it (it stayed English).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import type { ProcessWorkflow, WorkflowExecution } from '@/types/process-workflow';

const get = vi.fn();
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get }) }));

import i18n from '@/i18n/config';
import { WorkflowExecutionDialog, getExecutionErrorText } from './workflow-execution-dialog';

const ENGLISH = 'Could not load data_product p-1 to evaluate the rule';
const PORTUGUESE = 'Não foi possível carregar data_product p-1 para avaliar a regra';

const CODED_RUN = {
  id: 'run-1', step_id: 'row-1', status: 'failed', passed: false,
  error_message: ENGLISH,
  result_data: {
    error_code: 'rule_entity_load_failed',
    error_params: { entityType: 'data_product', entityId: 'p-1' },
  },
};

function failedExecution(overrides: Partial<WorkflowExecution> = {}): WorkflowExecution {
  return {
    id: 'ex-1', workflow_id: 'wf-1', workflow_name: 'Gate', status: 'failed',
    success_count: 0, failure_count: 1, error_message: ENGLISH,
    step_executions: [CODED_RUN], ...overrides,
  } as unknown as WorkflowExecution;
}

describe('getExecutionErrorText', () => {
  it("translates the execution's error when it is a step's coded error", async () => {
    await i18n.changeLanguage('pt');
    try {
      expect(getExecutionErrorText(failedExecution(), i18n.t)).toBe(PORTUGUESE);
    } finally {
      await i18n.changeLanguage('en');
    }
  });

  it('leaves an error that no coded step carries to the shipped text lookup', () => {
    expect(getExecutionErrorText(failedExecution({ error_message: 'Step not found: x' }), i18n.t))
      .toBeUndefined();
    const uncoded = { ...CODED_RUN, result_data: {} };
    expect(getExecutionErrorText(failedExecution({ step_executions: [uncoded] as any }), i18n.t))
      .toBeUndefined();
  });
});

describe('getExecutionErrorText edge cases', () => {
  it('has no text for an execution without an error', () => {
    expect(getExecutionErrorText(failedExecution({ error_message: undefined }), i18n.t)).toBeUndefined();
    expect(getExecutionErrorText(failedExecution({ error_message: '' }), i18n.t)).toBeUndefined();
  });

  it('has no text when the step results are not loaded or carry no result data', () => {
    expect(getExecutionErrorText(failedExecution({ step_executions: undefined }), i18n.t)).toBeUndefined();
    const noData = { ...CODED_RUN, result_data: undefined };
    expect(getExecutionErrorText(failedExecution({ step_executions: [noData] as any }), i18n.t))
      .toBeUndefined();
  });

  it('ignores a coded step whose error is not the execution error', () => {
    const other = { ...CODED_RUN, error_message: 'Some other failure' };
    expect(getExecutionErrorText(failedExecution({ step_executions: [other] as any }), i18n.t))
      .toBeUndefined();
  });

  it('takes the latest coded run when several steps failed with the same message', async () => {
    const earlier = { ...CODED_RUN, id: 'run-0', result_data: { error_code: 'unknown_code_xyz' } };
    await i18n.changeLanguage('pt');
    try {
      expect(getExecutionErrorText(failedExecution({ step_executions: [earlier, CODED_RUN] as any }), i18n.t))
        .toBe(PORTUGUESE);
    } finally {
      await i18n.changeLanguage('en');
    }
  });
});

describe('WorkflowExecutionDialog error box', () => {
  beforeEach(() => get.mockReset());

  it("shows a step's coded error in the UI language, also for a row of the list", async () => {
    const steps = [{ id: 'row-1', step_id: 'check-owner', name: 'Check Owner', step_type: 'validation' }];
    const workflow = { id: 'wf-1', name: 'Gate', steps } as unknown as ProcessWorkflow;
    // The executions list carries no step results; the dialog loads them.
    const listRow = failedExecution({ step_executions: [] });
    get.mockImplementation(async (url: string) => (
      url === '/api/workflows/wf-1' ? { data: workflow } : { data: failedExecution() }
    ));
    await i18n.changeLanguage('pt');
    try {
      render(<WorkflowExecutionDialog execution={listRow} open onOpenChange={vi.fn()} />);
      // Once under the failed step and once in the error box
      await waitFor(() => expect(screen.getAllByText(PORTUGUESE)).toHaveLength(2));
      expect(screen.queryByText(ENGLISH)).toBeNull();
    } finally {
      await i18n.changeLanguage('en');
    }
  });

  it('shows the title fallback and an uncoded error as sent', async () => {
    get.mockResolvedValue({ data: { id: 'wf-1', name: 'Gate', steps: [] } });
    const execution = failedExecution({ workflow_name: undefined, step_executions: [], error_message: 'Step not found: x' });
    render(<WorkflowExecutionDialog execution={execution} open onOpenChange={vi.fn()} />);

    expect(await screen.findByText('Workflow Execution')).toBeInTheDocument();
    expect(screen.getByText('Step not found: x')).toBeInTheDocument();
  });
});
