import { describe, it, expect } from 'vitest';
import { relationshipTargetSource } from './relationship-target-source';

const ASSET_TYPES = ['Table', 'Logical Attribute', 'Logical Entity', 'Metric View'];

describe('relationshipTargetSource', () => {
  it.each(['DataDomain', 'DataProduct', 'DataContract', 'Team', 'Project', 'OntologyConcept'])(
    '%s comes from link candidates',
    (type) => {
      expect(relationshipTargetSource(type, ASSET_TYPES)).toEqual({ kind: 'candidates' });
    },
  );

  it('matches asset types by local name, not by the (translated) label', () => {
    expect(relationshipTargetSource('LogicalAttribute', ASSET_TYPES)).toEqual({
      kind: 'asset', assetTypeNames: ['Logical Attribute'],
    });
    expect(relationshipTargetSource('MetricView', ASSET_TYPES)).toEqual({
      kind: 'asset', assetTypeNames: ['Metric View'],
    });
  });

  it('accepts any asset type for the Asset superclass', () => {
    expect(relationshipTargetSource('Asset', ASSET_TYPES)).toEqual({ kind: 'asset', assetTypeNames: null });
  });

  it('reports targets that are managed elsewhere', () => {
    expect(relationshipTargetSource('Ownership', ASSET_TYPES)).toEqual({ kind: 'unsupported' });
  });
});
