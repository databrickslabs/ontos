/**
 * Manual workflow run dialog (#1118): asks for the entity, calls the execute
 * endpoint and shows the execution it returns.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ProcessWorkflow, WorkflowExecution } from '@/types/process-workflow';

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: api.get, post: api.post }) }));
const toast = vi.hoisted(() => vi.fn());
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast }) }));

import i18n from '@/i18n/config';
import { WorkflowRunDialog } from './workflow-run-dialog';

function workflow(entityTypes: string[]): ProcessWorkflow {
  return {
    id: 'wf 1', name: 'Quality check', trigger: { type: 'manual', entity_types: entityTypes },
  } as unknown as ProcessWorkflow;
}

const EXECUTION = {
  id: 'ex-1', workflow_id: 'wf 1', status: 'succeeded', entity_type: 'table',
  entity_id: 'main.sales.orders', step_executions: [], success_count: 1, failure_count: 0,
} as unknown as WorkflowExecution;

describe('WorkflowRunDialog', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
    toast.mockReset();
  });

  it('runs the workflow for a typed entity id and shows the result', async () => {
    api.post.mockResolvedValue({ data: EXECUTION });
    const onViewExecution = vi.fn();
    const onExecuted = vi.fn();
    render(
      <WorkflowRunDialog
        workflow={workflow(['table'])} open onOpenChange={vi.fn()}
        onExecuted={onExecuted} onViewExecution={onViewExecution}
      />,
    );
    const run = screen.getByRole('button', { name: 'Run' });
    expect(run).toBeDisabled();

    await userEvent.type(screen.getByLabelText('Entity id'), ' main.sales.orders ');
    await userEvent.click(run);

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(api.post).toHaveBeenCalledWith(
      '/api/workflows/wf%201/execute?entity_type=table&entity_id=main.sales.orders', {},
    );
    expect(await screen.findByTestId('run-result')).toHaveTextContent('Succeeded');
    expect(onExecuted).toHaveBeenCalledWith(EXECUTION);

    await userEvent.click(screen.getByRole('button', { name: 'View execution' }));
    expect(onViewExecution).toHaveBeenCalledWith(EXECUTION);
  });

  it('loads a picker for types with a list endpoint', async () => {
    api.get.mockResolvedValue({ data: [{ id: 'p1', name: 'Orders' }] });
    render(<WorkflowRunDialog workflow={workflow(['data_product'])} open onOpenChange={vi.fn()} />);
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/api/data-products'));
    expect(screen.queryByLabelText('Entity id')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run' })).toBeDisabled();
  });

  it('falls back to a text id when the list cannot be loaded', async () => {
    api.get.mockResolvedValue({ error: 'boom' });
    render(<WorkflowRunDialog workflow={workflow(['domain'])} open onOpenChange={vi.fn()} />);
    expect(await screen.findByLabelText('Entity id')).toBeInTheDocument();
  });

  it('shows a translated error, not the API text, when the run is refused', async () => {
    api.post.mockResolvedValue({ error: 'Forbidden' });
    render(<WorkflowRunDialog workflow={workflow(['table'])} open onOpenChange={vi.fn()} />);
    await userEvent.type(screen.getByLabelText('Entity id'), 'x');
    await userEvent.click(screen.getByRole('button', { name: 'Run' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('The workflow could not be started.');
    expect(alert).not.toHaveTextContent('Forbidden');
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ variant: 'destructive' }));
    expect(screen.queryByTestId('run-result')).not.toBeInTheDocument();
  });

  it.each([
    ['en', 'Table: main.sales.orders'],
    ['fr', 'Table : main.sales.orders'],
    ['ja', 'テーブル: main.sales.orders'],
  ])('formats the result entity line with the %s label/value separator', async (lng, expected) => {
    api.post.mockResolvedValue({ data: EXECUTION });
    await i18n.changeLanguage(lng);
    try {
      render(<WorkflowRunDialog workflow={workflow(['table'])} open onOpenChange={vi.fn()} />);
      await userEvent.type(screen.getByRole('textbox'), 'main.sales.orders');
      await userEvent.click(screen.getAllByRole('button').find((b) => b.textContent === i18n.t('workflows:runDialog.run'))!);
      expect(await screen.findByTestId('run-result')).toHaveTextContent(expected);
    } finally {
      await i18n.changeLanguage('en');
    }
  });
});
