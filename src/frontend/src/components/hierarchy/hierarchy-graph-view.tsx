import React, { useMemo } from 'react';
import ReactFlow, {
  Node,
  Edge,
  Position,
  MarkerType,
  useNodesState,
  useEdgesState,
  Controls,
  Background,
  MiniMap,
  NodeProps,
  Handle,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { useNavigate } from 'react-router-dom';
import { Card, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  Box, Table2, Eye, Columns2, LayoutDashboard, Globe, FileCode, Brain,
  Activity, Server, Shield, BookOpen, Database, FolderOpen, Shapes, Network,
  Package,
} from 'lucide-react';
import * as dagre from 'dagre';
import type { InstanceHierarchyNode } from '@/types/ontology-schema';

const ICON_MAP: Record<string, React.ElementType> = {
  Table2, Eye, Columns2, LayoutDashboard, Globe, FileCode, Brain, Activity,
  Server, Shield, BookOpen, Database, FolderOpen, Shapes, Box, Network, Package,
};

const TYPE_ROUTE_MAP: Record<string, string> = {
  DataProduct: '/data-products',
  DataContract: '/data-contracts',
  DataDomain: '/data-domains',
};

const TYPE_COLOR: Record<string, { bg: string; border: string; text: string }> = {
  System:         { bg: 'bg-blue-500/10',    border: 'border-blue-500/40',    text: 'text-blue-600 dark:text-blue-400' },
  DataDomain:     { bg: 'bg-purple-500/10',  border: 'border-purple-500/40',  text: 'text-purple-600 dark:text-purple-400' },
  DataProduct:    { bg: 'bg-emerald-500/10', border: 'border-emerald-500/40', text: 'text-emerald-600 dark:text-emerald-400' },
  Dataset:        { bg: 'bg-amber-500/10',   border: 'border-amber-500/40',   text: 'text-amber-600 dark:text-amber-400' },
  Table:          { bg: 'bg-orange-500/10',  border: 'border-orange-500/40',  text: 'text-orange-600 dark:text-orange-400' },
  View:           { bg: 'bg-teal-500/10',    border: 'border-teal-500/40',    text: 'text-teal-600 dark:text-teal-400' },
  Column:         { bg: 'bg-slate-500/10',   border: 'border-slate-500/40',   text: 'text-slate-600 dark:text-slate-400' },
  Schema:         { bg: 'bg-violet-500/10',  border: 'border-violet-500/40',  text: 'text-violet-600 dark:text-violet-400' },
  DataContract:   { bg: 'bg-pink-500/10',    border: 'border-pink-500/40',    text: 'text-pink-600 dark:text-pink-400' },
};

const STATUS_VARIANT: Record<string, 'default' | 'secondary' | 'outline' | 'destructive'> = {
  draft: 'outline',
  active: 'default',
  deprecated: 'secondary',
  archived: 'destructive',
};

function getEntityRoute(entityType: string, entityId: string): string {
  const base = TYPE_ROUTE_MAP[entityType];
  if (base) return `${base}/${entityId}`;
  return `/assets/${entityId}`;
}

interface HierarchyNodeData {
  label: string;
  entityType: string;
  entityId: string;
  icon?: string | null;
  status?: string | null;
  childCount: number;
  relationshipLabel?: string | null;
  navigate: (path: string) => void;
}

const HierarchyNode: React.FC<NodeProps<HierarchyNodeData>> = ({ data }) => {
  const Icon = (data.icon && ICON_MAP[data.icon]) || Box;
  const colors = TYPE_COLOR[data.entityType] || TYPE_COLOR.System;

  const handleClick = () => {
    data.navigate(getEntityRoute(data.entityType, data.entityId));
  };

  return (
    <>
      <Handle type="target" position={Position.Top} id="target" style={{ visibility: 'hidden' }} />
      <Card
        onClick={handleClick}
        className={`w-56 shadow-md hover:shadow-lg transition-shadow rounded-lg cursor-pointer ${colors.bg} ${colors.border} border react-flow__node-default`}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && handleClick()}
      >
        <CardHeader className="p-2.5 space-y-0">
          <CardTitle className="text-xs font-medium flex items-center gap-1.5">
            <Icon className={`w-3.5 h-3.5 flex-shrink-0 ${colors.text}`} />
            <span className="truncate">{data.label}</span>
          </CardTitle>
          <div className="flex items-center gap-1 mt-1">
            <Badge variant="outline" className="text-[9px] h-3.5 px-1 font-normal">
              {data.entityType}
            </Badge>
            {data.status && (
              <Badge
                variant={STATUS_VARIANT[data.status] ?? 'outline'}
                className="text-[9px] h-3.5 px-1"
              >
                {data.status}
              </Badge>
            )}
            {data.childCount > 0 && (
              <span className="text-[9px] text-muted-foreground ml-auto">
                {data.childCount}
              </span>
            )}
          </div>
        </CardHeader>
      </Card>
      <Handle type="source" position={Position.Bottom} id="source" style={{ visibility: 'hidden' }} />
    </>
  );
};

