/**
 * Column layout algorithm with hierarchy collapsing and child-level edge routing.
 *
 * Containment relationships (hasTable, hasColumn, etc.) nest children inside
 * parent cards. Only root-level entities get positioned in columns.
 * Infrastructure edges (belongsToSystem) become metadata, not visual edges.
 *
 * Flow edges preserve child-level source/target handles so that edges can
 * connect to specific column rows within ERD-style cards.
 *
 * Layer mode: when every node carries a model `layer` (business → delivery →
 * logical → physical → other), columns are lanes per layer instead of BFS
 * hops from the center. Containment only nests within a layer — a cross-layer
 * containment edge (e.g. DataProduct hasDataset Dataset) is drawn as an edge
 * between lanes. Flow edges inside a lane spread it into sub-columns.
 */

import type { LineageGraph, LineageGraphNode, LineageGraphEdge } from '@/types/ontology-schema';
import { MODEL_LAYERS } from './constants';

// ─── Relationship classification ─────────────────────────────────────────

/** Containment rels — children get nested inside parent card */
const CONTAINMENT_RELS = new Set([
  'hasTable', 'has table',
  'hasView', 'has view',
  'hasColumn', 'has column',
  'containsDataset', 'contains dataset', 'contains',
  'hasLogicalAttribute', 'has logical attribute',
  'containsProduct', 'contains product',
  'hasTopic', 'has topic',
  'has dataset',   // "has dataset" is containment (DataProduct → Dataset)
  'hasDataset',
  'hasOutputPort', 'has output port',
  'hasSchemaObject', 'has schema',
  'hasProperty', 'has property',
]);

/** Infrastructure rels — rendered as badge, not as edge */
const INFRASTRUCTURE_RELS = new Set([
  'belongs to system', 'belongsToSystem',
  'deployed on system', 'deployedOnSystem',
  'hosted on', 'hostedOn',
  'runs on', 'runsOn',
]);

// ─── Types ───────────────────────────────────────────────────────────────

export interface LayoutConfig {
  columnSpacing: number;
  nodeWidth: number;
  headerHeight: number;     // ERD header bar (name + type)
  childRowHeight: number;   // each child/column row
  nodeGap: number;          // vertical gap between cards
  topPadding: number;       // space below column header
  maxChildrenShown: number; // collapse after N children
  /** Which child rows cards show — see LineageDetail */
  detail: LineageDetail;
  /** Rows always shown regardless of detail (e.g. the selected path) */
  alwaysShow?: Set<string> | null;
}

/**
 * Card row detail, by kind rather than containment depth (a table's columns
 * sit one level down, a contract's properties two — numeric depth made those
 * inconsistent):
 *   entities  — cards only
 *   structure — containers: schema objects, tables/views in datasets, ports
 *   fields    — plus properties and columns
 */
export type LineageDetail = 'entities' | 'structure' | 'fields';
export const LINEAGE_DETAILS: LineageDetail[] = ['entities', 'structure', 'fields'];

const FIELD_TYPES = new Set(['SchemaProperty', 'Column']);
const MAX_NESTING_LEVELS = 3;

export const DEFAULT_CONFIG: LayoutConfig = {
  columnSpacing: 420,
  nodeWidth: 340,
  headerHeight: 44,
  childRowHeight: 30,
  nodeGap: 24,
  topPadding: 56,
  maxChildrenShown: 6,
  detail: 'structure',
  alwaysShow: null,
};

export interface GroupNode {
  id: string;
  node: LineageGraphNode;
  children: LineageGraphNode[];
  /** Containment depth per child (0=direct, 1=grandchild, etc.) */
  childDepths: number[];
  /** System/infra this entity belongs to */
  system?: string;
  height: number;
  column: number;
}

export interface LayoutEdge {
  id: string;
  /** Original edge (stored direction, for label/style) */
  edge: LineageGraphEdge;
  /** Stored direction points against the flow — arrow belongs at the start */
  reversed: boolean;
  /** Keys (edgeKey) of all graph edges merged into this rendered edge */
  memberKeys: string[];
  /** Resolved to root-level ancestor IDs */
  sourceRootId: string;
  targetRootId: string;
  /** Handle ID on source node — child port or undefined for parent-level */
  sourceHandle?: string;
  /** Handle ID on target node — child port or undefined for parent-level */
  targetHandle?: string;
}

