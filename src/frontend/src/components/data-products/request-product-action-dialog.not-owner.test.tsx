/**
 * A review requested by someone who doesn't own the product is refused with
 * `not_product_owner` (#1117); the dialog shows that error in the UI language.
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
  return {
    ...actual,
    useApprovalWizardTrigger: () => ({ lookupWorkflowId: mockLookupWorkflowId }),
  };
});
vi.mock('@/stores/notifications-store', () => ({
  useNotificationsStore: (selector: any) =>
    selector({ refreshNotifications: mockRefreshNotifications }),
}));

const NOT_OWNER = "Only the product's owners or an admin can request its review.";
const NOT_OWNER_PT =
  'Somente os proprietários do produto ou um administrador podem solicitar a revisão dele.';

describe('RequestProductActionDialog review requested by a non-owner', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it.each([
    ['en', NOT_OWNER],
    ['pt', NOT_OWNER_PT],
  ])('shows the refusal in %s', async (language, expected) => {
    mockGet.mockResolvedValue({ data: [] });
    mockLookupWorkflowId.mockResolvedValue(null);
    mockPost.mockResolvedValue({
      data: {}, error: 'raw server text', errorCode: 'not_product_owner', errorParams: null,
    });
    await i18n.changeLanguage(language);

    renderWithProviders(
      <RequestProductActionDialog
        isOpen={true}
        onOpenChange={vi.fn()}
        productId="prod-1"
        productName="Test Product"
        productStatus="draft"
        defaultRequestType="review"
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /Enviar solicitação|Send Request/i }));

    expect(mockPost).toHaveBeenLastCalledWith(
      '/api/data-products/prod-1/request-review', expect.anything(),
    );
    expect((await screen.findAllByText(expected)).length).toBeGreaterThan(0);
  });
});
