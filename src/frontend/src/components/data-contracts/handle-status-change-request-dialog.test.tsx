/**
 * An admin decides a contract's status change request (e.g. the deprecation
 * of a certified contract) from its notification: the dialog sends the
 * decision to handle-status-change and explains a refusal in the user's
 * language.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import i18n from '@/i18n/config';
import HandleStatusChangeRequestDialog from './handle-status-change-request-dialog';

const api = vi.hoisted(() => ({ post: vi.fn(), toast: vi.fn() }));
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ post: api.post }) }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: api.toast }) }));

const OK = { data: { message: 'ok' }, error: null, errorCode: null, errorParams: null };

type DialogProps = Parameters<typeof HandleStatusChangeRequestDialog>[0];

function renderDialog(overrides: Partial<DialogProps> = {}) {
  const onDecisionMade = vi.fn();
  const onOpenChange = vi.fn();
  render(
    <HandleStatusChangeRequestDialog
      isOpen
      onOpenChange={onOpenChange}
      contractId="c1"
      contractName="Orders v1"
      requesterEmail="owner@example.com"
      fromStatus="active"
      targetStatus="deprecated"
      justification="Replaced by Orders v2"
      onDecisionMade={onDecisionMade}
      {...overrides}
    />,
  );
  return { onDecisionMade, onOpenChange };
}

function click(name: RegExp) {
  fireEvent.click(screen.getAllByRole('button').find(b => name.test(b.textContent || ''))!);
}

beforeEach(() => {
  api.post.mockReset();
  api.toast.mockReset();
});

afterEach(async () => {
  await i18n.changeLanguage('en');
});

describe('HandleStatusChangeRequestDialog', () => {
  it('shows the request with its statuses in the user language', async () => {
    await i18n.changeLanguage('pt');
    renderDialog();

    expect(screen.getByText('Tratar Solicitação de Mudança de Status')).toBeInTheDocument();
    expect(screen.getByTestId('status-change-request-statuses')).toHaveTextContent('Ativo');
    expect(screen.getByTestId('status-change-request-statuses')).toHaveTextContent('Obsoleto');
    expect(screen.getByText('owner@example.com')).toBeInTheDocument();
    expect(screen.getByText('Orders v1')).toBeInTheDocument();
    expect(screen.getByText('Replaced by Orders v2')).toBeInTheDocument();
  });

  it('approves through handle-status-change and reports the new status', async () => {
    api.post.mockResolvedValue(OK);
    const { onDecisionMade, onOpenChange } = renderDialog();

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Consumers moved' } });
    click(/^Approve$/);

    await waitFor(() => expect(onDecisionMade).toHaveBeenCalled());
    expect(api.post).toHaveBeenCalledWith('/api/data-contracts/c1/handle-status-change', {
      decision: 'approve',
      target_status: 'deprecated',
      requester_email: 'owner@example.com',
      message: 'Consumers moved',
    });
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(api.toast.mock.calls[0][0]).toMatchObject({
      title: 'Status Change Approved',
      description: 'The contract is now Deprecated.',
    });
  });

  it('denies the request', async () => {
    api.post.mockResolvedValue(OK);
    const { onDecisionMade } = renderDialog();

    click(/^Deny$/);

    await waitFor(() => expect(onDecisionMade).toHaveBeenCalled());
    expect(api.post.mock.calls[0][1]).toMatchObject({
      decision: 'deny', target_status: 'deprecated',
    });
    expect(api.post.mock.calls[0][1].message).toBeUndefined();
    expect(api.toast.mock.calls[0][0].title).toBe('Status Change Denied');
  });

  it('explains a request decided after the status changed, in the user language', async () => {
    await i18n.changeLanguage('pt');
    api.post.mockResolvedValue({
      data: null,
      error: "Invalid transition from 'deprecated' to 'deprecated'",
      errorCode: 'invalid_status_transition',
      errorParams: { fromStatus: 'deprecated', toStatus: 'deprecated' },
    });
    const { onDecisionMade } = renderDialog();

    click(/^Aprovar$/);

    await waitFor(() => expect(api.toast).toHaveBeenCalled());
    const shown = api.toast.mock.calls[0][0];
    expect(shown.variant).toBe('destructive');
    expect(shown.description).toContain('Obsoleto');
    expect(shown.description).not.toContain('Invalid transition');
    expect(onDecisionMade).not.toHaveBeenCalled();
  });

  it('explains the certified guard refusing an approval that is not an admin one', async () => {
    await i18n.changeLanguage('pt');
    api.post.mockResolvedValue({
      data: null,
      error: "The data contract 'Orders v1' is certified: deprecating it needs an approved ...",
      errorCode: 'certified_deprecation_requires_approval',
      errorParams: { entityName: 'Orders v1' },
    });
    renderDialog();

    click(/^Aprovar$/);

    await waitFor(() => expect(api.toast).toHaveBeenCalled());
    const description = api.toast.mock.calls[0][0].description as string;
    expect(description).toContain('Orders v1');
    expect(description).not.toContain('is certified: deprecating it');
  });
});
