/**
 * Link contract > Create New Contract prefills the contract's domains with the
 * product's domain ids. `product.domain` is the primary domain's NAME: sent as an id it
 * made the contract create fail with "Domain ... not found".
 */
import { waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import LinkContractToPortDialog from './link-contract-to-port-dialog';

vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock('@/components/common/entity-version-picker', () => ({ default: () => null }));

const prefill = vi.fn();
vi.mock('@/components/data-contracts/create-contract-inline-dialog', () => ({
  default: (props: { prefillData?: unknown }) => {
    prefill(props.prefillData);
    return null;
  },
}));

describe('LinkContractToPortDialog: Create New Contract prefill', () => {
  it('passes the product domain ids, not its domain name', async () => {
    global.fetch = vi.fn(() => Promise.resolve({
      ok: true,
      json: () => Promise.resolve({
        id: 'prod-1', name: 'P', status: 'active', outputPorts: [],
        domain: 'Sales', domain_ids: ['d-1', 'd-2'], primary_domain_id: 'd-2',
        tenant: 'acme',
      }),
    } as Response)) as any;
    renderWithProviders(
      <LinkContractToPortDialog
        isOpen onOpenChange={vi.fn()} productId="prod-1" portIndex={0} onSuccess={vi.fn()}
      />,
    );

    await waitFor(() => expect(prefill).toHaveBeenLastCalledWith(
      expect.objectContaining({ domainIds: ['d-1', 'd-2'], primaryDomainId: 'd-2' }),
    ));
    const last = prefill.mock.calls[prefill.mock.calls.length - 1][0];
    expect(last).not.toHaveProperty('domainId');
    expect(last).not.toHaveProperty('domain');
  });
});
