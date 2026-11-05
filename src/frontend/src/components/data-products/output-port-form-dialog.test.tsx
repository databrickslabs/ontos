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
});
