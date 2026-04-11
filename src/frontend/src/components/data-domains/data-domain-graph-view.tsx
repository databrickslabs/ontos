/**
 * Domain taxonomy graph using ReactFlow + dagre layout.
 * Shows data domains as an interactive hierarchical graph with 3 custom node types:
 *   - SchemeNode: dark root node (top of hierarchy)
 *   - DomainNode: colored pill for top-level domains
 *   - SubdomainNode: white pill for child domains
 *
 * Includes MiniMap, Controls, Background, domain-based coloring, and
 * top-to-bottom dagre layout for clear hierarchy visualization.
 */
import React, { useMemo, useEffect } from 'react';
import ReactFlow, {
  Node,
  Edge,
  Position,
  useNodesState,
  useEdgesState,
  Controls,
  Background,
  MiniMap,
  Handle,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { useNavigate } from 'react-router-dom';
import { DataDomain } from '@/types/data-domain';
import dagre from 'dagre';

// ---- Domain Color Map ----
// Assigns consistent colors to well-known domain labels.
// Falls back to a neutral blue for unrecognized domains.

const DOMAIN_COLOR_MAP: Record<string, string> = {
  'Customer': '#3b82f6',
  'Energy': '#06b6d4',
  'Billing': '#eab308',
  'Billing & Payments': '#eab308',
  'Network': '#7c3aed',
  'Network & Infrastructure': '#7c3aed',
  'Solar': '#22c55e',
  'Solar & Batteries': '#22c55e',
  'Wholesale': '#f97316',
  'Wholesale & Trading': '#f97316',
  'Digital': '#a855f7',
  'Digital & Experience': '#a855f7',
  'Regulatory': '#ef4444',
  'Regulatory & Compliance': '#ef4444',
  // Generic fallbacks
  'Finance': '#eab308',
  'Operations': '#14b8a6',
  'Marketing': '#ec4899',
  'Analytics': '#6366f1',
  'Compliance': '#ef4444',
  'Security': '#dc2626',
  'Research': '#8b5cf6',
  'Clinical': '#0ea5e9',
};

function getDomainColor(label: string): string {
  // Exact match first
  if (DOMAIN_COLOR_MAP[label]) return DOMAIN_COLOR_MAP[label];
  // Partial match
  for (const [key, color] of Object.entries(DOMAIN_COLOR_MAP)) {
    if (label.includes(key) || key.includes(label)) return color;
  }
  return '#3b82f6';
}

// ---- Custom Node Components ----

interface SchemeNodeData {
  label: string;
}

const SchemeNode: React.FC<{ data: SchemeNodeData }> = ({ data }) => {
  return (
    <div className="bg-slate-800 dark:bg-slate-200 text-white dark:text-slate-900 rounded-xl px-7 py-3.5 font-bold text-[15px] text-center min-w-[160px] border-2 border-slate-800 dark:border-slate-200 shadow-lg">
      <Handle type="target" position={Position.Top} style={{ visibility: 'hidden' }} />
      {data.label}
      <Handle type="source" position={Position.Bottom} style={{ visibility: 'hidden' }} />
    </div>
  );
};

interface DomainNodeData {
  label: string;
  id: string;
  parentId?: string | null;
  childrenCount?: number;
  notation?: string;
}

const DomainNode: React.FC<{ data: DomainNodeData; id: string }> = ({ data, id }) => {
  const navigate = useNavigate();
  const color = getDomainColor(data.label);

  return (
    <div
      className="rounded-full px-6 py-3 font-semibold text-[13px] text-center min-w-[140px] cursor-pointer text-white transition-transform hover:scale-105"
      style={{
        backgroundColor: color,
        border: `2px solid ${color}`,
        boxShadow: '0 2px 8px rgba(0,0,0,0.12)',
      }}
      onClick={() => navigate(`/settings/data-domains/${id}`)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && navigate(`/settings/data-domains/${id}`)}
    >
      <Handle type="target" position={Position.Top} style={{ visibility: 'hidden' }} />
      {data.label}
      {data.childrenCount !== undefined && data.childrenCount > 0 && (
        <div className="text-[10px] opacity-80 mt-0.5">
          {data.childrenCount} {data.childrenCount === 1 ? 'subdomain' : 'subdomains'}
        </div>
      )}
      {data.notation && (
        <div className="text-[10px] opacity-70 mt-0.5 font-mono">{data.notation}</div>
      )}
      <Handle type="source" position={Position.Bottom} style={{ visibility: 'hidden' }} />
    </div>
  );
};

interface SubdomainNodeData {
  label: string;
  id: string;
  parentId?: string | null;
  childrenCount?: number;
  notation?: string;
}

const SubdomainNode: React.FC<{ data: SubdomainNodeData; id: string }> = ({ data, id }) => {
  const navigate = useNavigate();

  return (
    <div
      className="bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-200 rounded-full px-5 py-2.5 text-[12px] text-center min-w-[120px] border border-slate-200 dark:border-slate-600 cursor-pointer transition-all hover:shadow-md hover:border-blue-300 dark:hover:border-blue-500"
      onClick={() => navigate(`/settings/data-domains/${id}`)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && navigate(`/settings/data-domains/${id}`)}
    >
      <Handle type="target" position={Position.Top} style={{ visibility: 'hidden' }} />
      {data.label}
      {data.childrenCount !== undefined && data.childrenCount > 0 && (
        <div className="text-[10px] text-muted-foreground mt-0.5">
          {data.childrenCount} children
        </div>
      )}
      {data.notation && (
        <div className="text-[9px] text-muted-foreground mt-0.5 font-mono">{data.notation}</div>
      )}
      <Handle type="source" position={Position.Bottom} style={{ visibility: 'hidden' }} />
    </div>
  );
};

const nodeTypes = {
  schemeNode: SchemeNode,
  domainNode: DomainNode,
  subdomainNode: SubdomainNode,
};

// ---- Dagre Layout ----

const NODE_DIMENSIONS: Record<string, { width: number; height: number }> = {
  schemeNode: { width: 200, height: 50 },
  domainNode: { width: 170, height: 55 },
  subdomainNode: { width: 150, height: 45 },
};

interface DataDomainGraphViewProps {
  domains: DataDomain[];
}

const getLayoutedElements = (domains: DataDomain[]) => {
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  if (!domains || domains.length === 0) return { nodes, edges };

  const isDarkMode = document.documentElement.classList.contains('dark');
  const domainMap = new Map(domains.map(d => [d.id, d]));

  // Identify root domains (no parent or parent not in the set)
  const rootDomains = domains.filter(d => !d.parent_id || !domainMap.has(d.parent_id));
  const hasHierarchy = rootDomains.length < domains.length;

  // If there are root domains with children, add a virtual scheme node
  const schemeId = '__scheme__';
  if (hasHierarchy && rootDomains.length > 1) {
    nodes.push({
      id: schemeId,
      type: 'schemeNode',
      data: { label: 'Data Domains' },
      position: { x: 0, y: 0 },
      sourcePosition: Position.Bottom,
      targetPosition: Position.Top,
    });
  }

  // Categorize each domain
  domains.forEach(domain => {
    const isRoot = !domain.parent_id || !domainMap.has(domain.parent_id);
    const hasChildren = domains.some(d => d.parent_id === domain.id);

    // Determine node type based on position in hierarchy
    let nodeType: string;
    if (isRoot && hasChildren) {
      nodeType = 'domainNode';
    } else if (isRoot && !hasChildren) {
      // Single-level: treat as domain node
      nodeType = 'domainNode';
    } else {
      nodeType = 'subdomainNode';
    }

    nodes.push({
      id: domain.id,
      type: nodeType,
      data: {
        label: domain.name,
        id: domain.id,
        parentId: domain.parent_id,
        childrenCount: domain.children_count,
      },
      position: { x: 0, y: 0 },
      sourcePosition: Position.Bottom,
      targetPosition: Position.Top,
    });

    // Edge: parent → child
    if (domain.parent_id && domainMap.has(domain.parent_id)) {
      edges.push({
        id: `e-${domain.parent_id}-${domain.id}`,
        source: domain.parent_id,
        target: domain.id,
        type: 'smoothstep',
        style: {
          stroke: isDarkMode ? '#475569' : '#d1d5db',
          strokeWidth: 2,
        },
      });
    } else if (hasHierarchy && rootDomains.length > 1) {
      // Connect root domains to scheme node
      edges.push({
        id: `e-${schemeId}-${domain.id}`,
        source: schemeId,
        target: domain.id,
        type: 'smoothstep',
        style: {
          stroke: isDarkMode ? '#475569' : '#d1d5db',
          strokeWidth: 2,
        },
      });
    }
  });

  // Apply dagre layout (top-to-bottom)
  if (nodes.length > 0) {
    const g = new dagre.graphlib.Graph();
    g.setDefaultEdgeLabel(() => ({}));
    g.setGraph({ rankdir: 'TB', ranksep: 80, nodesep: 40 });

    nodes.forEach(node => {
      const dims = NODE_DIMENSIONS[node.type || 'subdomainNode'] ?? { width: 150, height: 50 };
      g.setNode(node.id, { width: dims.width, height: dims.height });
    });

    edges.forEach(edge => {
      g.setEdge(edge.source, edge.target);
    });

    dagre.layout(g);

    return {
      nodes: nodes.map(node => {
        const pos = g.node(node.id);
        const dims = NODE_DIMENSIONS[node.type || 'subdomainNode'] ?? { width: 150, height: 50 };
        return {
          ...node,
          position: { x: pos.x - dims.width / 2, y: pos.y - dims.height / 2 },
        };
      }),
      edges,
    };
  }

  return { nodes, edges };
};

// ---- Main Component ----

const DataDomainGraphView: React.FC<DataDomainGraphViewProps> = ({ domains }) => {
  const memoizedElements = useMemo(() => getLayoutedElements(domains), [domains]);
  const [nodes, setNodes, onNodesChange] = useNodesState(memoizedElements.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(memoizedElements.edges);
  const isDarkMode = document.documentElement.classList.contains('dark');

  useEffect(() => {
    const { nodes: newNodes, edges: newEdges } = getLayoutedElements(domains);
    setNodes(newNodes);
    setEdges(newEdges);
  }, [domains, setNodes, setEdges]);

  return (
    <div className="h-[calc(100vh-280px)] w-full border rounded-lg overflow-hidden" data-testid="data-domain-graph-view">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.3}
        maxZoom={2}
        attributionPosition="bottom-right"
        className="bg-background"
      >
        <Controls />
        <MiniMap
          nodeColor={(node) => {
            if (node.type === 'schemeNode') return isDarkMode ? '#e2e8f0' : '#1e293b';
            if (node.type === 'domainNode') return getDomainColor(node.data?.label ?? '');
            return isDarkMode ? '#475569' : '#d1d5db';
          }}
          maskColor={isDarkMode ? 'rgba(0, 0, 0, 0.15)' : 'rgba(0, 0, 0, 0.05)'}
          style={{ borderRadius: '8px' }}
          zoomable
          pannable
        />
        <Background color={isDarkMode ? '#334155' : '#e2e8f0'} gap={20} />
      </ReactFlow>
    </div>
  );
};

export default DataDomainGraphView;
