/**
 * Linking a contract to an output port PUTs the whole product. The body must not
 * carry `tags`: a loaded `[]` would remove every tag, and a loaded tag list would
 * drop a tag added while the dialog was open (#1435).
 */
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import LinkContractToPortDialog from './link-contract-to-port-dialog';

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));
vi.mock('@/components/common/entity-version-picker', () => ({
  default: ({ onChange }: { onChange: (value: unknown) => void }) => (
    <button
      type="button"
      onClick={() => onChange({ scope: 'entity', entityKind: 'contract', entityId: 'contract-1' })}
    >
      pick contract
    </button>
  ),
}));
vi.mock('@/components/data-contracts/create-contract-inline-dialog', () => ({
  default: () => null,
}));

const product = (tags: unknown[]) => ({
  id: 'prod-1',
  name: 'Existing Product',
  status: 'active',
  outputPorts: [{ name: 'orders', version: '1.0.0', type: 'Table', assetType: 'Table' }],
  tags,
});

let fetchMock: ReturnType<typeof vi.fn>;

const putBody = () => {
  const call = fetchMock.mock.calls.find(([, init]) => (init as RequestInit)?.method === 'PUT');
  return call ? JSON.parse((call[1] as RequestInit).body as string) : undefined;
};

const linkContract = async () => {
  fireEvent.click(screen.getByRole('button', { name: 'pick contract' }));
  fireEvent.click(screen.getByRole('button', { name: 'Link Contract' }));
  await waitFor(() => expect(putBody()).toBeDefined());
};

describe('LinkContractToPortDialog — tags in the product PUT', () => {
  const setup = (loaded: unknown[]) => {
    fetchMock = vi.fn((_url: RequestInfo | URL, init?: RequestInit) => Promise.resolve({
      ok: true,
      json: () => Promise.resolve(init?.method === 'PUT' ? {} : product(loaded)),
    } as Response));
    global.fetch = fetchMock as any;
    renderWithProviders(
      <LinkContractToPortDialog
        isOpen={true}
        onOpenChange={vi.fn()}
        productId="prod-1"
        portIndex={0}
        onSuccess={vi.fn()}
      />,
    );
  };

  beforeEach(() => {
    fetchMock = vi.fn();
  });

  it('omits tags when the loaded product has none', async () => {
    setup([]);
    await linkContract();
    expect(putBody()).not.toHaveProperty('tags');
    expect(putBody().outputPorts[0].contractId).toBe('contract-1');
  });

  it('omits tags when the loaded product has tags, so a tag added meanwhile is kept', async () => {
    setup([{ tag_id: 't1', fully_qualified_name: 'ns/pii', assigned_value: null }]);
    await linkContract();
    expect(putBody()).not.toHaveProperty('tags');
  });
});
