/**
 * The error of an execution that ended on a shipped fail step (#1078).
 *
 * A fail step's message becomes the execution's error; the default workflows
 * store it in English, so it is shown in the user's language while it is the
 * shipped text, and as written once an admin changed it.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { WorkflowExecution } from '@/types/process-workflow';

const get = vi.fn();
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get }) }));

import i18n from '@/i18n/config';
import { WorkflowExecutionDialog } from './workflow-execution-dialog';

function failed(error_message: string): WorkflowExecution {
  return {
    id: 'ex-1', workflow_id: 'wf-1', workflow_name: 'Data Contract Validation',
    status: 'failed', success_count: 1, failure_count: 1, step_executions: [], error_message,
  } as unknown as WorkflowExecution;
}

describe('WorkflowExecutionDialog error message', () => {
  beforeEach(async () => {
    get.mockReset();
    get.mockResolvedValue({ data: null });
    await i18n.changeLanguage('pt');
  });

  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it("shows a shipped fail step's message in the user's language", async () => {
    render(
      <WorkflowExecutionDialog
        execution={failed('Data contract requires a schema definition')}
        open
        onOpenChange={vi.fn()}
      />,
    );

    expect(await screen.findByText('O contrato de dados exige uma definição de schema'))
      .toBeInTheDocument();
  });

  it('shows a message an admin changed as written', async () => {
    render(
      <WorkflowExecutionDialog
        execution={failed('Contracts need a schema before review')}
        open
        onOpenChange={vi.fn()}
      />,
    );

    expect(await screen.findByText('Contracts need a schema before review')).toBeInTheDocument();
  });
});
