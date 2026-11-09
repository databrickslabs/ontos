import React, { useMemo, useCallback, useState, useEffect } from 'react';
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
import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Loader2, AlertCircle } from 'lucide-react';
import {
  Box, Table2, Eye, Columns2, LayoutDashboard, Globe, FileCode, Brain,
  Activity, Server, Shield, BookOpen, Database, Shapes, Package, Tag, Send,
} from 'lucide-react';
import * as dagre from 'dagre';
import type { LineageGraph, LineageGraphNode, LineageGraphEdge } from '@/types/ontology-schema';
import { TYPE_COLOR } from '@/components/lineage/constants';
import { useFormatLabel } from '@/lib/format-label';

const ICON_MAP: Record<string, React.ElementType> = {
  Table2, Eye, Columns2, LayoutDashboard, Globe, FileCode, Brain, Activity,
  Server, Shield, BookOpen, Database, Shapes, Box, Package, Tag, Send,
};

const TYPE_ROUTE_MAP: Record<string, string> = {
  DataProduct: '/data-products',
  DataContract: '/data-contracts',
  DataDomain: '/data-domains',
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

function humanizeType(type: string): string {
  return type.replace(/([A-Z])/g, ' $1').trim();
}

// Hierarchical (containment) relationship types
const CONTAINMENT_RELS = new Set([
  'hasTable', 'hasView', 'hasColumn', 'has table', 'has view', 'has column',
  'containsDataset', 'contains dataset', 'contains',
  'hasLogicalAttribute', 'has logical attribute',
]);

// ─── Container Node ──────────────────────────────────────────────────────

interface ContainerNodeData {
  label: string;
  entityType: string;
  entityId: string;
  icon?: string | null;
  status?: string | null;
  isCenter: boolean;
  childCount: number;
  navigate: (path: string) => void;
}

const ContainerNode: React.FC<NodeProps<ContainerNodeData>> = ({ data }) => {
  const Icon = (data.icon && ICON_MAP[data.icon]) || Box;
  const colors = TYPE_COLOR[data.entityType] || TYPE_COLOR.System;

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    data.navigate(getEntityRoute(data.entityType, data.entityId));
  };

  return (
    <>
      <Handle type="target" position={Position.Left} style={{ visibility: 'hidden' }} />
      <div
        className={`rounded-lg border-2 shadow-md ${colors.bg} ${colors.border} ${
          data.isCenter ? 'ring-2 ring-primary ring-offset-2 ring-offset-background' : ''
        }`}
        style={{ minWidth: 200, minHeight: data.childCount > 0 ? 120 : 60, padding: '8px 12px' }}
      >
        <div className="flex items-center gap-2 cursor-pointer hover:opacity-80" onClick={handleClick}>
          <Icon className={`w-4 h-4 flex-shrink-0 ${colors.text}`} />
          <span className="text-sm font-medium truncate">{data.label}</span>
          <Badge variant="outline" className="text-[9px] h-3.5 px-1 font-normal ml-auto">
            {humanizeType(data.entityType)}
          </Badge>
          {data.status && (
            <Badge variant={STATUS_VARIANT[data.status] ?? 'outline'} className="text-[9px] h-3.5 px-1">
              {data.status}
            </Badge>
          )}
          {data.childCount > 0 && (
            <Badge variant="secondary" className="text-[9px] h-3.5 px-1">
              {data.childCount}
            </Badge>
          )}
        </div>
      </div>
      <Handle type="source" position={Position.Right} style={{ visibility: 'hidden' }} />
    </>
  );
};

// ─── Leaf Node ───────────────────────────────────────────────────────────

interface LeafNodeData {
  label: string;
  entityType: string;
  entityId: string;
  icon?: string | null;
  navigate: (path: string) => void;
}

const LeafNode: React.FC<NodeProps<LeafNodeData>> = ({ data }) => {
  const Icon = (data.icon && ICON_MAP[data.icon]) || Box;
  const colors = TYPE_COLOR[data.entityType] || TYPE_COLOR.System;

  return (
    <>
      <Handle type="target" position={Position.Left} style={{ visibility: 'hidden' }} />
      <button
        onClick={() => data.navigate(getEntityRoute(data.entityType, data.entityId))}
        className={`flex items-center gap-1.5 px-2 py-1 rounded border text-left hover:shadow-md transition-shadow ${colors.bg} ${colors.border}`}
      >
        <Icon className={`w-3 h-3 flex-shrink-0 ${colors.text}`} />
        <span className="text-xs truncate max-w-32">{data.label}</span>
      </button>
      <Handle type="source" position={Position.Right} style={{ visibility: 'hidden' }} />
    </>
  );
};

