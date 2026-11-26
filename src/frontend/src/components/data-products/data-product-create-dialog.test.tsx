/**
 * Tests for DataProductCreateDialog, the dialog that creates and edits a
 * product's metadata: the Consumer Groups picker, the status field and the
 * product type picker (types come from GET /api/data-product-types).
 */
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import DataProductCreateDialog from './data-product-create-dialog';
import type { DataProduct } from '@/types/data-product';
import type { DataProductType } from '@/types/data-product-type';

// Mock external service hooks so the dialog mounts cleanly.
vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

vi.mock('@/hooks/use-domains', () => ({
  useDomains: () => ({ domains: [], loading: false }),
}));

vi.mock('@/hooks/use-teams', () => ({
  useTeams: () => ({ teams: [], loading: false }),
}));

vi.mock('@/stores/project-store', () => ({
  useProjectContext: () => ({
    currentProject: null,
    availableProjects: [],
    isLoading: false,
    fetchUserProjects: vi.fn(),
  }),
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
  productType('source-aligned', 'Source-Aligned', { sort_order: 1, is_default: true }),
  productType('aggregate', 'Composite', { sort_order: 2, has_seeded_label: false }),
  productType('sink', 'Sink', { sort_order: 3, is_active: false }),
];

// fetch is hit by ConsumerGroupsPicker (GET /api/workspace/groups), the type
// picker (GET /api/data-product-types) and the dialog's submit handler
// (POST/PUT /api/data-products). Tests inspect the recorded calls per assertion.
const setupFetchMock = (types: DataProductType[] = PRODUCT_TYPES) => {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();
    if (url.startsWith('/api/data-product-types')) {
      return Promise.resolve(
        new Response(JSON.stringify(types), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    }
    if (url.includes('/api/workspace/groups')) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve([
            { id: 'g1', display_name: 'account-ops-users' },
            { id: 'g2', display_name: 'analytics-readers' },
          ]),
      } as Response);
    }
    // Submit handlers — return whatever was sent so onSuccess gets a payload.
    let body: any = {};
    try {
      body = init?.body ? JSON.parse(init.body as string) : {};
    } catch {
      body = {};
    }
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({ id: 'new-id', ...body }),
    } as Response);
  });
  global.fetch = fetchMock as any;
  return fetchMock;
};

const baseProduct: DataProduct = {
  id: 'prod-1',
  apiVersion: 'v1.0.0',
  kind: 'DataProduct',
  name: 'Existing Product',
  version: '1.0.0',
  status: 'draft',
  inputPorts: [],
  outputPorts: [],
  managementPorts: [],
  support: [],
  authoritativeDefinitions: [],
  customProperties: [],
  tags: [],
};

describe('DataProductCreateDialog — Consumer Groups picker wiring', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupFetchMock();
  });

  it('renders the Consumer Groups picker when open in edit mode', async () => {
    renderWithProviders(
      <DataProductCreateDialog
        open={true}
        onOpenChange={vi.fn()}
        onSuccess={vi.fn()}
        product={baseProduct}
        mode="edit"
      />
    );

    expect(
      screen.getByRole('heading', { name: /Edit Data Product Metadata/ })
    ).toBeInTheDocument();
    // Section label + the picker's search input both have to be present.
    expect(screen.getByText('Consumer Groups')).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText(/Search workspace groups/)
    ).toBeInTheDocument();
  });

  it('hydrates the picker from the incoming product.consumer_principals', async () => {
    const productWithGroups: DataProduct = {
      ...baseProduct,
      consumer_principals: [{ type: 'group', value: 'pre-existing-group' }],
    };

    renderWithProviders(
      <DataProductCreateDialog
        open={true}
        onOpenChange={vi.fn()}
        onSuccess={vi.fn()}
        product={productWithGroups}
        mode="edit"
      />
    );

    // Pre-existing group renders as a chip via the picker's Badge.
    expect(await screen.findByText('pre-existing-group')).toBeInTheDocument();
    expect(
      screen.getByLabelText('Remove pre-existing-group')
    ).toBeInTheDocument();
  });

  it('includes consumer_principals in the PUT payload after a free-text add', async () => {
    const fetchMock = setupFetchMock();
    const onSuccess = vi.fn();

    renderWithProviders(
      <DataProductCreateDialog
        open={true}
        onOpenChange={vi.fn()}
        onSuccess={onSuccess}
        product={baseProduct}
        mode="edit"
      />
    );

    // Free-text add via Enter key — bypasses Radix Select hangs in jsdom and
    // doesn't depend on the /api/workspace/groups list being rendered.
    const search = screen.getByPlaceholderText(/Search workspace groups/);
    fireEvent.change(search, { target: { value: 'account-ops-users' } });
    fireEvent.keyDown(search, { key: 'Enter', code: 'Enter' });

    // Save Changes
    const saveBtn = screen.getByRole('button', { name: /Save Changes/ });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      const putCall = fetchMock.mock.calls.find(([url, init]: any[]) => {
        const u = typeof url === 'string' ? url : url.toString();
        return u.startsWith('/api/data-products/') && init?.method === 'PUT';
      });
      expect(putCall).toBeTruthy();
      const body = JSON.parse(putCall![1]!.body as string);
      expect(body.consumer_principals).toEqual([
        { type: 'group', value: 'account-ops-users' },
      ]);
    });
  });
});

