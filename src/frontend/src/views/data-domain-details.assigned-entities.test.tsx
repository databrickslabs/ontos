/**
 * An asset listed under the domain's "Assigned entities" opens the asset's
 * detail page (#1496).
 */
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useParams } from 'react-router-dom';

import DataDomainDetailsView from './data-domain-details';

const api = vi.hoisted(() => ({
  get: vi.fn(),
  toast: vi.fn(),
}));

vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: api.get, post: vi.fn(), delete: vi.fn() }) }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: api.toast }) }));
vi.mock('@/hooks/use-domains', () => ({ useDomains: () => ({ domains: [], refetch: vi.fn() }) }));

function AssetPage() {
  const { assetId } = useParams();
  return <p data-testid="asset-page">{assetId}</p>;
}

describe('DataDomainDetailsView assigned entities', () => {
  it('opens an assigned asset on its detail page', async () => {
    api.get.mockImplementation(async (url: string) => {
      if (url === '/api/data-domains/d-1') return { data: { id: 'd-1', name: 'Finance' } };
      if (url.startsWith('/api/assets?')) return { data: [{ id: 'a-1', name: 'Ledger', primary_domain_id: 'd-1' }] };
      return { data: [] };
    });
    render(
      <MemoryRouter initialEntries={['/settings/data-domains/d-1']}>
        <Routes>
          <Route path="/settings/data-domains/:domainId" element={<DataDomainDetailsView />} />
          <Route path="/assets/:assetId" element={<AssetPage />} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByText('Ledger'));

    expect(await screen.findByTestId('asset-page')).toHaveTextContent('a-1');
  });
});