const nodeTypes = { containerNode: ContainerNode, leafNode: LeafNode };

// ─── Graph building ──────────────────────────────────────────────────────

const CONTAINER_W = 220;
const CONTAINER_H = 80;
const LEAF_H = 32;

function buildLineageFlowGraph(
  data: LineageGraph,
  navigate: (path: string) => void,
  isDark: boolean,
  formatLabel: (s: string | null | undefined) => string,
): { nodes: Node[]; edges: Edge[] } {
  // Identify containment edges and non-containment (flow) edges
  const containmentEdges: LineageGraphEdge[] = [];
  const flowEdges: LineageGraphEdge[] = [];

  for (const edge of data.edges) {
    const relType = edge.relationship_type || '';
    const label = edge.label || '';
    if (CONTAINMENT_RELS.has(relType) || CONTAINMENT_RELS.has(label)) {
      containmentEdges.push(edge);
    } else {
      flowEdges.push(edge);
    }
  }

  // Build parent→children map from containment edges
  const parentOf: Record<string, string> = {};
  const childrenOf: Record<string, string[]> = {};
  for (const edge of containmentEdges) {
    parentOf[edge.target] = edge.source;
    if (!childrenOf[edge.source]) childrenOf[edge.source] = [];
    childrenOf[edge.source].push(edge.target);
  }

  // Identify top-level nodes (no parent)
  const topLevel = data.nodes.filter(n => !parentOf[n.id]);

  // Build dagre layout for top-level containers
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: 'LR', nodesep: 60, ranksep: 100 });

  const nodeMap = new Map<string, LineageGraphNode>();
  for (const n of data.nodes) nodeMap.set(n.id, n);

  // Add top-level nodes to dagre
  for (const n of topLevel) {
    const children = childrenOf[n.id] || [];
    const h = children.length > 0 ? CONTAINER_H + children.length * (LEAF_H + 8) : CONTAINER_H;
    g.setNode(n.id, { width: CONTAINER_W, height: h });
  }

  // Add flow edges between top-level nodes (or their ancestors)
  const getAncestor = (id: string): string => {
    let cur = id;
    while (parentOf[cur]) cur = parentOf[cur];
    return cur;
  };

  for (const edge of flowEdges) {
    const srcTop = getAncestor(edge.source);
    const tgtTop = getAncestor(edge.target);
    if (srcTop !== tgtTop && g.node(srcTop) && g.node(tgtTop)) {
      g.setEdge(srcTop, tgtTop);
    }
  }

  dagre.layout(g);

  const resultNodes: Node[] = [];
  const resultEdges: Edge[] = [];

  // Place top-level containers
  for (const n of topLevel) {
    const pos = g.node(n.id);
    if (!pos) continue;
    const children = childrenOf[n.id] || [];
    const h = children.length > 0 ? CONTAINER_H + children.length * (LEAF_H + 8) : CONTAINER_H;

    resultNodes.push({
      id: n.id,
      type: 'containerNode',
      position: { x: pos.x - CONTAINER_W / 2, y: pos.y - h / 2 },
      data: {
        label: n.name,
        entityType: n.entity_type,
        entityId: n.entity_id,
        icon: n.icon,
        status: n.status,
        isCenter: n.is_center,
        childCount: children.length,
        navigate,
      },
      style: { width: CONTAINER_W, height: h },
    });

    // Place children inside the container
    children.forEach((childId, ci) => {
      const child = nodeMap.get(childId);
      if (!child) return;
      resultNodes.push({
        id: child.id,
        type: 'leafNode',
        position: { x: 12, y: 40 + ci * (LEAF_H + 8) },
        parentNode: n.id,
        extent: 'parent' as const,
        data: {
          label: child.name,
          entityType: child.entity_type,
          entityId: child.entity_id,
          icon: child.icon,
          navigate,
        },
      });
    });
  }

  // Add flow edges
  for (const edge of flowEdges) {
    resultEdges.push({
      id: `flow-${edge.source}-${edge.target}`,
      source: edge.source,
      target: edge.target,
      type: 'smoothstep',
      label: formatLabel(edge.label) || undefined,
      labelStyle: { fontSize: 9, fill: isDark ? '#94a3b8' : '#64748b' },
      labelBgStyle: { fill: isDark ? '#1e293b' : '#f8fafc', fillOpacity: 0.9 },
      labelBgPadding: [4, 2] as [number, number],
      animated: false,
      markerEnd: { type: MarkerType.ArrowClosed, color: isDark ? '#94a3b8' : '#333' },
      style: { stroke: isDark ? '#475569' : '#94a3b8', strokeWidth: 1.5 },
    });
  }

  return { nodes: resultNodes, edges: resultEdges };
}