const nodeTypes = { hierarchyNode: HierarchyNode };

const NODE_WIDTH = 224;
const NODE_HEIGHT = 64;

interface FlattenResult {
  nodes: Node<HierarchyNodeData>[];
  edges: Edge[];
}

function flattenHierarchy(
  root: InstanceHierarchyNode,
  navigate: (path: string) => void,
  isDark: boolean,
): FlattenResult {
  const nodes: Node<HierarchyNodeData>[] = [];
  const edges: Edge[] = [];
  const seen = new Set<string>();

  function walk(node: InstanceHierarchyNode, parentKey?: string) {
    const key = `${node.entity_type}-${node.entity_id}`;
    if (seen.has(key)) return;
    seen.add(key);

    nodes.push({
      id: key,
      type: 'hierarchyNode',
      position: { x: 0, y: 0 },
      sourcePosition: Position.Bottom,
      targetPosition: Position.Top,
      data: {
        label: node.name,
        entityType: node.entity_type,
        entityId: node.entity_id,
        icon: node.icon,
        status: node.status,
        childCount: node.child_count,
        relationshipLabel: node.relationship_label,
        navigate,
      },
    });

    if (parentKey) {
      const edgeLabel = node.relationship_label || node.relationship_type || '';
      edges.push({
        id: `e-${parentKey}-${key}`,
        source: parentKey,
        target: key,
        type: 'smoothstep',
        label: edgeLabel || undefined,
        labelStyle: { fontSize: 9, fill: isDark ? '#94a3b8' : '#64748b' },
        labelBgStyle: { fill: isDark ? '#1e293b' : '#f8fafc', fillOpacity: 0.9 },
        labelBgPadding: [4, 2] as [number, number],
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: isDark ? '#94a3b8' : '#333',
        },
        style: {
          stroke: isDark ? '#475569' : '#94a3b8',
          strokeWidth: 1.5,
        },
      });
    }

    for (const child of node.children || []) {
      walk(child, key);
    }
  }

  walk(root);
  return { nodes, edges };
}

function applyDagreLayout(
  nodes: Node<HierarchyNodeData>[],
  edges: Edge[],
  direction: 'TB' | 'LR' = 'TB',
): Node<HierarchyNodeData>[] {
  if (nodes.length === 0) return nodes;

  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: direction, nodesep: 40, ranksep: 60 });

  nodes.forEach((n) => g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT }));
  edges.forEach((e) => g.setEdge(e.source, e.target));

  dagre.layout(g);

  return nodes.map((n) => {
    const pos = g.node(n.id);
    const isHorizontal = direction === 'LR';
    return {
      ...n,
      targetPosition: isHorizontal ? Position.Left : Position.Top,
      sourcePosition: isHorizontal ? Position.Right : Position.Bottom,
      position: { x: pos.x - NODE_WIDTH / 2, y: pos.y - NODE_HEIGHT / 2 },
    };
  });
}

interface HierarchyGraphViewProps {
  rootNode: InstanceHierarchyNode;
  className?: string;
}

export function HierarchyGraphView({ rootNode, className }: HierarchyGraphViewProps) {
  const navigate = useNavigate();
  const isDark = typeof document !== 'undefined' && document.documentElement.classList.contains('dark');

  const { layoutedNodes, layoutedEdges } = useMemo(() => {
    const { nodes, edges } = flattenHierarchy(rootNode, navigate, isDark);
    const laid = applyDagreLayout(nodes, edges, 'TB');
    return { layoutedNodes: laid, layoutedEdges: edges };
  }, [rootNode, navigate, isDark]);

  const [nodes, setNodes, onNodesChange] = useNodesState(layoutedNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(layoutedEdges);

  React.useEffect(() => {
    setNodes(layoutedNodes);
    setEdges(layoutedEdges);
  }, [layoutedNodes, layoutedEdges, setNodes, setEdges]);

  return (
    <div className={`w-full border rounded-lg ${className || 'h-full'}`} data-testid="hierarchy-graph-view">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        attributionPosition="bottom-right"
        className="bg-background"
        minZoom={0.1}
        maxZoom={2}
        nodesDraggable
        nodesConnectable={false}
      >
        <Controls />
        <MiniMap
          nodeStrokeWidth={3}
          zoomable
          pannable
          nodeColor={(n: Node) => {
            const type = (n.data as HierarchyNodeData)?.entityType;
            const colors: Record<string, string> = {
              System: '#3b82f6',
              DataDomain: '#a855f7',
              DataProduct: '#10b981',
              Dataset: '#f59e0b',
              Table: '#f97316',
              View: '#14b8a6',
              Column: '#64748b',
              Schema: '#8b5cf6',
              DataContract: '#ec4899',
            };
            return colors[type] || '#6b7280';
          }}
        />
        <Background color={isDark ? '#334155' : '#e2e8f0'} gap={16} />
      </ReactFlow>
    </div>
  );
}