export interface ColumnHeader {
  column: number;
  label: string;
  /** Set in layer mode — the lane's model layer (for i18n) */
  layer?: string;
  x: number;
}

/** Layer-mode lane band (background + title) */
export interface LaneBand {
  layer: string;
  x: number;
  width: number;
  height: number;
}

export interface LayoutResult {
  groups: (GroupNode & { x: number; y: number })[];
  /** Layer mode only: one band per non-empty lane */
  lanes: LaneBand[];
  edges: LayoutEdge[];
  columns: ColumnHeader[];
  /** All containment edges (hidden from rendering) */
  hiddenEdgeCount: number;
  /** Nesting: child → parent (same-layer containment) */
  parentOf: Map<string, string>;
  childrenOf: Map<string, string[]>;
  /** Flow-oriented edges (upstream → downstream) used for path highlighting */
  flowEdges: OrientedEdge[];
}

/** Edge with source/target in flow direction; `original` keeps the stored edge */
export interface OrientedEdge {
  source: string;
  target: string;
  key: string;
  original: LineageGraphEdge;
}

export function edgeKey(e: LineageGraphEdge): string {
  return `${e.source}|${e.target}|${e.relationship_type}`;
}

function orient(e: LineageGraphEdge): OrientedEdge {
  return e.reversed
    ? { source: e.target, target: e.source, key: edgeKey(e), original: e }
    : { source: e.source, target: e.target, key: edgeKey(e), original: e };
}

// ─── Helpers ─────────────────────────────────────────────────────────────

export function isContainment(relType: string): boolean {
  return CONTAINMENT_RELS.has(relType);
}

export function isInfrastructure(relType: string): boolean {
  return INFRASTRUCTURE_RELS.has(relType);
}

// ─── Main algorithm ──────────────────────────────────────────────────────

