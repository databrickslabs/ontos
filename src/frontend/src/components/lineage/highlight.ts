/**
 * Path highlighting and view filters for the lineage view.
 *
 * Highlight: selecting a node lights the node, its full upstream chain and its
 * full downstream chain (to either end), and dims everything else. Siblings
 * that merely share an upstream node are not part of the path.
 *
 * Nesting matters for continuation: going downstream from a card continues
 * from its child rows (a contract's schema objects bind to tables); going
 * upstream from a row continues from its parent cards (a property is defined
 * by its contract, which a port and product deliver).
 *
 * Skipped layers are filled like in the backend walk: if the path jumps from
 * Delivery to Physical (Product → Dataset), the Dataset's governing contract
 * (Logical, i.e. upstream of the Dataset) is lit as a leaf.
 */

import type { LineageGraph } from '@/types/ontology-schema';
import type { OrientedEdge } from './layout';
import { isContainment, isInfrastructure } from './layout';
import { categorizeEdge, MODEL_LAYERS } from './constants';
import type { ModelLayer } from './constants';

// ─── Highlight ───────────────────────────────────────────────────────────

export interface Highlight {
  nodes: Set<string>;
  edges: Set<string>;
  upstreamCount: number;
  downstreamCount: number;
}

export function computeHighlight(
  selectedId: string,
  flowEdges: OrientedEdge[],
  parentOf: Map<string, string>,
  childrenOf: Map<string, string[]>,
  layerOf: (id: string) => string | null | undefined = () => null,
): Highlight {
  const rank = (id: string) => {
    const i = (MODEL_LAYERS as readonly string[]).indexOf(layerOf(id) || '');
    return i >= 0 && i < 4 ? i : null; // 'other' has no rank
  };
  const selectedRank = rank(selectedId);
  const fillsGap = (from: string, to: string) => {
    const a = selectedRank, b = rank(from), c = rank(to);
    return a !== null && b !== null && c !== null && Math.min(a, b) < c && c < Math.max(a, b);
  };
  const up = new Map<string, OrientedEdge[]>();   // node → edges arriving at it
  const down = new Map<string, OrientedEdge[]>(); // node → edges leaving it
  for (const e of flowEdges) {
    if (!up.has(e.target)) up.set(e.target, []);
    up.get(e.target)!.push(e);
    if (!down.has(e.source)) down.set(e.source, []);
    down.get(e.source)!.push(e);
  }

  const ancestors = (id: string): string[] => {
    const out: string[] = [];
    const seen = new Set<string>([id]);
    let cur = parentOf.get(id);
    while (cur && !seen.has(cur)) {
      out.push(cur);
      seen.add(cur);
      cur = parentOf.get(cur);
    }
    return out;
  };
  const descendants = (id: string): string[] => {
    const out: string[] = [];
    const stack = [...(childrenOf.get(id) || [])];
    const seen = new Set<string>([id]);
    while (stack.length) {
      const c = stack.pop()!;
      if (seen.has(c)) continue;
      seen.add(c);
      out.push(c);
      stack.push(...(childrenOf.get(c) || []));
    }
    return out;
  };

  const nodes = new Set<string>([selectedId, ...descendants(selectedId)]);
  const edges = new Set<string>();

  const walk = (
    adjacency: Map<string, OrientedEdge[]>,
    next: (e: OrientedEdge) => string,
    expand: (id: string) => string[],
    opposite: Map<string, OrientedEdge[]>,
    back: (e: OrientedEdge) => string,
  ): Set<string> => {
    const reached = new Set<string>();
    const queue = [selectedId, ...expand(selectedId)];
    const visited = new Set<string>(queue);
    while (queue.length) {
      const id = queue.shift()!;
      for (const e of opposite.get(id) || []) {
        const n = back(e);
        if (fillsGap(id, n)) {
          edges.add(e.key);
          nodes.add(n); // leaf — not walked further
        }
      }
      for (const e of adjacency.get(id) || []) {
        edges.add(e.key);
        const n = next(e);
        reached.add(n);
        for (const m of [n, ...expand(n)]) {
          if (!visited.has(m)) {
            visited.add(m);
            queue.push(m);
          }
        }
      }
    }
    return reached;
  };

  const upstream = walk(up, (e) => e.source, ancestors, down, (e) => e.target);
  const downstream = walk(down, (e) => e.target, descendants, up, (e) => e.source);

  for (const id of [...upstream, ...downstream]) nodes.add(id);
  // Light the cards that contain lit rows
  for (const id of [...nodes]) for (const a of ancestors(id)) nodes.add(a);
  for (const a of ancestors(selectedId)) nodes.add(a);

  upstream.delete(selectedId);
  downstream.delete(selectedId);
  return { nodes, edges, upstreamCount: upstream.size, downstreamCount: downstream.size };
}

