/**
 * Settings → Reference Data → Data Product Types (#1209): list, labels,
 * the rules the API enforces (shown before the user tries) and its error codes.
 */
import { screen, fireEvent, waitFor, within } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import i18n from '@/i18n/config';
import { renderWithProviders } from '@/test/utils';
import DataProductTypesSettings from './data-product-types-settings';
import type { DataProductType } from '@/types/data-product-type';

const toast = vi.fn();
vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast }),
}));

let canWrite = true;
vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({ hasPermission: (_id: string, level: string) => level !== 'Read/Write' || canWrite }),
}));

const productType = (key: string, label: string, overrides: Partial<DataProductType> = {}): DataProductType => ({
  id: `id-${key}`,
  key,
  label,
  description: null,
  color: null,
  sort_order: 1,
  is_active: true,
  is_default: false,
  is_imported: false,
  is_seeded: false,
  has_seeded_label: false,
  usage_count: 0,
  ...overrides,
});

const TYPES: DataProductType[] = [
  productType('source-aligned', 'Source-Aligned', {
    sort_order: 1, is_default: true, is_seeded: true, has_seeded_label: true, usage_count: 0,
  }),
  productType('aggregate', 'Composite', { sort_order: 2, is_seeded: true, usage_count: 3 }),
  productType('golden-record', 'Golden Record', { sort_order: 3, is_imported: true, usage_count: 2 }),
  productType('scratch', 'Scratch', { sort_order: 4, is_active: false }),
];

type Reply = { status?: number; body: unknown };

const jsonResponse = ({ status = 200, body }: Reply) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const setupFetch = (writeReply: Reply = { body: {} }) => {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === '/api/data-product-types' && (!init?.method || init.method === 'GET')) {
      return Promise.resolve(jsonResponse({ body: TYPES }));
    }
    return Promise.resolve(jsonResponse(writeReply));
  });
  global.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
};

const writes = (fetchMock: ReturnType<typeof setupFetch>) =>
  fetchMock.mock.calls
    .filter(([, init]) => init?.method && init.method !== 'GET')
    .map(([url, init]) => ({ url: String(url), method: init!.method, body: init!.body ? JSON.parse(init!.body as string) : undefined }));

const row = (key: string) => screen.getByTestId(`data-product-type-${key}`);

const renderPage = async () => {
  renderWithProviders(<DataProductTypesSettings />);
  await screen.findByTestId('data-product-type-source-aligned');
};