export function layoutLineageGraph(
  graph: LineageGraph,
  config: LayoutConfig = DEFAULT_CONFIG,
): LayoutResult {
  if (graph.nodes.length === 0) {
    return {
      groups: [], lanes: [], edges: [], columns: [], hiddenEdgeCount: 0,
      parentOf: new Map(), childrenOf: new Map(), flowEdges: [],
    };
  }

  const centerId = `${graph.center_entity_type}:${graph.center_entity_id}`;
  const nodeMap = new Map<string, LineageGraphNode>();
  for (const n of graph.nodes) nodeMap.set(n.id, n);

  // ── Step 1: Classify edges ────────────────────────────────────────────
  // Infrastructure edges (belongsToSystem, deployedOnSystem) are treated as
  // containment when they touch the center entity — e.g., when viewing a System,
  // assets that "belong to" it become nested children. Otherwise they become
  // metadata badges.

  const centerNode = nodeMap.get(centerId);
  const centerIsSystem = centerNode?.entity_type === 'System';
  const layerMode = graph.nodes.every((n) => !!n.layer);
  const sameLayer = (a: string, b: string) =>
    !layerMode || nodeMap.get(a)?.layer === nodeMap.get(b)?.layer;

  const containmentEdges: LineageGraphEdge[] = [];
  const infraEdges: LineageGraphEdge[] = [];
  const flowEdges: OrientedEdge[] = [];

  for (const e of graph.edges) {
    if (isContainment(e.relationship_type)) {
      if (sameLayer(e.source, e.target)) containmentEdges.push(e);
      else flowEdges.push(orient(e));
    } else if (isInfrastructure(e.relationship_type)) {
      // When center is a System, infra edges touching it become containment
      // belongsToSystem: source=entity, target=System → parent=System, child=entity
      // deployedOnSystem: source=entity, target=System → parent=System, child=entity
      if (centerIsSystem && e.target === centerId) {
        // Reverse: System (target) is parent, entity (source) is child
        containmentEdges.push({
          ...e,
          source: e.target,  // System = parent
          target: e.source,  // entity = child
        });
      } else {
        infraEdges.push(e);
      }
    } else {
      flowEdges.push(orient(e));
    }
  }

  // ── Step 2: Build containment hierarchy ───────────────────────────────
  // Containment is: source (parent) → target (child)

  const parentOf = new Map<string, string>();   // child → parent
  const childrenOf = new Map<string, string[]>(); // parent → children[]

  for (const e of containmentEdges) {
    const parentId = e.source;
    const childId = e.target;

    // Don't let the center entity become a child
    if (childId === centerId) continue;

    // Only set parent if not already assigned (first-come-first-served)
    if (!parentOf.has(childId)) {
      parentOf.set(childId, parentId);
      if (!childrenOf.has(parentId)) childrenOf.set(parentId, []);
      childrenOf.get(parentId)!.push(childId);
    }
  }

  // ── Step 3: Build infrastructure metadata ─────────────────────────────

  const systemOf = new Map<string, string>(); // entity → system name
  for (const e of infraEdges) {
    const entityId = e.source;
    const systemNode = nodeMap.get(e.target);
    if (systemNode && !systemOf.has(entityId)) {
      systemOf.set(entityId, systemNode.name);
    }
  }

  // ── Step 4: Identify root nodes (not a containment child) ─────────────

  const rootIds = new Set<string>();
  for (const n of graph.nodes) {
    if (!parentOf.has(n.id)) {
      // Skip System nodes unless the center IS a System
      const isSystemNode = n.entity_type === 'System';
      if (isSystemNode && n.id !== centerId) continue;
      rootIds.add(n.id);
    }
  }

  // Ensure center is always a root
  rootIds.add(centerId);

  // ── Step 5: Resolve node-to-root mapping ──────────────────────────────

  function getRootAncestor(nodeId: string): string {
    let current = nodeId;
    const visited = new Set<string>();
    while (parentOf.has(current) && !visited.has(current)) {
      visited.add(current);
      current = parentOf.get(current)!;
    }
    return rootIds.has(current) ? current : nodeId;
  }

  // ── Step 6: Column assignment (BFS on flow edges between roots) ───────

  const columns = new Map<string, number>();
  columns.set(centerId, 0);

  // Build adjacency for flow edges (mapped to root ancestors)
  const outgoing = new Map<string, Set<string>>();
  const incoming = new Map<string, Set<string>>();

  for (const e of flowEdges) {
    const src = getRootAncestor(e.source);
    const tgt = getRootAncestor(e.target);
    if (src === tgt) continue;
    if (!rootIds.has(src) || !rootIds.has(tgt)) continue;

    if (!outgoing.has(src)) outgoing.set(src, new Set());
    outgoing.get(src)!.add(tgt);
    if (!incoming.has(tgt)) incoming.set(tgt, new Set());
    incoming.get(tgt)!.add(src);
  }

  const queue: string[] = [centerId];
  const visited = new Set<string>([centerId]);

  while (queue.length > 0) {
    const nodeId = queue.shift()!;
    const col = columns.get(nodeId)!;

    for (const neighbor of outgoing.get(nodeId) || []) {
      if (!visited.has(neighbor)) {
        visited.add(neighbor);
        columns.set(neighbor, col + 1);
        queue.push(neighbor);
      }
    }

    for (const neighbor of incoming.get(nodeId) || []) {
      if (!visited.has(neighbor)) {
        visited.add(neighbor);
        columns.set(neighbor, col - 1);
        queue.push(neighbor);
      }
    }
  }

  // Assign disconnected roots to column 0
  for (const rootId of rootIds) {
    if (!columns.has(rootId)) columns.set(rootId, 0);
  }

  // Layer mode: lanes replace hop distance. Column = lane * LANE_STRIDE + sub-column.
  const LANE_STRIDE = 100;
  if (layerMode) {
    const subCol = assignSubColumns(rootIds, outgoing, (id) => nodeMap.get(id)?.layer || 'other');
    for (const rootId of rootIds) {
      const layer = nodeMap.get(rootId)?.layer || 'other';
      const lane = Math.max(0, (MODEL_LAYERS as readonly string[]).indexOf(layer));
      columns.set(rootId, lane * LANE_STRIDE + (subCol.get(rootId) ?? 0));
    }
  }

  // ── Step 6b: Prune orphan roots (no flow edges to other roots) ────────
  // Nodes reachable only via infrastructure edges (through System) are noise.
  // Keep a root only if it's the center, has children, or has ≥1 flow edge.

  const connectedRoots = new Set<string>();
  connectedRoots.add(centerId);
  for (const e of flowEdges) {
    const src = getRootAncestor(e.source);
    const tgt = getRootAncestor(e.target);
    if (src !== tgt && rootIds.has(src) && rootIds.has(tgt)) {
      connectedRoots.add(src);
      connectedRoots.add(tgt);
    }
  }
  // Also keep roots that have containment children (they carry info)
  for (const rootId of rootIds) {
    if (childrenOf.has(rootId) && childrenOf.get(rootId)!.length > 0) {
      connectedRoots.add(rootId);
    }
  }
  // Remove orphans
  for (const rootId of rootIds) {
    if (!connectedRoots.has(rootId)) {
      rootIds.delete(rootId);
    }
  }

  // ── Step 7: Build group nodes ─────────────────────────────────────────

  // Collect children recursively (up to MAX_NESTING_LEVELS)
  function collectNestedChildren(
    parentId: string,
    maxLevels: number, // how many containment levels to include (0 = none)
  ): { nodes: LineageGraphNode[]; depths: number[] } {
    if (maxLevels <= 0) return { nodes: [], depths: [] };
    const result: LineageGraphNode[] = [];
    const depths: number[] = [];

    const directIds = childrenOf.get(parentId) || [];
    for (const cid of directIds) {
      const cnode = nodeMap.get(cid);
      if (!cnode) continue;
      result.push(cnode);
      depths.push(0);

      // Recurse for grandchildren (depth 1+)
      if (maxLevels > 1) {
        const nested = collectNestedChildren(cid, maxLevels - 1);
        for (let i = 0; i < nested.nodes.length; i++) {
          result.push(nested.nodes[i]);
          depths.push(nested.depths[i] + 1);
        }
      }
    }
    return { nodes: result, depths };
  }

  const groups: GroupNode[] = [];
  for (const rootId of rootIds) {
    const node = nodeMap.get(rootId);
    if (!node) continue;

    const all = collectNestedChildren(rootId, MAX_NESTING_LEVELS);
    const children: LineageGraphNode[] = [];
    const childDepths: number[] = [];
    all.nodes.forEach((c, i) => {
      const show = config.alwaysShow?.has(c.id)
        || config.detail === 'fields'
        || (config.detail === 'structure' && !FIELD_TYPES.has(c.entity_type));
      if (show) {
        children.push(c);
        childDepths.push(all.depths[i]);
      }
    });

    const visibleChildren = Math.min(children.length, config.maxChildrenShown);
    const hasOverflow = children.length > config.maxChildrenShown;
    const childHeight = visibleChildren * config.childRowHeight;
    const overflowRow = hasOverflow ? config.childRowHeight : 0;
    const divider = children.length > 0 ? 1 : 0; // 1px border line

    const height = config.headerHeight + divider + childHeight + overflowRow;

    groups.push({
      id: rootId,
      node,
      children,
      childDepths,
      system: systemOf.get(rootId),
      height,
      column: columns.get(rootId) ?? 0,
    });
  }

  // ── Step 8: Minimize crossings (barycenter) ───────────────────────────

  const columnGroups = new Map<number, GroupNode[]>();
  for (const g of groups) {
    if (!columnGroups.has(g.column)) columnGroups.set(g.column, []);
    columnGroups.get(g.column)!.push(g);
  }

  const cols = Array.from(columnGroups.keys()).sort((a, b) => a - b);
  const yIndex = new Map<string, number>();
  for (const col of cols) {
    columnGroups.get(col)!.forEach((g, i) => yIndex.set(g.id, i));
  }

  const neighbors = new Map<string, string[]>();
  for (const e of flowEdges) {
    const src = getRootAncestor(e.source);
    const tgt = getRootAncestor(e.target);
    if (src === tgt || !rootIds.has(src) || !rootIds.has(tgt)) continue;
    if (!neighbors.has(src)) neighbors.set(src, []);
    neighbors.get(src)!.push(tgt);
    if (!neighbors.has(tgt)) neighbors.set(tgt, []);
    neighbors.get(tgt)!.push(src);
  }

  for (let pass = 0; pass < 3; pass++) {
    for (let i = 1; i < cols.length; i++) {
      barycenterSort(columnGroups.get(cols[i])!, neighbors, yIndex);
      columnGroups.get(cols[i])!.forEach((g, idx) => yIndex.set(g.id, idx));
    }
    for (let i = cols.length - 2; i >= 0; i--) {
      barycenterSort(columnGroups.get(cols[i])!, neighbors, yIndex);
      columnGroups.get(cols[i])!.forEach((g, idx) => yIndex.set(g.id, idx));
    }
  }

  // ── Step 9: Compute positions ─────────────────────────────────────────

  let maxColHeight = 0;
  for (const col of cols) {
    const gs = columnGroups.get(col)!;
    let h = 0;
    for (const g of gs) h += g.height + config.nodeGap;
    if (gs.length > 0) h -= config.nodeGap;
    if (h > maxColHeight) maxColHeight = h;
  }

  const positioned: (GroupNode & { x: number; y: number })[] = [];
  const columnHeaders: ColumnHeader[] = [];
  const laneX = new Map<string, { min: number; max: number }>();

  for (let ci = 0; ci < cols.length; ci++) {
    const col = cols[ci];
    const x = ci * config.columnSpacing;
    const gs = columnGroups.get(col)!;

    let totalH = 0;
    for (const g of gs) totalH += g.height + config.nodeGap;
    if (gs.length > 0) totalH -= config.nodeGap;

    const yStart = config.topPadding + (maxColHeight - totalH) / 2;

    if (layerMode) {
      const layer = MODEL_LAYERS[Math.floor(col / LANE_STRIDE)] ?? 'other';
      const ext = laneX.get(layer);
      laneX.set(layer, { min: Math.min(ext?.min ?? x, x), max: Math.max(ext?.max ?? x, x) });
    } else {
      let label: string;
      if (col === 0) label = 'Origin';
      else if (col < 0) label = `Upstream ‹${Math.abs(col)}`;
      else label = `Downstream ›${col}`;
      columnHeaders.push({ column: col, label, x });
    }

    let y = yStart;
    for (const g of gs) {
      positioned.push({ ...g, x, y });
      y += g.height + config.nodeGap;
    }
  }

  // ── Step 10: Build visible edges with child-level handle routing ──────

  // Build a lookup: for each group, index children by their node ID
  const groupChildIndex = new Map<string, Map<string, number>>();
  for (const g of groups) {
    const childMap = new Map<string, number>();
    // Only index up to maxChildrenShown (visible children get handles)
    const visCount = Math.min(g.children.length, config.maxChildrenShown);
    for (let i = 0; i < visCount; i++) {
      childMap.set(g.children[i].id, i);
    }
    groupChildIndex.set(g.id, childMap);
  }

  const renderedByKey = new Map<string, LayoutEdge>();
  const layoutEdges: LayoutEdge[] = [];

  for (let i = 0; i < flowEdges.length; i++) {
    const e = flowEdges[i];
    const srcRoot = getRootAncestor(e.source);
    const tgtRoot = getRootAncestor(e.target);
    if (srcRoot === tgtRoot) continue;
    if (!rootIds.has(srcRoot) || !rootIds.has(tgtRoot)) continue;

    // Resolve child handles: if source/target is a visible child, route to its port
    let sourceHandle: string | undefined;
    let targetHandle: string | undefined;

    if (e.source !== srcRoot) {
      const childMap = groupChildIndex.get(srcRoot);
      if (childMap?.has(e.source)) {
        sourceHandle = `child-${childMap.get(e.source)}`;
      }
    }

    if (e.target !== tgtRoot) {
      const childMap = groupChildIndex.get(tgtRoot);
      if (childMap?.has(e.target)) {
        targetHandle = `child-${childMap.get(e.target)}`;
      }
    }

    // Merge by rendered endpoints — edges to hidden (collapsed) children all
    // land on the parent handle and would otherwise stack up
    const key = `${srcRoot}/${sourceHandle ?? 'parent'}→${tgtRoot}/${targetHandle ?? 'parent'}`;
    const existing = renderedByKey.get(key);
    if (existing) {
      existing.memberKeys.push(e.key);
      continue;
    }

    const le: LayoutEdge = {
      id: `edge-${i}`,
      edge: e.original,
      reversed: !!e.original.reversed,
      memberKeys: [e.key],
      sourceRootId: srcRoot,
      targetRootId: tgtRoot,
      sourceHandle,
      targetHandle,
    };
    renderedByKey.set(key, le);
    layoutEdges.push(le);
  }

  // Lane bands span their sub-columns plus half the gutter on each side
  const lanePad = (config.columnSpacing - config.nodeWidth) / 2 - 8;
  const lanes: LaneBand[] = [];
  for (const layer of MODEL_LAYERS) {
    const ext = laneX.get(layer);
    if (!ext) continue;
    lanes.push({
      layer,
      x: ext.min - lanePad,
      width: ext.max - ext.min + config.nodeWidth + 2 * lanePad,
      height: config.topPadding + maxColHeight + config.nodeGap,
    });
  }

  return {
    groups: positioned,
    lanes,
    edges: layoutEdges,
    columns: columnHeaders,
    hiddenEdgeCount: containmentEdges.length + infraEdges.length,
    parentOf,
    childrenOf,
    flowEdges,
  };
}

