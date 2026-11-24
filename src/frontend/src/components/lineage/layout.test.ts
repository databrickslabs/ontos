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

describe('layoutLineageGraph (detail level vs. selected rows)', () => {
  // A contract property feeding a table column: a field-level edge
  const fieldGraph: LineageGraph = {
    center_entity_type: 'DataContract',
    center_entity_id: 'k',
    nodes: [
      node('DataContract:k', 'logical'),
      node('SchemaObject:s', 'logical'),
      node('SchemaProperty:f', 'logical'),
      node('Dataset:d', 'physical'),
      node('Table:t', 'physical'),
      node('Column:col', 'physical'),
    ],
    edges: [
      edge('DataContract:k', 'SchemaObject:s', 'hasSchemaObject'),
      edge('SchemaObject:s', 'SchemaProperty:f', 'hasProperty'),
      edge('Dataset:d', 'Table:t', 'hasTable'),
      edge('Table:t', 'Column:col', 'hasColumn'),
      edge('SchemaProperty:f', 'Column:col', 'implementedBy'),
    ],
  };
  const pathRows = new Set(['SchemaProperty:f', 'Column:col', 'SchemaObject:s', 'Table:t']);
  const childIds = (l: ReturnType<typeof layoutLineageGraph>, id: string) =>
    l.groups.find((g) => g.id === id)!.children.map((c) => c.id);

  it('shows cards only at Entities detail, even for selected rows', () => {
    const l = layoutLineageGraph(fieldGraph, { ...defaultsWith('entities'), alwaysShow: pathRows });
    expect(childIds(l, 'DataContract:k')).toEqual([]);
    expect(childIds(l, 'Dataset:d')).toEqual([]);
    // Edges between hidden rows land on the cards
    expect(l.edges.length).toBeGreaterThan(0);
    for (const e of l.edges) {
      expect(e.sourceHandle).toBeUndefined();
      expect(e.targetHandle).toBeUndefined();
    }
  });

  it('keeps a selected field row at Structure detail, but no other fields', () => {
    const l = layoutLineageGraph(fieldGraph, { ...defaultsWith('structure'), alwaysShow: new Set(['Column:col']) });
    expect(childIds(l, 'Dataset:d')).toEqual(['Table:t', 'Column:col']);
    expect(childIds(l, 'DataContract:k')).toEqual(['SchemaObject:s']);
  });
});

describe('layoutLineageGraph (System nodes)', () => {
  // Upstream path of a table: table <- table <- system (stored asset -> system, against the flow)
  const sysGraph = (layered: boolean): LineageGraph => {
    const n = (id: string) => {
      const base = node(id, 'physical');
      return layered ? base : { ...base, layer: undefined };
    };
    return {
      center_entity_type: 'Table',
      center_entity_id: 't',
      nodes: [n('Table:t'), n('Table:u'), n('System:erp'), n('System:historian')],
      edges: [
        edge('Table:t', 'Table:u', 'derivedFrom', true),
        edge('Table:u', 'System:erp', 'belongsToSystem', true),
        edge('Table:u', 'System:historian', 'someSourceRel', true),
      ],
    };
  };

  for (const layered of [true, false]) {
    it(`draws System nodes as upstream sources (${layered ? 'layer' : 'column'} mode)`, () => {
      const l = layoutLineageGraph(sysGraph(layered));
      const x = (id: string) => l.groups.find((g) => g.id === id)?.x;
      expect(l.groups.map((g) => g.id).sort()).toEqual(
        ['System:erp', 'System:historian', 'Table:t', 'Table:u'],
      );
      expect(x('System:erp')!).toBeLessThan(x('Table:u')!);
      expect(x('Table:u')!).toBeLessThan(x('Table:t')!);
      const pairs = l.edges.map((e) => `${e.edge.source}>${e.edge.target}`).sort();
      expect(pairs).toEqual([
        'Table:t>Table:u',
        'Table:u>System:erp',
        'Table:u>System:historian',
      ]);
      expect(l.groups.find((g) => g.id === 'Table:u')!.system).toBeUndefined();
    });
  }

  for (const infraFirst of [true, false]) {
    it(`keeps the real flow edge over a System edge (${infraFirst ? 'infra' : 'flow'} first)`, () => {
      const infra = edge('Table:u', 'System:s', 'belongsToSystem', true);
      const feeds = edge('Table:u', 'System:s', 'feeds', true);
      const l = layoutLineageGraph({
        center_entity_type: 'Table',
        center_entity_id: 'u',
        nodes: [node('Table:u', 'physical'), node('System:s', 'physical')],
        edges: infraFirst ? [infra, feeds] : [feeds, infra],
      });
      expect(l.edges).toHaveLength(1);
      expect(l.edges[0].edge.relationship_type).toBe('feeds');
      expect(l.edges[0].memberKeys).toHaveLength(2);
    });
  }

  it('draws a non-reversed System edge with the System as a sink', () => {
    const l = layoutLineageGraph({
      center_entity_type: 'Table',
      center_entity_id: 'u',
      nodes: [node('Table:u', 'physical'), node('System:s', 'physical')],
      edges: [edge('Table:u', 'System:s', 'deployedOnSystem')],
    });
    const x = (id: string) => l.groups.find((g) => g.id === id)!.x;
    expect(x('System:s')).toBeGreaterThan(x('Table:u'));
  });

  it('still nests assets inside a System that is the center', () => {
    const l = layoutLineageGraph({
      center_entity_type: 'System',
      center_entity_id: 'erp',
      nodes: [node('System:erp', 'physical'), node('Table:a', 'physical')],
      edges: [edge('Table:a', 'System:erp', 'belongsToSystem', true)],
    });
    expect(l.groups.map((g) => g.id)).toEqual(['System:erp']);
    expect(l.parentOf.get('Table:a')).toBe('System:erp');
  });
});

function defaultsWith(detail: LineageDetail) {
  return { ...DEFAULT_CONFIG, detail };
}