describe('DataProductTypesSettings', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    canWrite = true;
  });

  it('lists the types with their badges, key and product count', async () => {
    setupFetch();
    await renderPage();

    const sourceAligned = within(row('source-aligned'));
    expect(sourceAligned.getByText('Source-Aligned')).toBeInTheDocument();
    expect(sourceAligned.getByText('Default')).toBeInTheDocument();
    expect(sourceAligned.getByText('Built-in')).toBeInTheDocument();

    expect(within(row('golden-record')).getByText('Imported')).toBeInTheDocument();
    expect(within(row('golden-record')).getByText('golden-record')).toBeInTheDocument();
    expect(within(row('aggregate')).getByText('3')).toBeInTheDocument();
  });

  it('loads the list once, and again after a change', async () => {
    const fetchMock = setupFetch();
    await renderPage();
    const listLoads = () =>
      fetchMock.mock.calls.filter(([url, init]) => String(url) === '/api/data-product-types' && !init?.method).length;

    // Give a render loop the chance to show up
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(listLoads()).toBe(1);

    fireEvent.click(within(row('golden-record')).getByRole('switch'));
    await waitFor(() => expect(listLoads()).toBe(2));
  });

  it('translates built-in labels until they are renamed', async () => {
    setupFetch();
    await i18n.changeLanguage('de');
    try {
      await renderPage();
      expect(within(row('source-aligned')).getByText('Quellorientiert')).toBeInTheDocument();
      // Renamed built-in type: shown as entered
      expect(within(row('aggregate')).getByText('Composite')).toBeInTheDocument();
    } finally {
      await i18n.changeLanguage('en');
    }
  });

  it('only allows deleting a custom type nobody uses, and says why otherwise', async () => {
    setupFetch();
    await renderPage();

    const deleteButton = (key: string) => within(row(key)).getByRole('button', { name: /^Delete / });
    expect(deleteButton('source-aligned')).toBeDisabled();
    expect(deleteButton('golden-record')).toBeDisabled();
    expect(deleteButton('scratch')).not.toBeDisabled();
    // An enabled delete has no reason around it
    expect(within(row('scratch')).queryByLabelText(/Deactivate it instead/)).not.toBeInTheDocument();
  });

  it('explains a blocked delete in a tooltip (a disabled button gets no hover)', async () => {
    setupFetch();
    await renderPage();

    fireEvent.focus(within(row('golden-record')).getByLabelText('Used by 2 data products. Deactivate it instead.'));
    expect(await screen.findByRole('tooltip')).toHaveTextContent('Used by 2 data products. Deactivate it instead.');
  });

  it('explains a built-in type that cannot be deleted', async () => {
    setupFetch();
    await renderPage();

    fireEvent.focus(within(row('source-aligned')).getByLabelText(/Built-in types can't be deleted/));
    expect(await screen.findByRole('tooltip')).toHaveTextContent(/Built-in types can't be deleted/);
  });

  it('deletes an unused custom type after confirming', async () => {
    const fetchMock = setupFetch({ status: 204, body: null });
    await renderPage();

    fireEvent.click(within(row('scratch')).getByRole('button', { name: /^Delete / }));
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }));

    await waitFor(() =>
      expect(writes(fetchMock)).toEqual([{ url: '/api/data-product-types/id-scratch', method: 'DELETE', body: undefined }]),
    );
  });

  it("doesn't let the default type be deactivated, but other types can be", async () => {
    const fetchMock = setupFetch();
    await renderPage();

    expect(within(row('source-aligned')).getByRole('switch')).toBeDisabled();
    fireEvent.focus(within(row('source-aligned')).getByLabelText(/default type can't be deactivated/));
    expect(await screen.findByRole('tooltip')).toHaveTextContent(/default type can't be deactivated/);

    fireEvent.click(within(row('golden-record')).getByRole('switch'));

    await waitFor(() =>
      expect(writes(fetchMock)).toEqual([
        { url: '/api/data-product-types/id-golden-record', method: 'PUT', body: { is_active: false } },
      ]),
    );
  });

  it('makes an active type the default; inactive types and the default itself cannot be', async () => {
    const fetchMock = setupFetch();
    await renderPage();

    const makeDefault = (key: string) => within(row(key)).getByRole('button', { name: /the default$/ });
    expect(makeDefault('source-aligned')).toBeDisabled();
    expect(makeDefault('scratch')).toBeDisabled();

    fireEvent.click(makeDefault('aggregate'));

    await waitFor(() =>
      expect(writes(fetchMock)).toEqual([
        { url: '/api/data-product-types/id-aggregate', method: 'PUT', body: { is_default: true } },
      ]),
    );
  });

  it('sends the new order when a type is moved down', async () => {
    const fetchMock = setupFetch({ body: TYPES });
    await renderPage();

    fireEvent.click(within(row('source-aligned')).getByRole('button', { name: /down$/ }));

    await waitFor(() =>
      expect(writes(fetchMock)).toEqual([
        {
          url: '/api/data-product-types/reorder',
          method: 'PUT',
          body: {
            types: [
              { id: 'id-aggregate', sort_order: 1 },
              { id: 'id-source-aligned', sort_order: 2 },
              { id: 'id-golden-record', sort_order: 3 },
              { id: 'id-scratch', sort_order: 4 },
            ],
          },
        },
      ]),
    );
  });

  it('creates a type, suggesting the key from the label', async () => {
    const fetchMock = setupFetch({ status: 201, body: {} });
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: /Add Type/ }));
    fireEvent.change(await screen.findByLabelText('Label'), { target: { value: 'Data Mart' } });
    expect(screen.getByLabelText('Key')).toHaveValue('data-mart');
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() =>
      expect(writes(fetchMock)).toEqual([
        {
          url: '/api/data-product-types',
          method: 'POST',
          body: { key: 'data-mart', label: 'Data Mart', description: null, color: 'slate' },
        },
      ]),
    );
  });

  it("can't save a key that isn't lower-case words joined by hyphens", async () => {
    setupFetch();
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: /Add Type/ }));
    fireEvent.change(await screen.findByLabelText('Label'), { target: { value: 'Data Mart' } });
    fireEvent.change(screen.getByLabelText('Key'), { target: { value: 'Data Mart' } });

    expect(screen.getByRole('button', { name: 'Create' })).toBeDisabled();
  });

  it('edits the label but never the key', async () => {
    const fetchMock = setupFetch();
    await renderPage();

    fireEvent.click(within(row('golden-record')).getByRole('button', { name: /^Edit / }));
    expect(await screen.findByLabelText('Key')).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Label'), { target: { value: 'Golden Records' } });
    fireEvent.click(screen.getByRole('button', { name: 'Update' }));

    await waitFor(() => {
      const [write] = writes(fetchMock);
      expect(write.url).toBe('/api/data-product-types/id-golden-record');
      expect(write.body).toEqual({ label: 'Golden Records', description: null, color: 'slate' });
    });
  });

  it("shows a refused change in the user's language from the error code", async () => {
    setupFetch({
      status: 409,
      body: { detail: { code: 'data_product_type_key_exists', message: 'exists', params: { key: 'data-mart' } } },
    });
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: /Add Type/ }));
    fireEvent.change(await screen.findByLabelText('Label'), { target: { value: 'Data Mart' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        expect.objectContaining({
          variant: 'destructive',
          description: 'A data product type with the key "data-mart" already exists.',
        }),
      ),
    );
  });

  it('hides the editing controls without write access', async () => {
    canWrite = false;
    setupFetch();
    await renderPage();

    expect(screen.queryByRole('button', { name: /Add Type/ })).not.toBeInTheDocument();
    expect(within(row('scratch')).queryByRole('button', { name: /^Delete / })).not.toBeInTheDocument();
    expect(within(row('scratch')).getByRole('switch')).toBeDisabled();
  });
});
