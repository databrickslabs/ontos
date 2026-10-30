import { describe, it, expect } from 'vitest';
import type { LineageGraph, LineageGraphNode, LineageGraphEdge } from '@/types/ontology-schema';
import { layoutLineageGraph } from './layout';
import { computeHighlight, filterGraph, DEFAULT_VIEW_OPTIONS } from './highlight';

const node = (id: string, layer: string): LineageGraphNode => {
  const [entity_type, entity_id] = id.split(':');
  return { id, entity_type, entity_id, name: entity_id, layer, is_center: false };
};
const edge = (source: string, target: string, relationship_type: string, reversed = false): LineageGraphEdge =>
  ({ source, target, relationship_type, reversed });

// concept → product ⊃ port → contract ⊃ schema → table ⊃ column; sibling product shares the concept;
// provider product is depended on (dependsOn points consumer → provider)
const graph: LineageGraph = {
  center_entity_type: 'DataProduct',
  center_entity_id: 'p',
  nodes: [
    node('Concept:c', 'business'),
    node('DataProduct:p', 'delivery'),
    node('DataProduct:provider', 'delivery'),
    node('DataProduct:sibling', 'delivery'),
    node('OutputPort:port', 'delivery'),
    node('DataContract:k', 'logical'),
    node('SchemaObject:s', 'logical'),
    node('Table:t', 'physical'),
    node('Column:col', 'physical'),
  ],
  edges: [
    edge('Concept:c', 'DataProduct:p', 'describes'),
    edge('Concept:c', 'DataProduct:sibling', 'describes'),
    edge('DataProduct:p', 'DataProduct:provider', 'dependsOn', true),
    edge('DataProduct:p', 'OutputPort:port', 'hasOutputPort'),
    edge('OutputPort:port', 'DataContract:k', 'portHasContract'),
    edge('DataContract:k', 'SchemaObject:s', 'hasSchemaObject'),
    edge('SchemaObject:s', 'Table:t', 'implementedBy'),
    edge('Table:t', 'Column:col', 'hasColumn'),
  ],
};

describe('computeHighlight', () => {
  const layout = layoutLineageGraph(graph);
  const layers = new Map(graph.nodes.map((n) => [n.id, n.layer]));
  const hl = (id: string) => computeHighlight(id, layout.flowEdges, layout.parentOf, layout.childrenOf, (n) => layers.get(n));

  it('lights the full chain both ways but not siblings', () => {
    const h = hl('DataProduct:p');
    for (const id of ['Concept:c', 'DataProduct:provider', 'DataContract:k', 'SchemaObject:s', 'Table:t']) {
      expect(h.nodes.has(id), id).toBe(true);
    }
    expect(h.nodes.has('DataProduct:sibling')).toBe(false);
  });

  it('continues upstream from a row through its parent cards', () => {
    const h = hl('Column:col');
    for (const id of ['Table:t', 'SchemaObject:s', 'DataContract:k', 'OutputPort:port', 'DataProduct:p', 'Concept:c']) {
      expect(h.nodes.has(id), id).toBe(true);
    }
    expect(h.downstreamCount).toBe(0);
  });

  it('orients reversed edges so the provider sits upstream', () => {
    const dep = layout.flowEdges.find((e) => e.original.relationship_type === 'dependsOn')!;
    expect(dep.source).toBe('DataProduct:provider');
    expect(dep.target).toBe('DataProduct:p');
  });
});

describe('filterGraph', () => {
  it('hides a layer but never the center, and keeps nesting', () => {
    const g = filterGraph(graph, {
      ...DEFAULT_VIEW_OPTIONS,
      layers: { ...DEFAULT_VIEW_OPTIONS.layers, delivery: false },
    });
    const ids = new Set(g.nodes.map((n) => n.id));
    expect(ids.has('DataProduct:p')).toBe(true); // center
    expect(ids.has('OutputPort:port')).toBe(false);
    expect(g.edges.some((e) => e.relationship_type === 'hasColumn')).toBe(true);
  });

  it('hides an edge kind', () => {
    const g = filterGraph(graph, { ...DEFAULT_VIEW_OPTIONS, edges: { ...DEFAULT_VIEW_OPTIONS.edges, semantic: false } });
    expect(g.edges.some((e) => e.relationship_type === 'describes')).toBe(false);
  });
});
