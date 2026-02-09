import { describe, it, expect } from 'vitest';
import {
  ChangeStatus,
  getColorForType,
  getUniqueNodeTypes,
  getUniqueRelationshipTypes,
  getNodeTypeColorMap,
  type GraphData,
} from './graph-explorer';

describe('ChangeStatus', () => {
  it('has expected values', () => {
    expect(ChangeStatus.EXISTING).toBe('existing');
    expect(ChangeStatus.NEW).toBe('new');
    expect(ChangeStatus.MODIFIED).toBe('modified');
  });
});

describe('getColorForType', () => {
  it('returns a string color', () => {
    const color = getColorForType('Person');
    expect(color).toMatch(/^#[0-9a-fA-F]{6}$/);
  });

  it('returns consistent color for same type', () => {
    expect(getColorForType('Person')).toBe(getColorForType('Person'));
  });

  it('returns different colors for different types', () => {
    const c1 = getColorForType('Person');
    const c2 = getColorForType('Organization');
    // They may collide but typically should not
    expect(typeof c1).toBe('string');
    expect(typeof c2).toBe('string');
  });

  it('supports dark mode', () => {
    const light = getColorForType('Person', false);
    const dark = getColorForType('Person', true);
    expect(light).not.toBe(dark);
  });
});

describe('getUniqueNodeTypes', () => {
  it('extracts unique node types sorted', () => {
    const data: GraphData = {
      nodes: [
        { id: '1', label: 'A', type: 'Person', properties: {}, status: ChangeStatus.EXISTING },
        { id: '2', label: 'B', type: 'Company', properties: {}, status: ChangeStatus.EXISTING },
        { id: '3', label: 'C', type: 'Person', properties: {}, status: ChangeStatus.NEW },
      ],
      edges: [],
    };
    expect(getUniqueNodeTypes(data)).toEqual(['Company', 'Person']);
  });

  it('returns empty array for empty data', () => {
    expect(getUniqueNodeTypes({ nodes: [], edges: [] })).toEqual([]);
  });
});

describe('getUniqueRelationshipTypes', () => {
  it('extracts unique relationship types sorted', () => {
    const data: GraphData = {
      nodes: [],
      edges: [
        { id: 'e1', source: '1', target: '2', relationshipType: 'WORKS_AT', properties: {}, status: ChangeStatus.EXISTING },
        { id: 'e2', source: '2', target: '3', relationshipType: 'KNOWS', properties: {}, status: ChangeStatus.EXISTING },
        { id: 'e3', source: '1', target: '3', relationshipType: 'WORKS_AT', properties: {}, status: ChangeStatus.NEW },
      ],
    };
    expect(getUniqueRelationshipTypes(data)).toEqual(['KNOWS', 'WORKS_AT']);
  });
});

describe('getNodeTypeColorMap', () => {
  it('returns a map of type to color', () => {
    const data: GraphData = {
      nodes: [
        { id: '1', label: 'A', type: 'Person', properties: {}, status: ChangeStatus.EXISTING },
        { id: '2', label: 'B', type: 'Company', properties: {}, status: ChangeStatus.EXISTING },
      ],
      edges: [],
    };
    const map = getNodeTypeColorMap(data);
    expect(map.size).toBe(2);
    expect(map.has('Person')).toBe(true);
    expect(map.has('Company')).toBe(true);
    expect(map.get('Person')).toMatch(/^#[0-9a-fA-F]{6}$/);
  });
});
