/**
 * The request dialog shows the API's coded errors in the UI language (#1078),
 * e.g. a review requested for a draft without a schema.
 */
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { renderWithProviders } from '@/test/utils';
import RequestContractActionDialog from './request-contract-action-dialog';

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockToast = vi.fn();

vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: mockToast }) }));
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: mockGet, post: mockPost }) }));
vi.mock('@/stores/notifications-store', () => ({
  useNotificationsStore: (selector: any) => selector({ refreshNotifications: vi.fn() }),
}));

const SCHEMA_REQUIRED = {
  data: {},
  error: 'A schema is required before a contract can be proposed for review.',
  errorCode: 'review_schema_required',
  errorParams: {},
};

async function submit() {
  renderWithProviders(
    <RequestContractActionDialog
      isOpen={true}
      onOpenChange={vi.fn()}
      contractId="c-1"
      contractName="Orders"
      contractStatus="draft"
    />,
  );
  fireEvent.click(await screen.findByRole('button', { name: i18n.t('data-contracts:requests.sendRequest') }));
  await waitFor(() => expect(mockToast).toHaveBeenCalledTimes(1));
  return mockToast.mock.calls[0][0];
}

describe('RequestContractActionDialog coded errors', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGet.mockImplementation(async (url: string) => (
      url.includes('deployment-policy')
        ? { data: { allowed_catalogs: ['*'], allowed_schemas: ['*'], require_approval: true } }
        : { data: [] }
    ));
    mockPost.mockResolvedValue(SCHEMA_REQUIRED);
  });

  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('shows the error in the UI language', async () => {
    await i18n.changeLanguage('pt');

    const toast = await submit();

    const text = 'O contrato precisa de um schema antes de ser proposto para revisão.';
    expect(toast.variant).toBe('destructive');
    expect(toast.description).toBe(text);
    expect(screen.getByText(text)).toBeInTheDocument();
  });

  it('keeps the English message in English', async () => {
    const toast = await submit();

    expect(toast.description).toBe(SCHEMA_REQUIRED.error);
  });
});
