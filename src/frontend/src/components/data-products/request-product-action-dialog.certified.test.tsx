/**
 * Deprecating a certified product directly is refused by the certified guard
 * (`certified_deprecation_requires_approval`): the dialog shows the error in
 * the UI language and offers to send a status change request instead.
 *
 * The Radix Select hangs in jsdom, so it is replaced by a native select.
 */
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { renderWithProviders } from '@/test/utils';
import RequestProductActionDialog from './request-product-action-dialog';

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockToast = vi.fn();
const mockLookupWorkflowId = vi.fn();

vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: mockToast }) }));
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: mockGet, post: mockPost }) }));
vi.mock('@/hooks/use-approval-wizard-trigger', async () => {
  const actual = await vi.importActual<typeof import('@/hooks/use-approval-wizard-trigger')>(
    '@/hooks/use-approval-wizard-trigger',
  );
  return {
    ...actual,
    useApprovalWizardTrigger: () => ({ lookupWorkflowId: mockLookupWorkflowId }),
  };
});
vi.mock('@/stores/notifications-store', () => ({
  useNotificationsStore: (selector: any) => selector({ refreshNotifications: vi.fn() }),
}));
vi.mock('@/components/ui/select', () => ({
  Select: ({ value, onValueChange, children }: any) => (
    <select value={value} onChange={(e) => onValueChange(e.target.value)}>
      <option value="" />
      {children}
    </select>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
  SelectContent: ({ children }: any) => <>{children}</>,
  SelectItem: ({ value }: any) => <option value={value}>{value}</option>,
}));

const REFUSED = {
  data: {},
  error: "The data product 'Orders' is certified: deprecating it needs an approved status "
    + 'change request. Request the status change instead.',
  errorCode: 'certified_deprecation_requires_approval',
  errorParams: {
    entityType: 'data_product', entityId: 'prod-1', entityName: 'Orders', certificationLevel: 2,
  },
};

function render() {
  renderWithProviders(
    <RequestProductActionDialog
      isOpen={true}
      onOpenChange={vi.fn()}
      productId="prod-1"
      productName="Orders"
      productStatus="active"
      defaultRequestType="status_change"
      canDirectStatusChange={true}
    />,
  );
}

function chooseDeprecate() {
  const target = screen.getAllByRole('combobox').find(
    (select) => select.querySelector('option[value="deprecated"]'),
  ) as HTMLSelectElement;
  fireEvent.change(target, { target: { value: 'deprecated' } });
}

describe('RequestProductActionDialog certified deprecation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPost.mockReset();  // drop answers a failed test left queued
    mockGet.mockResolvedValue({ data: [] });
    mockLookupWorkflowId.mockResolvedValue(null);
  });

  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('shows the refusal in the UI language and sends a request instead', async () => {
    await i18n.changeLanguage('pt');
    mockPost.mockResolvedValueOnce(REFUSED).mockResolvedValueOnce({ data: { request_id: 'r-1' } });
    render();

    chooseDeprecate();
    fireEvent.click(screen.getByRole('button', {
      name: i18n.t('data-products:requestAction.types.statusChange.titleDirect'),
    }));

    const text = 'Orders é certificado, então só pode ser descontinuado por uma solicitação de '
      + 'mudança de status aprovada. Solicite a mudança de status.';
    expect(await screen.findByText(text)).toBeInTheDocument();
    expect(mockPost.mock.calls[0][0]).toBe('/api/data-products/prod-1/change-status');

    fireEvent.click(screen.getByRole('button', { name: 'Solicitar a mudança de status' }));

    const justification = await screen.findByRole('textbox');
    fireEvent.change(justification, {
      target: { value: 'Replaced by Orders v2; every consumer has moved.' },
    });
    fireEvent.click(screen.getByRole('button', {
      name: i18n.t('data-products:requestAction.buttons.sendRequest'),
    }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(2));
    expect(mockPost.mock.calls[1][0]).toBe('/api/data-products/prod-1/request-status-change');
    expect(mockPost.mock.calls[1][1]).toMatchObject({
      target_status: 'deprecated',
      justification: 'Replaced by Orders v2; every consumer has moved.',
      current_status: 'active',
    });
  });

  it('offers no request for another refusal', async () => {
    mockPost.mockResolvedValueOnce({
      data: {}, error: 'Invalid status transition', errorCode: 'invalid_status_transition',
      errorParams: { fromStatus: 'active', toStatus: 'deprecated' },
    });
    render();

    chooseDeprecate();
    fireEvent.click(screen.getByRole('button', {
      name: i18n.t('data-products:requestAction.types.statusChange.titleDirect'),
    }));

    expect(await screen.findByText('Invalid status transition')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: i18n.t('workflow-gates:requestInstead') }))
      .toBeNull();
  });
});
