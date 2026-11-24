/**
 * Admin actions on a paused execution (#1119): a cancelled approval says which
 * path the workflow took, and a refused force decision (require_all) says
 * why, in the UI language. An error response is never shown as a success.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

const get = vi.fn();
const post = vi.fn();
const toast = vi.fn();
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get, post, delete: vi.fn() }) }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast }) }));
vi.mock('@/stores/permissions-store', async (orig) => {
  const actual = await orig<Record<string, unknown>>();
  return { ...actual, usePermissions: () => ({ hasPermission: () => true }) };
});
// Inline stand-in for the Radix dropdown: always renders its items as buttons
// (driving Radix pointer/portal machinery in jsdom is flaky in CI).
vi.mock('@/components/ui/dropdown-menu', () => {
  const Box = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  return {
    DropdownMenu: Box, DropdownMenuContent: Box, DropdownMenuLabel: Box,
    DropdownMenuGroup: Box, DropdownMenuPortal: Box, DropdownMenuSub: Box,
    DropdownMenuSubContent: Box, DropdownMenuSubTrigger: Box, DropdownMenuRadioGroup: Box,
    DropdownMenuShortcut: Box, DropdownMenuCheckboxItem: Box, DropdownMenuRadioItem: Box,
    DropdownMenuTrigger: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
    DropdownMenuItem: (
      { children, onClick }: { children?: React.ReactNode; onClick?: () => void },
    ) => <button type="button" role="menuitem" onClick={onClick}>{children}</button>,
    DropdownMenuSeparator: () => <hr />,
  };
});
vi.mock('@/components/settings/settings-page-wrapper', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

import i18n from '@/i18n/config';
import Workflows from './workflows';

const EXECUTION = {
  id: 'ex-1', workflow_id: 'wf-1', workflow_name: 'Contract Review',
  status: 'paused', entity_type: 'data_contract', entity_name: 'orders', entity_id: 'c-1',
  success_count: 1, failure_count: 0, step_executions: [],
};

function mockLists() {
  get.mockImplementation(async (url: string) => {
    if (url.startsWith('/api/workflows/executions')) {
      return { data: { executions: [EXECUTION], total: 1 } };
    }
    if (url.startsWith('/api/workflows')) return { data: { workflows: [], total: 0 } };
    return { data: { sessions: [], total: 0 } };
  });
}

async function chooseAction(name: RegExp) {
  const user = userEvent.setup();
  render(<MemoryRouter><Workflows /></MemoryRouter>);
  await screen.findByText('Contract Review');
  await user.click(await screen.findByRole('menuitem', { name }));
}

const lastToast = () => toast.mock.calls[toast.mock.calls.length - 1][0];

describe('Workflows view: admin actions on a paused approval', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
    get.mockReset();
    post.mockReset();
    toast.mockReset();
  });

  it('says the cancelled approval followed its rejection path', async () => {
    mockLists();
    post.mockResolvedValue({
      data: {
        execution_id: 'ex-1', status: 'failed', code: 'cancelled_by_admin',
        params: { status: 'failed' }, message: 'Approval cancelled',
      },
    });

    await chooseAction(/^cancel$/i);

    await waitFor(() => expect(toast).toHaveBeenCalled());
    expect(post).toHaveBeenCalledWith('/api/workflows/executions/ex-1/cancel', {});
    expect(lastToast().description).toBe(
      'Approval cancelled. The workflow followed its rejection path; status: Failed.',
    );
  });

  it('says it in Portuguese', async () => {
    mockLists();
    await i18n.changeLanguage('pt');
    post.mockResolvedValue({
      data: { execution_id: 'ex-1', status: 'failed', code: 'cancelled_by_admin',
        params: { status: 'failed' } },
    });

    await chooseAction(/^cancelar$/i);

    await waitFor(() => expect(toast).toHaveBeenCalled());
    expect(lastToast().description).toBe(
      'Aprovação cancelada. O fluxo de trabalho seguiu o caminho de rejeição; status: Falhou.',
    );
  });

  it('keeps the plain message for any other cancel', async () => {
    mockLists();
    post.mockResolvedValue({ data: { execution_id: 'ex-1', status: 'cancelled' } });

    await chooseAction(/^cancel$/i);

    await waitFor(() => expect(toast).toHaveBeenCalled());
    expect(lastToast().description).toBe('Execution cancelled successfully');
  });

  it('shows a failed cancel as an error', async () => {
    mockLists();
    post.mockResolvedValue({ data: {}, error: 'Execution not found' });

    await chooseAction(/^cancel$/i);

    await waitFor(() => expect(toast).toHaveBeenCalled());
    expect(lastToast()).toMatchObject({
      description: 'Failed to cancel execution', variant: 'destructive',
    });
  });

  it.each([
    ['force approve', /force approve/i],
    ['force reject', /force reject/i],
  ])('explains a refused %s under require_all', async (_label, name) => {
    mockLists();
    post.mockResolvedValue({
      data: {}, error: 'Only the approvers of this step can decide it.',
      errorCode: 'approval_not_an_approver',
    });

    await chooseAction(name);

    await waitFor(() => expect(toast).toHaveBeenCalled());
    expect(lastToast()).toMatchObject({
      description:
        'Only the approvers can decide this step (every approver must decide). '
        + 'You can cancel the execution instead.',
      variant: 'destructive',
    });
    expect(screen.queryByText('Workflow approved and resumed')).toBeNull();
  });

  it('explains it in Portuguese', async () => {
    mockLists();
    await i18n.changeLanguage('pt');
    post.mockResolvedValue({
      data: {}, error: 'Only the approvers of this step can decide it.',
      errorCode: 'approval_not_an_approver',
    });

    await chooseAction(/forçar aprovação/i);

    await waitFor(() => expect(toast).toHaveBeenCalled());
    expect(lastToast().description).toBe(
      'Somente os aprovadores podem decidir esta etapa (todos precisam decidir). '
      + 'Em vez disso, você pode cancelar a execução.',
    );
  });

  it('shows any other refused force decision as its failure', async () => {
    mockLists();
    post.mockResolvedValue({ data: {}, error: 'Execution not found or not in paused state' });

    await chooseAction(/force reject/i);

    await waitFor(() => expect(toast).toHaveBeenCalled());
    expect(lastToast()).toMatchObject({
      description: 'Failed to reject workflow', variant: 'destructive',
    });
  });

  it('counts a refused bulk cancel as a failure', async () => {
    mockLists();
    post.mockResolvedValue({ data: {}, error: 'Execution not found' });
    const user = userEvent.setup();
    render(<MemoryRouter><Workflows /></MemoryRouter>);
    await screen.findByText('Contract Review');

    const selectAll = screen.getAllByRole('checkbox', { name: /select all/i });
    await user.click(selectAll[selectAll.length - 1]);
    await user.click(await screen.findByRole('button', { name: /cancel \(1\)/i }));

    await waitFor(() => expect(toast).toHaveBeenCalled());
    expect(toast).toHaveBeenCalledTimes(1);
    expect(lastToast()).toMatchObject({
      description: '1 execution failed to cancel.', variant: 'destructive',
    });
  });
});
