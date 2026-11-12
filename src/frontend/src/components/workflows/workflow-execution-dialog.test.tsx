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

describe('entity type and step type labels', () => {
  const steps = [
    { id: 'row-1', step_id: 's1', name: 'Notify Approval', step_type: 'notification' },
    { id: 'row-2', step_id: 's2', name: 'Weird', step_type: 'custom_thing' },
  ];
  const workflow = { id: 'wf-1', name: 'W', steps } as unknown as ProcessWorkflow;
  const ex = execution({ entity_type: 'table', entity_name: 'orders', step_executions: [] });

  async function show(lang: string, check: () => void) {
    get.mockImplementation(async (url: string) => (
      url === '/api/workflows/wf-1' ? { data: workflow } : { data: ex }
    ));
    await i18n.changeLanguage(lang);
    try {
      render(<WorkflowExecutionDialog execution={ex} open onOpenChange={vi.fn()} />);
      await screen.findByText('Notify Approval');
      check();
    } finally {
      await i18n.changeLanguage('en');
    }
  }

  it('shows them in Portuguese', async () => {
    await show('pt', () => {
      expect(screen.getByText('Tabela')).toBeInTheDocument();
      expect(screen.getByText('Notificação')).toBeInTheDocument();
    });
  });

  it('shows them in English, and falls back for an unknown step type', async () => {
    await show('en', () => {
      expect(screen.getByText('Table')).toBeInTheDocument();
      expect(screen.getByText('Notification')).toBeInTheDocument();
      expect(screen.getByText('Custom Thing')).toBeInTheDocument();
    });
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

  it('translates the error of an entity that no longer exists', async () => {
    await i18n.changeLanguage('pt');
    try {
      expect(getStepErrorText({
        error_message: "data_product p-1 was not found, so the rule can't be evaluated",
        result_data: {
          error_code: 'rule_entity_not_found',
          error_params: { entityType: 'data_product', entityId: 'p-1' },
        },
      }, i18n.t)).toBe('data_product p-1 não foi encontrado, então a regra não pode ser avaliada');
    } finally {
      await i18n.changeLanguage('en');
    }
  });

  it('translates an approval rejected without a reason', async () => {
    await i18n.changeLanguage('pt');
    try {
      expect(getStepErrorText({
        error_message: 'Request denied',
        result_data: { error_code: 'approval_rejected', error_params: {} },
      }, i18n.t)).toBe('Solicitação negada');
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

describe('WorkflowExecutionDialog progress card', () => {
  beforeEach(() => get.mockReset());
  const workflow = { id: 'wf-1', name: 'Data Contract Review Request', steps: STEPS } as unknown as ProcessWorkflow;

  function mockApi(ex: WorkflowExecution) {
    get.mockImplementation(async (url: string) => (
      url === '/api/workflows/wf-1' ? { data: workflow } : { data: ex }
    ));
  }

  it('names the paused step while the execution waits', async () => {
    const ex = execution({ current_step_name: 'Request Data Steward Approval' });
    mockApi(ex);
    render(<WorkflowExecutionDialog execution={ex} open onOpenChange={vi.fn()} />);
    expect(await screen.findByText('Waiting At')).toBeTruthy();
    expect(screen.getAllByText('Request Data Steward Approval').length).toBeGreaterThan(1);
  });

  it.each(['failed', 'succeeded', 'cancelled'] as const)(
    'shows the progress, not the last paused step, once the execution is %s', async (status) => {
      const ex = execution({
        status, current_step_name: 'Request Data Steward Approval',
        step_executions: [RUN('row-1'), RUN('row-2')] as any,
      });
      mockApi(ex);
      render(<WorkflowExecutionDialog execution={ex} open onOpenChange={vi.fn()} />);
      const label = await screen.findByText('Progress');
      const card = label.parentElement as HTMLElement;
      expect(card.textContent).not.toContain('Request Data Steward Approval');
      expect(card.textContent).toMatch(/\d/);
    },
  );
});
