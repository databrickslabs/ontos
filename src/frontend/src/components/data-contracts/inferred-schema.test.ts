import { describe, it, expect } from 'vitest';
import { inferredPropertyFields } from './inferred-schema';

const base = { name: 'Total Price', physicalType: 'REAL', logicalType: 'number', required: false, description: '', partitioned: false };

describe('inferredPropertyFields', () => {
  it('keeps semantic model fields, with the UC sources as comma-separated text', () => {
    expect(inferredPropertyFields({
      ...base,
      businessName: 'Total Price',
      transformLogic: 'SUM([Price])',
      transformSourceObjects: ['samples.tpch.orders.o_totalprice', 'samples.tpch.orders.o_orderkey'],
    })).toEqual({
      ...base,
      businessName: 'Total Price',
      transformLogic: 'SUM([Price])',
      transformSourceObjects: 'samples.tpch.orders.o_totalprice, samples.tpch.orders.o_orderkey',
    });
  });

  it('adds nothing for a plain table column', () => {
    expect(inferredPropertyFields({ ...base, logicalType: '' })).toEqual({ ...base, logicalType: 'string' });
  });
});