// ─── Main Component ──────────────────────────────────────────────────────

interface LineageFlowGraphProps {
  entityType: string;
  entityId: string;
  className?: string;
  maxDepth?: number;
}

export function LineageFlowGraph({
  entityType,
  entityId,
  className,
  maxDepth = 3,
}: LineageFlowGraphProps) {
  const navigate = useNavigate();
  const { t } = useTranslation('common');
  const isDark = typeof document !== 'undefined' && document.documentElement.classList.contains('dark');
  const formatLabel = useFormatLabel();

  const [graphData, setGraphData] = useState<LineageGraph | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchGraph = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ max_depth: String(maxDepth) });
      const res = await fetch(
        `/api/business-lineage/${entityType}/${entityId}?${params}`
      );
      if (!res.ok) throw new Error(t('common:businessLineage.failedLoadLineage', { status: res.status }));
      setGraphData(await res.json());
    } catch (e: any) {
      setError(e.message || t('common:lineageFlow.failedLoad'));
    } finally {
      setIsLoading(false);
    }
  }, [entityType, entityId, maxDepth, t]);

  useEffect(() => { fetchGraph(); }, [fetchGraph]);

  const { layoutedNodes, layoutedEdges } = useMemo(() => {
    if (!graphData || graphData.nodes.length === 0) {
      return { layoutedNodes: [], layoutedEdges: [] };
    }
    const { nodes, edges } = buildLineageFlowGraph(graphData, navigate, isDark, formatLabel);
    return { layoutedNodes: nodes, layoutedEdges: edges };
  }, [graphData, navigate, isDark, formatLabel]);

  const [nodes, setNodes, onNodesChange] = useNodesState(layoutedNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(layoutedEdges);

  useEffect(() => {
    setNodes(layoutedNodes);
    setEdges(layoutedEdges);
  }, [layoutedNodes, layoutedEdges, setNodes, setEdges]);

  if (isLoading) {
    return (
      <div className={`flex items-center justify-center ${className || 'h-64'}`}>
        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
        <span className="ml-2 text-sm text-muted-foreground">{t('common:lineageFlow.loadingLineage')}</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className={`flex flex-col items-center justify-center gap-2 ${className || 'h-64'}`}>
        <AlertCircle className="w-6 h-6 text-destructive" />
        <p className="text-sm text-destructive">{error}</p>
        <Button variant="outline" size="sm" onClick={fetchGraph}>{t('common:retry')}</Button>
      </div>
    );
  }

  if (!graphData || graphData.nodes.length === 0) {
    return (
      <div className={`flex items-center justify-center ${className || 'h-64'}`}>
        <p className="text-sm text-muted-foreground">{t('common:lineageFlow.noLineageData')}</p>
      </div>
    );
  }

  return (
    <div className={`flex flex-col ${className || 'h-[500px]'}`}>
      <div className="flex items-center gap-4 px-3 py-2 border-b bg-muted/30">
        <span className="text-xs text-muted-foreground">
          {t('common:businessLineage.countBadge', { entities: graphData.nodes.length, relationships: graphData.edges.length })}
        </span>
      </div>

      <div className="flex-1 border rounded-b-lg">
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
              const type = n.data?.entityType;
              return TYPE_COLOR[type]?.minimap || '#6b7280';
            }}
          />
          <Background color={isDark ? '#334155' : '#e2e8f0'} gap={16} />
        </ReactFlow>
      </div>
    </div>
  );
}
