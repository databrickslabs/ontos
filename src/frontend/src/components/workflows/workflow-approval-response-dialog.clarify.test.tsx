/**
 * "Request clarification" is offered only when the approval step has an
 * on_clarify branch (the notification's can_clarify), needs a message, and is
 * sent as a clarification, not as an approval or a rejection (#1321).
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import i18n from '@/i18n/config';
import WorkflowApprovalResponseDialog from './workflow-approval-response-dialog';

const api = vi.hoisted(() => ({
  get: async () => ({
    data: {
      id: 'wf',
      name: 'Status Change Request',
      steps: [
        {
          step_id: 'request-approval',
          name: 'Request Admin Approval',
          step_type: 'approval',
          config: {},
        },
      ],
    },
  }),
  post: vi.fn(async (_url: string, _body: Record<string, unknown>) => ({ data: {} })),
  toast: vi.fn(),
}));

vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: api.get, post: api.post }) }));

vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: api.toast }) }));

function renderDialog(canClarify: boolean) {
  return render(
    <WorkflowApprovalResponseDialog
      isOpen
      onOpenChange={() => {}}
      payload={{ execution_id: 'e-1', entity_name: 'Product', can_clarify: canClarify } as never}
    />,
  );
}

afterEach(async () => {
  api.post.mockClear();
  api.toast.mockClear();
  await i18n.changeLanguage('en');
});

describe('WorkflowApprovalResponseDialog clarification', () => {
  it('offers the request only when the step has a clarification branch', async () => {
    renderDialog(false);
    await screen.findByRole('button', { name: 'Approve' });
    expect(screen.queryByRole('button', { name: 'Request clarification' })).not.toBeInTheDocument();
  });

  it('sends the message as a clarification, neither approved nor rejected', async () => {
    renderDialog(true);
    await screen.findByRole('button', { name: 'Request clarification' });
    fireEvent.change(document.getElementById('approval-reason') as HTMLElement, {
      target: { value: 'Which region?' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Request clarification' }));

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    const [url, body] = api.post.mock.calls[0];
    expect(url).toBe('/api/workflows/handle-approval');
    expect(body).toEqual({
      execution_id: 'e-1',
      approved: false,
      clarify: true,
      message: 'Which region?',
    });
  });

  it('asks for the message before sending a clarification without one', async () => {
    renderDialog(true);
    await screen.findByRole('button', { name: 'Request clarification' });

    fireEvent.click(screen.getByRole('button', { name: 'Request clarification' }));

    expect(api.post).not.toHaveBeenCalled();
    expect(api.toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Message required', variant: 'destructive' }),
    );
  });
});
