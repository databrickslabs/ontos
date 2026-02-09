/**
 * Type definitions for Graph Explorer.
 *
 * Defines node/edge structures, force-graph types, API types,
 * and utility functions for dynamic type coloring.
 */

export const ChangeStatus = {
  EXISTING: 'existing',
  NEW: 'new',
  MODIFIED: 'modified',
} as const;

export type ChangeStatus = (typeof ChangeStatus)[keyof typeof ChangeStatus];

// Node and relationship types are dynamic - they can be any string
// No hardcoded enums to allow for unlimited scalability

export interface NodeProperties {
  [key: string]: string | number | boolean | null;
}

export interface EdgeProperties {
  [key: string]: string | number | boolean | null;
}

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  properties: NodeProperties;
  status: ChangeStatus;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  relationshipType: string;
  properties: EdgeProperties;
  status: ChangeStatus;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// Transformed data for react-force-graph
export interface ForceGraphNode {
  id: string;
  name: string;
  type: string;
  status: ChangeStatus;
  properties: NodeProperties;
  val?: number;
  color?: string;
  // Position and velocity properties managed by d3-force
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
  fx?: number | undefined;
  fy?: number | undefined;
}

export interface ForceGraphLink {
  id: string;
  source: string;
  target: string;
  relationshipType: string;
  status: ChangeStatus;
  properties: EdgeProperties;
  color?: string;
}

export interface ForceGraphData {
  nodes: ForceGraphNode[];
  links: ForceGraphLink[];
}

export interface GraphStats {
  totalNodes: number;
  totalEdges: number;
  newNodes: number;
  newEdges: number;
  existingNodes: number;
  existingEdges: number;
  modifiedNodes: number;
  modifiedEdges: number;
}

// --- Utility functions for dynamic type extraction and color generation ---

/** Extract unique node types from graph data */
export function getUniqueNodeTypes(data: GraphData): string[] {
  const types = new Set<string>();
  data.nodes.forEach((node) => types.add(node.type));
  return Array.from(types).sort();
}

/** Extract unique relationship types from graph data */
export function getUniqueRelationshipTypes(data: GraphData): string[] {
  const types = new Set<string>();
  data.edges.forEach((edge) => types.add(edge.relationshipType));
  return Array.from(types).sort();
}

/**
 * Generate a consistent color for a given string using a hash function.
 * Returns colors from a curated palette for better visual distinction.
 */
export function getColorForType(type: string, isDarkMode: boolean = false): string {
  const darkModeColors = [
    '#42a5f5', '#ab47bc', '#ff9800', '#ef5350', '#66bb6a',
    '#ffa726', '#26c6da', '#ec407a', '#9ccc65', '#5c6bc0',
    '#ffca28', '#8d6e63', '#78909c', '#ff7043', '#ba68c8',
    '#7e57c2', '#29b6f6', '#26a69a', '#d4e157', '#ffd54f',
  ];

  const lightModeColors = [
    '#1976d2', '#7b1fa2', '#f57c00', '#c62828', '#388e3c',
    '#e64a19', '#0097a7', '#c2185b', '#689f38', '#3949ab',
    '#ffa000', '#5d4037', '#546e7a', '#d84315', '#8e24aa',
    '#5e35b1', '#0288d1', '#00897b', '#afb42b', '#ffb300',
  ];

  const colors = isDarkMode ? darkModeColors : lightModeColors;

  let hash = 0;
  for (let i = 0; i < type.length; i++) {
    hash = type.charCodeAt(i) + ((hash << 5) - hash);
    hash = hash & hash;
  }

  const index = Math.abs(hash) % colors.length;
  return colors[index];
}

/** Get color mapping for all node types in the data */
export function getNodeTypeColorMap(
  data: GraphData,
  isDarkMode: boolean = false,
): Map<string, string> {
  const colorMap = new Map<string, string>();
  const types = getUniqueNodeTypes(data);
  types.forEach((type) => {
    colorMap.set(type, getColorForType(type, isDarkMode));
  });
  return colorMap;
}
