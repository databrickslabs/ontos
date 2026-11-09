/**
 * ``onSessionComplete`` fires as soon as the wizard's session completes, so
 * a caller can submit the request then instead of when the wizard is closed
 * (leaving the page on the completion screen used to lose the request).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

import ApprovalWizardDialog from './approval-wizard-dialog';

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockToast = vi.fn();

vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: mockGet, post: mockPost }),
}));
vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: mockToast }),
}));
vi.mock('@/stores/user-store', () => ({
  useUserStore: (selector: (s: unknown) => unknown) =>
    selector({ userInfo: { email: 'requester@example.com' }, fetchUserInfo: vi.fn() }),
}));

const reasonStep = {
  step_id: 'reason',
  name: 'Provide a reason',
  step_type: 'user_action',
  order: 0,
  config: { required_fields: [{ id: 'reason', label: 'Why', type: 'text', required: true }] },
};

function renderWizard(props: Record<string, unknown> = {}) {
  const onOpenChange = vi.fn();
  render(
    <ApprovalWizardDialog
      isOpen
      onOpenChange={onOpenChange}
      entityType="data_product"
      entityId="p-1"
      entityName="Orders"
      preselectedWorkflowId="wf-1"
      autoStartWithPreselected
      {...props}
    />,
  );
  return { onOpenChange };
}

async function completeTheWizard() {
  const field = await screen.findByLabelText(/Why/);
  fireEvent.change(field, { target: { value: 'Needed for the quarterly report' } });
  fireEvent.click(screen.getByRole('button', { name: /complete/i }));
  await screen.findByText(/Agreement recorded/i);
}

const completedToast = () =>
  mockToast.mock.calls.some(([arg]) => /completed/i.test(String(arg?.title ?? '')));

describe('ApprovalWizardDialog completion', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGet.mockResolvedValue({ data: { id: 'wf-1', name: 'Request Publish', steps: [reasonStep] } });
    mockPost.mockImplementation((url: string) =>
      Promise.resolve(
        url === '/api/approvals/sessions'
          ? { data: { session_id: 's-1', workflow_id: 'wf-1', current_step: reasonStep } }
          : { data: { complete: true, agreement_id: 'agr-1', pdf_storage_path: null, pdf_url: null } },
      ),
    );
  });

  it('calls onSessionComplete when the session completes, before the wizard is closed', async () => {
    const onSessionComplete = vi.fn();
    const onComplete = vi.fn();
    renderWizard({ onSessionComplete, onComplete });

    await completeTheWizard();

    await waitFor(() => expect(onSessionComplete).toHaveBeenCalledTimes(1));
    expect(onSessionComplete).toHaveBeenCalledWith('agr-1', null, { reason: 'Needed for the quarterly report' });
    expect(onComplete).not.toHaveBeenCalled();
    // The caller reports the outcome, so no "completed" toast from the wizard
    expect(completedToast()).toBe(false);
  });

  it('still calls onComplete when the completed wizard is closed', async () => {
    const onSessionComplete = vi.fn();
    const onComplete = vi.fn();
    const { onOpenChange } = renderWizard({ onSessionComplete, onComplete });
    await completeTheWizard();

    fireEvent.click(screen.getAllByRole('button', { name: /^close$/i })[0]);

    await waitFor(() => expect(onComplete).toHaveBeenCalledTimes(1));
    expect(onSessionComplete).toHaveBeenCalledTimes(1);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('keeps the previous behavior without onSessionComplete', async () => {
    const onComplete = vi.fn();
    renderWizard({ onComplete });

    await completeTheWizard();

    expect(onComplete).not.toHaveBeenCalled();
    expect(completedToast()).toBe(true);
  });
});
