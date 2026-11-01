/**
 * Approving a deployment request records the decision and deploys nothing
 * (#1151 item 1), so the dialog no longer offers "execute deployment".
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import HandleDeployRequestDialog from './handle-deploy-request-dialog';

const api = vi.hoisted(() => ({ post: vi.fn(), toast: vi.fn() }));
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ post: api.post }) }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: api.toast }) }));

const renderDialog = () => render(
  <HandleDeployRequestDialog
    isOpen onOpenChange={() => {}} contractId="c1" requesterEmail="p@example.com"
    onDecisionMade={() => {}}
  />,
);

beforeEach(() => {
  api.post.mockReset();
  api.toast.mockReset();
  api.post.mockResolvedValue({ data: { message: 'ok' } });
});

describe('HandleDeployRequestDialog', () => {
  it('has no option to execute the deployment', () => {
    renderDialog();

    expect(screen.queryByRole('checkbox')).toBeNull();
    expect(screen.queryByText(/Approve & Deploy/)).toBeNull();
  });

  it('sends only the decision and the message', async () => {
    renderDialog();
    fireEvent.change(screen.getByLabelText(/Response Message/), { target: { value: 'ok' } });

    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(api.post).toHaveBeenCalledWith(
      '/api/data-contracts/c1/handle-deploy', { decision: 'approve', message: 'ok' },
    );
    expect(api.toast.mock.calls[0][0].description).toBe('Deployment request has been approved.');
  });

  it('reports a denial', async () => {
    renderDialog();

    fireEvent.click(screen.getByRole('button', { name: 'Deny' }));

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(api.post.mock.calls[0][1]).toEqual({ decision: 'deny', message: undefined });
    expect(api.toast.mock.calls[0][0].description).toBe('Deployment request has been denied.');
  });
});
