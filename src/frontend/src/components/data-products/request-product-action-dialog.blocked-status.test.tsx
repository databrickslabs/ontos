/**
 * A request refused with the blocked status change error (`status_change_blocked`
 * with its parameters) shows it in the UI language (#1078).
 */
import { screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { renderWithProviders } from '@/test/utils';
import RequestProductActionDialog from './request-product-action-dialog';

// Stable mocks: the dialog's effects depend on these functions
const mockGet = vi.fn();
const mockPost = vi.fn();
const mockToast = vi.fn();
const mockLookupWorkflowId = vi.fn();
const mockRefreshNotifications = vi.fn();

vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: mockToast }) }));
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: mockGet, post: mockPost }) }));
vi.mock('@/hooks/use-approval-wizard-trigger', async () => {
  const actual = await vi.importActual<typeof import('@/hooks/use-approval-wizard-trigger')>(
    '@/hooks/use-approval-wizard-trigger',
  );
  return { ...actual, useApprovalWizardTrigger: () => ({ lookupWorkflowId: mockLookupWorkflowId }) };
});
vi.mock('@/stores/notifications-store', () => ({
  useNotificationsStore: (selector: any) => selector({ refreshNotifications: mockRefreshNotifications }),
}));

const BLOCKED = "Status transition from 'approved' to 'active' blocked by workflow: "
  + 'Steward Gate: waiting for approval (Steward approval)';
const BLOCKED_PARAMS = {
  fromStatus: 'approved',
  toStatus: 'active',
  reasons: [{
    workflow: 'Steward Gate', text: 'waiting for approval (Steward approval)',
    code: 'waiting_for_approval', params: { step: 'Steward approval' },
  }],
};

describe('RequestProductActionDialog blocked status change', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('shows the error in the UI language', async () => {
    mockGet.mockResolvedValue({ data: [] });
    mockLookupWorkflowId.mockResolvedValue(null);
    mockPost.mockResolvedValue({
      data: {}, error: BLOCKED, errorCode: 'status_change_blocked', errorParams: BLOCKED_PARAMS,
    });
    await i18n.changeLanguage('pt');

    renderWithProviders(
      <RequestProductActionDialog
        isOpen={true}
        onOpenChange={vi.fn()}
        productId="prod-1"
        productName="Test Product"
        productStatus="active"
      />,
    );
    const reasonField = document.getElementById('access-message') as HTMLTextAreaElement;
    fireEvent.change(reasonField, { target: { value: 'Need access for the Q3 analytics rollup.' } });
    fireEvent.click(screen.getByRole('button', { name: /Enviar solicitação|Send Request/i }));

    expect(await screen.findByText(
      'A mudança de status de Aprovado para Ativo foi bloqueada por um workflow: '
      + 'Steward Gate: aguardando aprovação (Steward approval)',
    )).toBeInTheDocument();
  });
});
