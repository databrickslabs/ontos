/**
 * Tests for DataProductCreateDialog — focused on the Consumer Groups picker
 * being mounted in the *active* edit/create dialog. Earlier work mounted the
 * picker only in `data-product-form-dialog.tsx`, which is dead code (not
 * imported anywhere). This dialog is the one actually opened from the UI, so
 * the picker has to live here for users to populate `consumer_principals`.
 */
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import DataProductCreateDialog from './data-product-create-dialog';
import type { DataProduct } from '@/types/data-product';

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

// fetch is hit by both ConsumerGroupsPicker (GET /api/workspace/groups) and
// the dialog's submit handler (POST/PUT /api/data-products). Tests inspect
// the recorded calls per assertion.
const setupFetchMock = () => {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();
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
