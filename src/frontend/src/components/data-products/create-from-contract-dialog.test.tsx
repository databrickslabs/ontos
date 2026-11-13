/**
 * Creating a product from a contract offers the dashboards built on the
 * contract's semantic models as extra deliverables.
 */
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import i18n from '@/i18n/config';
import { renderWithProviders } from '@/test/utils';
import CreateFromContractDialog from './create-from-contract-dialog';

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('@/hooks/use-api', () => ({ useApi: () => api }));

const DASHBOARDS = [
  { id: 'd1', name: 'Orders Overview', location: 'p~p1.wb~wb1.v~v1', url: 'https://t/#/views/OrdersOverview/OrdersOverview' },
  { id: 'd2', name: 'Revenue by Status', location: 'p~p1.wb~wb1.v~v2', url: null },
];

const renderDialog = () =>
  renderWithProviders(<CreateFromContractDialog isOpen onOpenChange={() => {}} contractId="c-1" contractName="TPCH Orders" />);

const submit = async () => {
  fireEvent.change(screen.getByLabelText(i18n.t('data-products:createFromContract.productNameLabel')), { target: { value: 'Orders Analytics' } });
  fireEvent.click(screen.getByRole('button', { name: i18n.t('data-products:createFromContract.createButton') }));
  await waitFor(() => expect(api.post).toHaveBeenCalled());
  return api.post.mock.calls[0][1];
};

describe('CreateFromContractDialog', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset().mockResolvedValue({ data: { id: 'p-1' } });
  });

  it('lists the dashboards and adds them by default', async () => {
    api.get.mockResolvedValue({ data: DASHBOARDS });
    renderDialog();

    expect(await screen.findByText('Orders Overview')).toBeInTheDocument();
    expect(screen.getByText('Revenue by Status')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/api/data-products/from-contract/c-1/dashboards');
    expect(await submit()).toMatchObject({ contract_id: 'c-1', include_dashboards: true });
  });

  it('leaves them out when unchecked', async () => {
    api.get.mockResolvedValue({ data: DASHBOARDS });
    renderDialog();

    fireEvent.click(await screen.findByLabelText(i18n.t('data-products:createFromContract.includeDashboardsLabel')));
    expect(await submit()).toMatchObject({ include_dashboards: false });
  });

  it('shows no option when no dashboard reads the contract', async () => {
    api.get.mockResolvedValue({ data: [] });
    renderDialog();

    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(screen.queryByLabelText(i18n.t('data-products:createFromContract.includeDashboardsLabel'))).not.toBeInTheDocument();
    expect(await submit()).toMatchObject({ include_dashboards: false });
  });
});