// ─── Sub-columns within a lane ───────────────────────────────────────────

/**
 * Longest-path rank over flow edges whose endpoints share a lane, so that
 * e.g. a provider product sits left of the product depending on it. Cycle-safe:
 * ranks are capped at the lane size.
 */
function assignSubColumns(
  rootIds: Set<string>,
  outgoing: Map<string, Set<string>>,
  layerOf: (id: string) => string,
): Map<string, number> {
  const rank = new Map<string, number>();
  for (const id of rootIds) rank.set(id, 0);
  const laneSize = new Map<string, number>();
  for (const id of rootIds) laneSize.set(layerOf(id), (laneSize.get(layerOf(id)) ?? 0) + 1);

  // Edges are flow-oriented (upstream → downstream): target goes right of source
  let changed = true;
  for (let iter = 0; changed && iter < rootIds.size; iter++) {
    changed = false;
    for (const [src, tgts] of outgoing) {
      if (!rootIds.has(src)) continue;
      for (const tgt of tgts) {
        if (!rootIds.has(tgt) || layerOf(src) !== layerOf(tgt)) continue;
        const cap = (laneSize.get(layerOf(tgt)) ?? 1) - 1;
        const want = Math.min(cap, (rank.get(src) ?? 0) + 1);
        if ((rank.get(tgt) ?? 0) < want) {
          rank.set(tgt, want);
          changed = true;
        }
      }
    }
  }
  return rank;
}

// ─── Barycenter sorting helper ───────────────────────────────────────────

function barycenterSort(
  groups: GroupNode[],
  neighbors: Map<string, string[]>,
  yIndex: Map<string, number>,
): void {
  const bcs = groups.map((g) => {
    const ns = neighbors.get(g.id) || [];
    if (ns.length === 0) return { g, bc: yIndex.get(g.id) ?? 0 };
    const sum = ns.reduce((acc, n) => acc + (yIndex.get(n) ?? 0), 0);
    return { g, bc: sum / ns.length };
  });
  bcs.sort((a, b) => a.bc - b.bc);
  for (let i = 0; i < groups.length; i++) {
    groups[i] = bcs[i].g;
  }
}
