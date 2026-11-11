/**
 * The request dialog's toasts name the request type in the UI language (#1078):
 * they showed the raw type ("deploy") inside the translated sentence.
 */
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { renderWithProviders } from '@/test/utils';
import RequestContractActionDialog from './request-contract-action-dialog';

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockToast = vi.fn();
const mockRefreshNotifications = vi.fn();

vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: mockToast }) }));
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: mockGet, post: mockPost }) }));
vi.mock('@/stores/notifications-store', () => ({
  useNotificationsStore: (selector: any) => selector({ refreshNotifications: mockRefreshNotifications }),
}));

async function submitDeployRequest() {
  renderWithProviders(
    <RequestContractActionDialog
      isOpen={true}
      onOpenChange={vi.fn()}
      contractId="c-1"
      contractName="Orders"
      contractStatus="active"
    />,
  );
  const send = await screen.findByRole('button', { name: i18n.t('data-contracts:requests.sendRequest') });
  fireEvent.click(send);
  await waitFor(() => expect(mockToast).toHaveBeenCalledTimes(1));
  return mockToast.mock.calls[0][0];
}

describe('RequestContractActionDialog request type in its toasts', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGet.mockImplementation(async (url: string) => (
      url.includes('deployment-policy')
        ? { data: { allowed_catalogs: ['*'], allowed_schemas: ['*'], require_approval: true } }
        : { data: [] }
    ));
  });

  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('names a submitted request in the UI language', async () => {
    await i18n.changeLanguage('pt');
    mockPost.mockResolvedValue({ data: { workflow_status: 'paused' } });

    const toast = await submitDeployRequest();

    expect(toast.description).toBe(
      'Sua solicitação de implantação foi enviada e você será notificado da decisão.',
    );
  });

  it('names the request whose workflow failed in the UI language', async () => {
    await i18n.changeLanguage('pt');
    mockPost.mockResolvedValue({
      data: {
        workflow_status: 'failed',
        workflow_error_code: 'request_workflow_failed',
        workflow_error_params: { workflow: 'Contract Deploy Approval' },
      },
    });

    const toast = await submitDeployRequest();

    expect(toast.description).toBe(
      'Ninguém foi acionado para decidir sobre sua solicitação de implantação: '
      + 'o workflow "Contract Deploy Approval" não pôde ser iniciado. Contate um administrador.',
    );
  });

  it('keeps the English sentence in English', async () => {
    mockPost.mockResolvedValue({ data: { workflow_status: 'paused' } });

    const toast = await submitDeployRequest();

    expect(toast.description).toBe(
      'Your deploy request has been submitted and you will be notified of the decision.',
    );
  });

  it('names the failed workflows when some succeed/pause and others fail (partial failure)', async () => {
    await i18n.changeLanguage('pt');
    mockPost.mockResolvedValue({
      data: {
        workflow_status: 'partially_failed',
        workflow_error_code: 'request_workflow_partially_failed',
        workflow_error_params: { failed_workflows: ['Deploy Audit', 'Compliance Check'] },
      },
    });

    const toast = await submitDeployRequest();

    expect(toast.description).toBe(
      'Um dos workflows de solicitação de implantação falhou: Deploy Audit, Compliance Check. '
      + 'Outras aprovações podem ainda estar pendentes.',
    );
    expect(toast.description).not.toContain('Ninguém foi acionado');
  });

  it('shows partial failure toast in English', async () => {
    mockPost.mockResolvedValue({
      data: {
        workflow_status: 'partially_failed',
        workflow_error_code: 'request_workflow_partially_failed',
        workflow_error_params: { failed_workflows: ['Deploy Approval'] },
      },
    });

    const toast = await submitDeployRequest();

    expect(toast.description).toBe(
      'One of the deploy request workflows failed: Deploy Approval. Other approvals may still be pending.',
    );
    expect(toast.description).not.toContain('Nobody was asked');
  });
});
