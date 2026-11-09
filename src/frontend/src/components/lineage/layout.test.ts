import { describe, it, expect } from 'vitest';
import type { LineageGraph, LineageGraphNode, LineageGraphEdge } from '@/types/ontology-schema';
import { layoutLineageGraph, DEFAULT_CONFIG } from './layout';
import type { LineageDetail } from './layout';

const node = (id: string, layer: string): LineageGraphNode => {
  const [entity_type, entity_id] = id.split(':');
  return { id, entity_type, entity_id, name: entity_id, layer, is_center: false };
};
const edge = (source: string, target: string, relationship_type: string, reversed = false): LineageGraphEdge =>
  ({ source, target, relationship_type, reversed });

const graph: LineageGraph = {
  center_entity_type: 'DataProduct',
  center_entity_id: 'p',
  nodes: [
    node('Concept:c', 'business'),
    node('DataProduct:p', 'delivery'),
    node('DataProduct:provider', 'delivery'),
    node('DataContract:k', 'logical'),
    node('SchemaObject:s', 'logical'),
    node('Dataset:d', 'physical'),
    node('Table:t', 'physical'),
  ],
  edges: [
    edge('Concept:c', 'DataProduct:p', 'describes'),
    edge('DataProduct:p', 'DataProduct:provider', 'dependsOn', true),
    edge('DataProduct:p', 'Dataset:d', 'hasDataset'),
    edge('Dataset:d', 'Table:t', 'hasTable'),
    edge('DataContract:k', 'SchemaObject:s', 'hasSchemaObject'),
    edge('Dataset:d', 'DataContract:k', 'governedBy', true),
  ],
};

describe('layoutLineageGraph (layer mode)', () => {
  const layout = layoutLineageGraph(graph);
  const x = (id: string) => layout.groups.find((g) => g.id === id)!.x;

  it('draws cross-layer containment as an edge but nests same-layer containment', () => {
    expect(layout.flowEdges.some((e) => e.original.relationship_type === 'hasDataset')).toBe(true);
    expect(layout.parentOf.has('Dataset:d')).toBe(false);
    expect(layout.parentOf.get('Table:t')).toBe('Dataset:d');
    expect(layout.parentOf.get('SchemaObject:s')).toBe('DataContract:k');
  });

  it('orders lanes business → delivery → logical → physical', () => {
    expect(layout.lanes.map((l) => l.layer)).toEqual(['business', 'delivery', 'logical', 'physical']);
    expect(x('Concept:c')).toBeLessThan(x('DataProduct:p'));
    expect(x('DataProduct:p')).toBeLessThan(x('DataContract:k'));
    expect(x('DataContract:k')).toBeLessThan(x('Dataset:d'));
  });

  it('puts a provider left of the product depending on it (same lane)', () => {
    expect(x('DataProduct:provider')).toBeLessThan(x('DataProduct:p'));
  });

  it('nests rows by detail level', () => {
    const entities = layoutLineageGraph(graph, defaultsWith('entities'));
    expect(entities.groups.find((g) => g.id === 'Dataset:d')!.children).toHaveLength(0);
    const structure = layoutLineageGraph(graph, defaultsWith('structure'));
    expect(structure.groups.find((g) => g.id === 'Dataset:d')!.children.map((c) => c.id)).toEqual(['Table:t']);
  });
});

function defaultsWith(detail: LineageDetail) {
  return { ...DEFAULT_CONFIG, detail };
}
