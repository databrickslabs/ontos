/**
 * Editing a deliverable must not drop the fields the form does not show
 * (asset, server, ...), and a dashboard deliverable offers a dashboard picker.
 */
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { renderWithProviders } from '@/test/utils';
import type { OutputPort } from '@/types/data-product';
import OutputPortFormDialog from './output-port-form-dialog';

// Stands in for the asset search: confirming picks the "Revenue by Status" dashboard
vi.mock('@/components/common/asset-selector', () => ({
  AssetSelector: ({ isOpen, onConfirm }: { isOpen: boolean; onConfirm: (assets: unknown[]) => void }) =>
    isOpen ? (
      <button onClick={() => onConfirm([{ id: 'a-2', name: 'Revenue by Status', location: 'p~p1.wb~wb1.v~v2', relationshipType: '' }])}>
        pick-dashboard
      </button>
    ) : null,
}));

const NEW_URL = 'https://tableau.example.com/#/views/OrdersOverview/RevenuebyStatus';

const stubFetch = (assetDetails: Response | Error) => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url === '/api/assets/a-2') {
      if (assetDetails instanceof Error) throw assetDetails;
      return assetDetails;
    }
    return { ok: true, json: async () => [] };
  }));
};

const DASHBOARD_PORT: OutputPort = {
  id: 'port-1',
  name: 'Orders Overview',
  version: '1.0.0',
  type: 'dashboard',
  assetType: 'dashboard',
  assetIdentifier: 'p~p1.wb~wb1.v~v1',
  server: { location: 'https://tableau.example.com/#/views/OrdersOverview/OrdersOverview' },
  containsPii: false,
  autoApprove: false,
};

describe('OutputPortFormDialog', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => [] })));
  });

  afterEach(async () => {
    vi.unstubAllGlobals();
    await i18n.changeLanguage('en');
  });

  it('keeps the asset and server of an edited dashboard deliverable', async () => {
    const onSubmit = vi.fn(async () => {});
    renderWithProviders(
      <OutputPortFormDialog isOpen onOpenChange={() => {}} onSubmit={onSubmit} initial={DASHBOARD_PORT} />,
    );

    fireEvent.change(screen.getByLabelText(i18n.t('common:labels.description')), { target: { value: 'Revenue KPIs' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      id: 'port-1',
      description: 'Revenue KPIs',
      assetType: 'dashboard',
      assetIdentifier: 'p~p1.wb~wb1.v~v1',
      server: DASHBOARD_PORT.server,
    }));
  });

  it('offers a dashboard picker for dashboard deliverables only', () => {
    renderWithProviders(
      <OutputPortFormDialog isOpen onOpenChange={() => {}} onSubmit={vi.fn()} initial={DASHBOARD_PORT} />,
    );
    const choose = i18n.t('data-products:outputPortForm.actions.chooseDashboard');
    expect(screen.getByRole('button', { name: choose })).toBeInTheDocument();
    expect(screen.getByText(DASHBOARD_PORT.server!.location!)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(i18n.t('common:labels.type')), { target: { value: 'table' } });
    expect(screen.queryByRole('button', { name: choose })).not.toBeInTheDocument();
  });

  const pickAndSave = async () => {
    const onSubmit = vi.fn(async () => {});
    renderWithProviders(
      <OutputPortFormDialog isOpen onOpenChange={() => {}} onSubmit={onSubmit} initial={DASHBOARD_PORT} />,
    );
    fireEvent.click(screen.getByRole('button', { name: i18n.t('data-products:outputPortForm.actions.chooseDashboard') }));
    fireEvent.click(screen.getByText('pick-dashboard'));
    await waitFor(() => expect(screen.getByText('Revenue by Status')).toBeInTheDocument());
    return onSubmit;
  };

  it('a picked dashboard becomes the delivered asset, with its live link', async () => {
    stubFetch({ ok: true, json: async () => ({ properties: { dashboardUrl: NEW_URL } }) } as Response);
    const onSubmit = await pickAndSave();
    await waitFor(() => expect(screen.getByText(NEW_URL)).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      assetType: 'dashboard',
      assetIdentifier: 'p~p1.wb~wb1.v~v2',
      server: { location: NEW_URL },
    }));
  });

  it('drops the previous dashboard link when the new one cannot be looked up', async () => {
    stubFetch(new Error('offline'));
    const onSubmit = await pickAndSave();

    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const port = (onSubmit.mock.calls[0] as unknown[])[0] as OutputPort;
    expect(port.assetIdentifier).toBe('p~p1.wb~wb1.v~v2');
    expect(port.server?.location).toBeUndefined();
  });
});
