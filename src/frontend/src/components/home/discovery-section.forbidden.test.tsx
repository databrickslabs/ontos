/** A 403 from published products is an empty card; other failures show the translated error. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/utils';

vi.mock('@/hooks/use-domains', () => ({
  useDomains: () => ({ domains: [], loading: false, getDomainName: () => '' }),
}));

vi.mock('@/hooks/use-approval-wizard-trigger', () => ({
  useApprovalWizardTrigger: () => ({ lookupWorkflowId: vi.fn() }),
}));

import DiscoverySection from './discovery-section';

const answer = (status: number, body: unknown = {}) => ({
  ok: status < 400,
  status,
  json: async () => body,
});

describe('DiscoverySection popular products', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn(async () => answer(200, [])) as any;
  });

  it('shows the empty state, not the HTTP status, on 403', async () => {
    globalThis.fetch = vi.fn(async () => answer(403)) as any;
    renderWithProviders(<DiscoverySection />);
    expect(await screen.findByText('No data products found.')).toBeTruthy();
    expect(screen.queryByText(/HTTP/)).toBeNull();
  });

  it('shows no empty state until the products answer, then the products', async () => {
    let release: (v: any) => void = () => {};
    globalThis.fetch = vi.fn((url: any) =>
      String(url).includes('/published')
        ? new Promise((r) => { release = r; })
        : Promise.resolve(answer(200, [])),
    ) as any;
    renderWithProviders(<DiscoverySection />);
    expect(screen.queryByText('No data products found.')).toBeNull();
    release(answer(200, [{ id: 'p1', name: 'Orders Product', status: 'active' }]));
    expect(await screen.findByText('Orders Product')).toBeTruthy();
    expect(screen.queryByText('No data products found.')).toBeNull();
  });

  it('shows the translated error, not the HTTP status, on 500', async () => {
    globalThis.fetch = vi.fn(async () => answer(500)) as any;
    renderWithProviders(<DiscoverySection />);
    expect(await screen.findByText('Failed to load data products')).toBeTruthy();
    expect(screen.queryByText(/HTTP/)).toBeNull();
  });
});