// ─── View filters ────────────────────────────────────────────────────────

/** Edge kinds the user can toggle. Same-layer containment (nesting) is never filtered. */
export const EDGE_FILTERS = ['flow', 'implementation', 'crossContainment', 'governance', 'semantic'] as const;
export type EdgeFilter = typeof EDGE_FILTERS[number];

export interface ViewOptions {
  layers: Record<ModelLayer, boolean>;
  edges: Record<EdgeFilter, boolean>;
  showLabels: boolean;
  showMinimap: boolean;
}

export const DEFAULT_VIEW_OPTIONS: ViewOptions = {
  layers: { business: true, delivery: true, logical: true, physical: true, other: false },
  edges: { flow: true, implementation: true, crossContainment: true, governance: true, semantic: true },
  showLabels: false,
  showMinimap: false,
};

/**
 * Focus: keep only the highlighted path (plus nesting/badge edges among kept
 * nodes) so the layout closes the gaps left by everything else.
 */
export function focusGraph(graph: LineageGraph, highlight: Highlight): LineageGraph {
  const nodes = graph.nodes.filter((n) => highlight.nodes.has(n.id));
  const kept = new Set(nodes.map((n) => n.id));
  const edges = graph.edges.filter((e) => {
    if (!kept.has(e.source) || !kept.has(e.target)) return false;
    if (isInfrastructure(e.relationship_type) || isContainment(e.relationship_type)) return true;
    return highlight.edges.has(`${e.source}|${e.target}|${e.relationship_type}`);
  });
  return { ...graph, nodes, edges };
}

/**
 * Drop hidden layers (never the center) and hidden edge kinds. Layout prunes
 * roots left without edges afterwards, so the view stays connected.
 */
export function filterGraph(graph: LineageGraph, opts: ViewOptions): LineageGraph {
  const centerId = `${graph.center_entity_type}:${graph.center_entity_id}`;
  const layerOf = new Map(graph.nodes.map((n) => [n.id, n.layer || 'physical']));
  const keepNode = (id: string) =>
    id === centerId || opts.layers[(layerOf.get(id) as ModelLayer)] !== false
    || !(MODEL_LAYERS as readonly string[]).includes(layerOf.get(id) || '');

  const nodes = graph.nodes.filter((n) => keepNode(n.id));
  const kept = new Set(nodes.map((n) => n.id));
  const edges = graph.edges.filter((e) => {
    if (!kept.has(e.source) || !kept.has(e.target)) return false;
    if (isInfrastructure(e.relationship_type)) return true; // rendered as badges
    if (isContainment(e.relationship_type)) {
      if (layerOf.get(e.source) === layerOf.get(e.target)) return true; // nesting
      return opts.edges.crossContainment;
    }
    const cat = categorizeEdge(e.relationship_type);
    return cat === 'hierarchy' ? opts.edges.crossContainment : opts.edges[cat];
  });
  return { ...graph, nodes, edges };
}
