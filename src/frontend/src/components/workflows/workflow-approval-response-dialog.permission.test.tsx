/**
 * #1615: an access request's approval dialog preselects the requested permission level.
 * The select offered CAN_READ / CAN_USE / ... while access requests carry READ / WRITE /
 * MANAGE, so the requested level matched no option and the select showed empty.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import i18n from '@/i18n/config';
import WorkflowApprovalResponseDialog, {
  MAX_GRANT_DAYS,
  grantableLevels,
} from './workflow-approval-response-dialog';

const api = vi.hoisted(() => ({
  admin: false,
  get: async () => ({ data: null }),
  post: vi.fn(async (_url: string, _body: Record<string, unknown>) => ({ data: {} }) as any),
  toast: vi.fn(),
}));

vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: api.get, post: api.post }) }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: api.toast }) }));
vi.mock('@/hooks/use-is-ontos-admin', () => ({ useIsOntosAdmin: () => api.admin }));

function renderDialog() {
  return render(
    <WorkflowApprovalResponseDialog
      isOpen
      onOpenChange={() => {}}
      payload={{
        execution_id: 'e-1',
        entity_type: 'access_grant',
        entity_name: 'Orders',
        permission_level: 'READ',
        requested_duration_days: 30,
      } as never}
    />,
  );
}

afterEach(async () => {
  api.admin = false;
  api.post.mockClear();
  api.toast.mockClear();
  await i18n.changeLanguage('en');
});

describe('WorkflowApprovalResponseDialog permission level', () => {
  it('shows the requested level selected', async () => {
    renderDialog();
    expect(await screen.findByRole('combobox')).toHaveTextContent('Read Only');
  });

  it('shows it in the UI language', async () => {
    await i18n.changeLanguage('pt');
    renderDialog();
    const expected = i18n.t('access-grants:permissionOptions.READ');
    expect(expected).not.toBe('Read Only');
    expect(await screen.findByRole('combobox')).toHaveTextContent(expected);
  });

  it('sends the requested level with the approval', async () => {
    renderDialog();
    fireEvent.click(await screen.findByRole('button', { name: /Approve/ }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(api.post.mock.calls[0][1]).toEqual(expect.objectContaining({
      approved: true, permission_level: 'READ', granted_duration_days: 30,
    }));
  });

  it('offers only the requested level or a narrower one', () => {
    expect(grantableLevels('READ')).toEqual(['READ']);
    expect(grantableLevels('WRITE')).toEqual(['READ', 'WRITE']);
    expect(grantableLevels('MANAGE')).toEqual(['READ', 'WRITE', 'MANAGE']);
    expect(grantableLevels('CAN_USE')).toEqual(['READ', 'WRITE', 'MANAGE']);
  });

  it('caps the duration at the requested one', async () => {
    renderDialog();
    expect(await screen.findByLabelText(/Duration/)).toHaveAttribute('max', '30');
  });
});

describe('WorkflowApprovalResponseDialog admin override (#1687 review)', () => {
  it('lets an admin grant any level and a longer duration, and says so', async () => {
    api.admin = true;
    renderDialog();
    expect(await screen.findByLabelText(/Duration/)).toHaveAttribute('max', String(MAX_GRANT_DAYS));
    expect(screen.getByText(/As an admin/)).toBeInTheDocument();
    expect(grantableLevels('READ', true)).toEqual(['READ', 'WRITE', 'MANAGE']);
  });

  it("doesn't tell an approver who isn't an admin about the override", async () => {
    renderDialog();
    await screen.findByLabelText(/Duration/);
    expect(screen.queryByText(/As an admin/)).toBeNull();
  });
});

describe('WorkflowApprovalResponseDialog failed access decision (#1687 review)', () => {
  it('warns the approver instead of a plain success', async () => {
    api.post.mockResolvedValueOnce({
      data: { status: 'succeeded', warning: { code: 'access_decision_failed' } },
    });
    renderDialog();
    fireEvent.click(await screen.findByRole('button', { name: /Approve/ }));
    await waitFor(() => expect(api.toast).toHaveBeenCalledTimes(1));
    expect(api.toast.mock.calls[0][0]).toEqual(expect.objectContaining({
      title: i18n.t('workflows:approvalResponse.accessDecision.failedTitle'),
      variant: 'destructive',
    }));
  });
});

describe('WorkflowApprovalResponseDialog terms cut by an earlier step (#1687 review)', () => {
  it('tells the approver what was granted instead', async () => {
    const params = { sent_days: 30, sent_level: 'WRITE', granted_days: 7, granted_level: 'READ' };
    api.post.mockResolvedValueOnce({
      data: {
        status: 'succeeded',
        warning: { code: 'access_terms_narrowed_by_earlier_step', params },
      },
    });
    renderDialog();
    fireEvent.click(await screen.findByRole('button', { name: /Approve/ }));
    await waitFor(() => expect(api.toast).toHaveBeenCalledTimes(1));
    expect(api.toast.mock.calls[0][0]).toEqual({
      title: i18n.t('workflows:approvalResponse.accessDecision.narrowedTitle'),
      description: i18n.t('workflows:approvalResponse.accessDecision.narrowed', params),
    });
    expect(api.toast.mock.calls[0][0].description).toContain('READ for 7 days');
  });
});
