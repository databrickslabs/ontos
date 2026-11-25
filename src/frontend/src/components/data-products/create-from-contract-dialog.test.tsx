/**
 * CreateFromContractDialog loads the data product types from the API and
 * preselects the default (#1209). Which types are offered is covered by
 * pickableDataProductTypes in lib/data-product-types.test.ts.
 */
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import CreateFromContractDialog from './create-from-contract-dialog';
import type { DataProductType } from '@/types/data-product-type';

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

const productType = (key: string, label: string, overrides: Partial<DataProductType> = {}): DataProductType => ({
  id: `id-${key}`,
  key,
  label,
  sort_order: 1,
  is_active: true,
  is_default: false,
  is_imported: false,
  is_seeded: true,
  has_seeded_label: true,
  usage_count: 0,
  ...overrides,
});

const PRODUCT_TYPES: DataProductType[] = [
  productType('source-aligned', 'Source-Aligned', { is_default: true }),
  productType('aggregate', 'Aggregate'),
  productType('sink', 'Sink', { is_active: false }),
];

const json = (body: unknown) =>
  new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });

const setupFetchMock = (types: DataProductType[] = PRODUCT_TYPES) => {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString();
    if (url.startsWith('/api/data-product-types')) return Promise.resolve(json(types));
    return Promise.resolve(json({ id: 'new-product' }));
  });
  global.fetch = fetchMock as any;
  return fetchMock;
};

const renderDialog = (onSuccess = vi.fn()) =>
  renderWithProviders(
    <CreateFromContractDialog
      isOpen={true}
      onOpenChange={vi.fn()}
      contractId="contract-1"
      contractName="Orders Contract"
      onSuccess={onSuccess}
    />,
  );

const typeTrigger = () => screen.getByRole('combobox', { name: /Product Type/ });

const submittedBody = async (fetchMock: ReturnType<typeof setupFetchMock>) => {
  let body: any;
  await waitFor(() => {
    const call = fetchMock.mock.calls.find(([url]: any[]) => String(url) === '/api/data-products/from-contract');
    expect(call).toBeTruthy();
    body = JSON.parse((call as any)[1].body as string);
  });
  return body;
};

const fillAndSubmit = () => {
  fireEvent.change(screen.getByLabelText(/Product Name/), { target: { value: 'Orders Product' } });
  fireEvent.click(screen.getByRole('button', { name: /Create Product/ }));
};

describe('CreateFromContractDialog — product type', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('preselects the default type and sends it', async () => {
    const fetchMock = setupFetchMock();
    renderDialog();

    await waitFor(() => expect(typeTrigger()).toHaveTextContent('Source-Aligned'));
    fillAndSubmit();

    expect((await submittedBody(fetchMock)).product_type).toBe('source-aligned');
  });

  it('can be submitted without a type when no default is set', async () => {
    const fetchMock = setupFetchMock(PRODUCT_TYPES.map((t) => ({ ...t, is_default: false })));
    renderDialog();

    await waitFor(() => expect(typeTrigger()).not.toBeDisabled());
    expect(typeTrigger()).toHaveTextContent('Select product type');
    fillAndSubmit();

    const body = await submittedBody(fetchMock);
    expect(body).not.toHaveProperty('product_type');
    expect(body.product_name).toBe('Orders Product');
  });

  it('shows a refused type in the user\'s language', async () => {
    const fetchMock = setupFetchMock();
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (url.startsWith('/api/data-product-types')) return Promise.resolve(json(PRODUCT_TYPES));
      return Promise.resolve(
        new Response(
          JSON.stringify({
            detail: {
              code: 'unknown_data_product_type',
              message: "Unknown or inactive data product type: 'source-aligned'",
              params: { key: 'source-aligned' },
            },
          }),
          { status: 400, headers: { 'Content-Type': 'application/json' } },
        ),
      );
    });
    renderDialog();

    await waitFor(() => expect(typeTrigger()).toHaveTextContent('Source-Aligned'));
    fillAndSubmit();

    expect(
      await screen.findByText(/The product type "source-aligned" doesn't exist or has been deactivated/),
    ).toBeInTheDocument();
  });
});
