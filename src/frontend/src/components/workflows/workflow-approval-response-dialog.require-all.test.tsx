/**
 * With require_all (#1119) a decision can leave other approvers pending: the
 * dialog says so, and translates the refusal of a second or late decision. It
 * sends the notification's step so a decision on an ended step gets 409.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import i18n from '@/i18n/config';
import WorkflowApprovalResponseDialog from './workflow-approval-response-dialog';

const api = vi.hoisted(() => ({
  get: async () => ({ data: { id: 'wf', name: 'Approval response', steps: [] } }),
  post: vi.fn(),
  toast: vi.fn(),
}));

vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: api.get, post: api.post }) }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: api.toast }) }));

function renderDialog(
  onDecisionMade = vi.fn(), onOpenChange = vi.fn(), extra: Record<string, unknown> = {},
) {
  render(
    <WorkflowApprovalResponseDialog
      isOpen
      onOpenChange={onOpenChange}
      onDecisionMade={onDecisionMade}
      payload={{ execution_id: 'e-1', entity_name: 'Product', ...extra } as never}
    />,
  );
  return { onDecisionMade, onOpenChange };
}

async function approve(label = 'Approve') {
  fireEvent.click(await screen.findByRole('button', { name: label }));
  await waitFor(() => expect(api.toast).toHaveBeenCalled());
  return api.toast.mock.calls[0][0];
}

beforeEach(() => {
  api.post.mockReset();
  api.toast.mockReset();
});

afterEach(async () => {
  await i18n.changeLanguage('en');
});

describe('WorkflowApprovalResponseDialog with require_all', () => {
  it('says the decision is recorded and how many approvers are left', async () => {
    api.post.mockResolvedValue({ data: { status: 'paused', pending_approvers: 2 } });
    const { onDecisionMade, onOpenChange } = renderDialog();

    const toast = await approve();

    expect(toast.title).toBe('Decision recorded');
    expect(toast.description).toBe('Waiting for 2 more approvers.');
    expect(toast.variant).toBeUndefined();
    expect(onDecisionMade).toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('says it in Portuguese, singular', async () => {
    await i18n.changeLanguage('pt');
    api.post.mockResolvedValue({ data: { status: 'paused', pending_approvers: 1 } });
    renderDialog();

    const toast = await approve('Aprovar');

    expect(toast.title).toBe('Decisão registrada');
    expect(toast.description).toBe('Aguardando mais 1 aprovador.');
  });

  it('keeps the approved message when the decision ends the step', async () => {
    api.post.mockResolvedValue({ data: { status: 'succeeded' } });
    renderDialog();

    const toast = await approve();

    expect(toast.description).toBe('Product has been approved.');
  });

  it('translates the refusal of a second decision', async () => {
    await i18n.changeLanguage('pt');
    api.post.mockResolvedValue({
      data: null, error: 'You have already decided this approval.',
      errorCode: 'approval_already_decided',
    });
    renderDialog();

    const toast = await approve('Aprovar');

    expect(toast.description).toBe('Você já decidiu esta aprovação.');
    expect(toast.variant).toBe('destructive');
  });

  it('translates the refusal of someone who is not one of the approvers', async () => {
    await i18n.changeLanguage('pt');
    api.post.mockResolvedValue({
      data: null, error: 'Only the approvers of this step can decide it.',
      errorCode: 'approval_not_an_approver',
    });
    renderDialog();

    const toast = await approve('Aprovar');

    expect(toast.description).toBe('Somente os aprovadores desta etapa podem decidi-la.');
  });

  it('sends the step of the notification', async () => {
    api.post.mockResolvedValue({ data: { status: 'succeeded' } });
    renderDialog(vi.fn(), vi.fn(), { step_id: 'approve' });

    await approve();

    expect(api.post).toHaveBeenCalledWith('/api/workflows/handle-approval', {
      execution_id: 'e-1', approved: true, step_id: 'approve',
    });
  });

  it('sends no step when the notification has none', async () => {
    api.post.mockResolvedValue({ data: { status: 'succeeded' } });
    renderDialog();

    await approve();

    expect(api.post.mock.calls[0][1]).toEqual({ execution_id: 'e-1', approved: true });
  });

  it.each([
    ['en', 'Approve', 'This approval has already been decided.'],
    ['pt', 'Aprovar', 'Esta aprovação já foi decidida.'],
  ])('translates a late decision (%s)', async (lang, label, text) => {
    await i18n.changeLanguage(lang);
    api.post.mockResolvedValue({
      data: null, error: 'This approval has already been decided.',
      errorCode: 'approval_no_longer_pending',
    });
    renderDialog();

    const toast = await approve(label);

    expect(toast.description).toBe(text);
    expect(toast.variant).toBe('destructive');
  });
});
