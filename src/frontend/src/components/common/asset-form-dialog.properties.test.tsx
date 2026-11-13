/**
 * Editing a column in the asset dialog keeps its stored properties: the form
 * shows only the ontology fields (is nullable, is primary key, ...), and saving
 * used to replace `properties` with them, dropping `data_type` and the rest.
 *
 * The Radix Select hangs in jsdom and the domain selector fetches, so both are stubbed.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockPut = vi.fn();

vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: mockGet, post: mockPost, put: mockPut, delete: vi.fn(), loading: false }),
}));

vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key, i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}));

vi.mock('@/components/ui/domain-multi-selector', () => ({ default: () => null }));

vi.mock('@/components/ui/select', () => ({
  Select: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectValue: () => null,
  SelectContent: () => null,
  SelectItem: () => null,
}));

import { AssetFormDialog } from './asset-form-dialog';
import type { AssetRead } from '@/types/asset';

const field = (name: string, label: string, order: number) => ({
  iri: `http://ontos.app/ontology#${name}`, name, label, range_type: 'boolean',
  field_type: 'boolean', field_order: order, is_required: false, field_group: 'technical',
});

const COLUMN_SCHEMA = {
  type_iri: 'http://ontos.app/ontology#Column',
  type_label: 'Column',
  fields: [field('isNullable', 'is nullable', 11), field('isPrimaryKey', 'is primary key', 12)],
};

const column = {
  id: 'col-1',
  name: 'order_date',
  description: 'Order day',
  status: 'active',
  platform: 'Databricks',
  location: 'main.sales.orders.order_date',
  asset_type_id: 'type-column',
  properties: { data_type: 'DATE', nullable: true, comment: 'Order day' },
  domains: [],
} as unknown as AssetRead;

describe('AssetFormDialog edit', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGet.mockResolvedValue({ data: COLUMN_SCHEMA });
    mockPut.mockResolvedValue({ data: column });
  });

  it('keeps the stored properties the form does not show', async () => {
    render(
      <AssetFormDialog
        isOpen
        onOpenChange={vi.fn()}
        onSuccess={vi.fn()}
        assetTypeId="type-column"
        assetTypeName="Column"
        assetTypeIri="http://ontos.app/ontology#Column"
        asset={column}
      />,
    );

    const primaryKey = await screen.findByRole('checkbox', { name: /primary key/i });
    await userEvent.click(primaryKey);
    await userEvent.click(screen.getByRole('button', { name: 'common:actions.saveChanges' }));

    await waitFor(() => expect(mockPut).toHaveBeenCalledTimes(1));
    const [url, payload] = mockPut.mock.calls[0];
    expect(url).toBe('/api/assets/col-1');
    expect(payload.properties).toEqual({
      data_type: 'DATE', nullable: true, comment: 'Order day', isPrimaryKey: true,
    });
  });
});