describe('DataProductCreateDialog — status', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupFetchMock();
  });

  it('keeps the status read-only when editing, pointing to Change Status', () => {
    renderWithProviders(
      <DataProductCreateDialog
        open={true}
        onOpenChange={vi.fn()}
        onSuccess={vi.fn()}
        product={{ ...baseProduct, status: 'active' }}
        mode="edit"
      />
    );

    expect(screen.getByRole('combobox', { name: /Status/ })).toBeDisabled();
    expect(screen.getByText(/The status changes with Change Status on the page/)).toBeInTheDocument();
  });

  it('lets the status be chosen when creating', () => {
    renderWithProviders(
      <DataProductCreateDialog open={true} onOpenChange={vi.fn()} onSuccess={vi.fn()} mode="create" />
    );

    expect(screen.getByRole('combobox', { name: /Status/ })).not.toBeDisabled();
    expect(screen.queryByText(/The status changes with Change Status on the page/)).not.toBeInTheDocument();
  });
});

describe('DataProductCreateDialog — product type', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const typeTrigger = () => screen.getByRole('combobox', { name: /Product Type/ });

  const submittedBody = async (fetchMock: ReturnType<typeof setupFetchMock>, method: string) => {
    let body: any;
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url, init]: any[]) => {
        const u = typeof url === 'string' ? url : url.toString();
        return u.startsWith('/api/data-products') && init?.method === method;
      });
      expect(call).toBeTruthy();
      body = JSON.parse(call![1]!.body as string);
    });
    return body;
  };

  const productTypeValues = (body: any) =>
    (body.customProperties || [])
      .filter((cp: any) => cp.property === 'productType')
      .map((cp: any) => cp.value);

  it('loads the types and preselects the default when creating', async () => {
    const fetchMock = setupFetchMock();
    renderWithProviders(
      <DataProductCreateDialog open={true} onOpenChange={vi.fn()} onSuccess={vi.fn()} mode="create" />
    );

    await waitFor(() => expect(typeTrigger()).toHaveTextContent('Source-Aligned'));
    expect(fetchMock.mock.calls.some(([url]: any[]) => String(url).startsWith('/api/data-product-types'))).toBe(true);

    fireEvent.change(screen.getByLabelText(/Product Name/), { target: { value: 'New Product' } });
    fireEvent.click(screen.getByRole('button', { name: /Create Product/ }));

    expect(productTypeValues(await submittedBody(fetchMock, 'POST'))).toEqual(['source-aligned']);
  });

  it('offers None and the active types, with renamed labels as entered', async () => {
    setupFetchMock();
    renderWithProviders(
      <DataProductCreateDialog open={true} onOpenChange={vi.fn()} onSuccess={vi.fn()} mode="create" />
    );
    await waitFor(() => expect(typeTrigger()).not.toBeDisabled());

    // Opening a Radix Select hangs under jsdom; read the options of the hidden
    // native <select> Radix renders next to a trigger inside a form instead.
    const nativeSelect = typeTrigger().parentElement!.querySelector('select')!;
    await waitFor(() =>
      expect(Array.from(nativeSelect.options).map((o) => o.textContent)).toEqual([
        'None',
        'Source-Aligned',
        'Composite',
      ]),
    );
  });

  it('leaves the type empty when no default is set', async () => {
    setupFetchMock(PRODUCT_TYPES.map((t) => ({ ...t, is_default: false })));
    renderWithProviders(
      <DataProductCreateDialog open={true} onOpenChange={vi.fn()} onSuccess={vi.fn()} mode="create" />
    );

    await waitFor(() => expect(typeTrigger()).not.toBeDisabled());
    expect(typeTrigger()).toHaveTextContent('None');
  });

  it("keeps a product's inactive type when editing", async () => {
    const fetchMock = setupFetchMock();
    renderWithProviders(
      <DataProductCreateDialog
        open={true}
        onOpenChange={vi.fn()}
        onSuccess={vi.fn()}
        product={{ ...baseProduct, customProperties: [{ property: 'productType', value: 'sink' }] }}
        mode="edit"
      />
    );

    await waitFor(() => expect(typeTrigger()).toHaveTextContent('Sink'));

    fireEvent.click(screen.getByRole('button', { name: /Save Changes/ }));

    expect(productTypeValues(await submittedBody(fetchMock, 'PUT'))).toEqual(['sink']);
  });
});
