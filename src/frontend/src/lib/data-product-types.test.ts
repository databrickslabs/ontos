import { describe, it, expect } from 'vitest';
import i18n from '@/i18n/config';
import type { DataProductType } from '@/types/data-product-type';
import {
  dataProductTypeLabel,
  defaultDataProductTypeKey,
  pickableDataProductTypes,
} from './data-product-types';

const type = (key: string, overrides: Partial<DataProductType> = {}): DataProductType => ({
  id: key,
  key,
  label: key,
  sort_order: 1,
  is_active: true,
  is_default: false,
  is_imported: false,
  is_seeded: false,
  has_seeded_label: false,
  usage_count: 0,
  ...overrides,
});

describe('dataProductTypeLabel', () => {
  it('translates a built-in type while its label is unchanged', async () => {
    await i18n.changeLanguage('de');
    try {
      const label = dataProductTypeLabel(
        type('source-aligned', { label: 'Source-Aligned', is_seeded: true, has_seeded_label: true }),
        i18n.t,
      );
      expect(label).toBe(i18n.t('data-products:dataProductType.source-aligned'));
      expect(label).not.toBe('Source-Aligned');
    } finally {
      await i18n.changeLanguage('en');
    }
  });

  it('shows the label as entered once an admin renamed it', () => {
    const renamed = type('aggregate', { label: 'Composite', is_seeded: true, has_seeded_label: false });
    expect(dataProductTypeLabel(renamed, i18n.t)).toBe('Composite');
  });

  it('shows the label of a custom type as entered', () => {
    expect(dataProductTypeLabel(type('golden-record', { label: 'Golden Record' }), i18n.t)).toBe(
      'Golden Record',
    );
  });
});

describe('pickableDataProductTypes', () => {
  const types = [type('source'), type('sink', { is_active: false })];

  it('offers only active types', () => {
    expect(pickableDataProductTypes(types).map((t) => t.key)).toEqual(['source']);
  });

  it("keeps the product's current type when it's inactive", () => {
    expect(pickableDataProductTypes(types, 'sink').map((t) => t.key)).toEqual(['source', 'sink']);
  });
});

describe('defaultDataProductTypeKey', () => {
  it('is the active default type', () => {
    expect(defaultDataProductTypeKey([type('source'), type('aggregate', { is_default: true })])).toBe(
      'aggregate',
    );
  });

  it('is undefined when the default is inactive or none is set', () => {
    expect(defaultDataProductTypeKey([type('a', { is_default: true, is_active: false })])).toBeUndefined();
    expect(defaultDataProductTypeKey([type('a')])).toBeUndefined();
  });
});
