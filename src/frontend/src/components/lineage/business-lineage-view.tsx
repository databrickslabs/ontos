/**
 * ERD-style column lineage visualization — Collibra/Informatica inspired.
 *
 * Entities as ERD cards in vertical columns, flowing left-to-right.
 * Containment relationships collapse children inside parent cards.
 * Edges route to specific child-row handles for column-level lineage.
 * Infrastructure (System) shown as badges, not nodes.
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import ReactFlow, {
  Node,
  Edge,
  MarkerType,
  useNodesState,
  useEdgesState,
  MiniMap,
  useReactFlow,
  ReactFlowProvider,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Loader2, AlertCircle, Network } from 'lucide-react';
import { cn } from '@/lib/utils';

import type { LineageGraph } from '@/types/ontology-schema';
import { layoutLineageGraph, DEFAULT_CONFIG } from './layout';
import type { LayoutConfig } from './layout';
import { TYPE_COLOR, DEFAULT_HEX, getEntityRoute, categorizeEdge } from './constants';
import type { LineageDirection } from './lineage-toolbar';
import LineageToolbar from './lineage-toolbar';
import LineageLegend from './lineage-legend';
import LineageEntityCard from './lineage-entity-card';
import type { GroupCardData } from './lineage-entity-card';
import LineageColumnHeader from './lineage-column-header';
import type { ColumnHeaderData } from './lineage-column-header';

// ─── Custom node types ──────────────────────────────────────────────────

const nodeTypes = {
  lineageCard: LineageEntityCard,
  columnHeader: LineageColumnHeader,
};

// ─── Edge style by category ─────────────────────────────────────────────

function getEdgeStyle(relType: string, isDark: boolean): Partial<Edge> {
  const cat = categorizeEdge(relType);

  switch (cat) {
    case 'flow':
      return {
        style: {
          stroke: isDark ? 'rgba(148,163,184,0.8)' : 'rgba(71,85,105,0.65)',
          strokeWidth: 1.5,
        },
      };
    case 'hierarchy':
      return {
        style: {
          stroke: isDark ? 'rgba(148,163,184,0.5)' : 'rgba(100,116,139,0.4)',
          strokeWidth: 1,
        },
      };
    case 'governance':
      return {
        style: {
          stroke: isDark ? 'rgba(148,163,184,0.6)' : 'rgba(100,116,139,0.5)',
          strokeWidth: 1,
          strokeDasharray: '6 3',
        },
      };
    case 'semantic':
      return {
        style: {
          stroke: isDark ? 'rgba(148,163,184,0.4)' : 'rgba(100,116,139,0.3)',
          strokeWidth: 1,
          strokeDasharray: '2 3',
        },
      };
  }
}

// ─── Props ──────────────────────────────────────────────────────────────

export interface BusinessLineageViewProps {
  entityType: string;
  entityId: string;
  entityName?: string;
  className?: string;
  direction?: LineageDirection;
  maxDepth?: number;
  showToolbar?: boolean;
  showMinimap?: boolean;
}

// ─── Inner component (needs ReactFlowProvider ancestor) ─────────────────

function BusinessLineageViewInner({
  entityType,
  entityId,
  className,
  direction: initialDirection = 'both',
  maxDepth: initialMaxDepth = 2,
  showToolbar = true,
  showMinimap = true,
}: BusinessLineageViewProps) {
  const navigate = useNavigate();
  const { t } = useTranslation(['data-catalog', 'common']);
  const { fitView, zoomIn, zoomOut } = useReactFlow();

  const [direction, setDirection] = useState<LineageDirection>(initialDirection);
  const [maxDepth, setMaxDepth] = useState(initialMaxDepth);
  const [nestingDepth, setNestingDepth] = useState(2);
  const [graph, setGraph] = useState<LineageGraph | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showLegend, setShowLegend] = useState(false);
  const [isDark, setIsDark] = useState(false);

  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  const layoutConfig = useMemo<LayoutConfig>(() => ({ ...DEFAULT_CONFIG, nestingDepth }), [nestingDepth]);

  // Dark mode detection
  useEffect(() => {
    const check = () => setIsDark(document.documentElement.classList.contains('dark'));
    check();
    const obs = new MutationObserver(check);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => obs.disconnect();
  }, []);

  // Navigation handler
  const handleNodeClick = useCallback((eType: string, eId: string) => {
    navigate(getEntityRoute(eType, eId));
  }, [navigate]);

  // Fetch lineage data
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    const params = new URLSearchParams({ max_depth: String(maxDepth) });
    if (direction !== 'both') params.set('direction', direction);

    fetch(`/api/business-lineage/${entityType}/${entityId}?${params}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
        return res.json();
      })
      .then((data: LineageGraph) => {
        if (!cancelled) setGraph(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [entityType, entityId, direction, maxDepth]);

  // Compute layout when graph changes
  useEffect(() => {
    if (!graph) {
      setNodes((prev) => prev.length ? [] : prev);
      setEdges((prev) => prev.length ? [] : prev);
      return;
    }

    const layout = layoutLineageGraph(graph, layoutConfig);
    const centerId = `${graph.center_entity_type}:${graph.center_entity_id}`;

    const rfNodes: Node[] = [];

    // Column headers
    for (const col of layout.columns) {
      rfNodes.push({
        id: `header-${col.column}`,
        type: 'columnHeader',
        position: { x: col.x, y: 0 },
        data: { label: col.label } satisfies ColumnHeaderData,
        draggable: false,
        selectable: false,
        connectable: false,
      });
    }

    // ERD-style group cards
    for (const g of layout.groups) {
      rfNodes.push({
        id: g.id,
        type: 'lineageCard',
        position: { x: g.x, y: g.y },
        data: {
          node: g.node,
          children: g.children,
          childDepths: g.childDepths,
          isCenter: g.id === centerId,
          system: g.system,
          config: layoutConfig,
          onClick: handleNodeClick,
        } satisfies GroupCardData,
        draggable: true,
        selectable: true,
        connectable: false,
      });
    }

    // Edges with child-level handle routing
    const rfEdges: Edge[] = layout.edges.map((le) => {
      const edgeStyle = getEdgeStyle(le.edge.relationship_type, isDark);
      const strokeColor = (edgeStyle.style as Record<string, string>)?.stroke || '#64748b';

      return {
        id: le.id,
        source: le.sourceRootId,
        target: le.targetRootId,
        sourceHandle: le.sourceHandle || 'parent',
        targetHandle: le.targetHandle || 'parent',
        type: 'smoothstep',
        // Only show labels for parent-to-parent edges (avoid clutter)
        label: (!le.sourceHandle && !le.targetHandle) ? (le.edge.label || undefined) : undefined,
        labelStyle: { fontSize: 10, fill: isDark ? '#94a3b8' : '#64748b' },
        labelBgStyle: {
          fill: isDark ? '#1e293b' : '#ffffff',
          fillOpacity: 0.85,
        },
        labelBgPadding: [6, 3] as [number, number],
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 10,
          height: 10,
          color: strokeColor,
        },
        ...edgeStyle,
      };
    });

    setNodes(rfNodes);
    setEdges(rfEdges);

    requestAnimationFrame(() => fitView({ padding: 0.12, duration: 300 }));
  }, [graph, isDark, handleNodeClick, setNodes, setEdges, fitView, layoutConfig, nestingDepth]);

  // ─── Render ──────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className={cn('flex items-center justify-center bg-muted/20 rounded-md', className)}>
        <div className="flex flex-col items-center gap-2 text-muted-foreground">
          <Loader2 className="h-6 w-6 animate-spin" />
          <span className="text-sm">{t('data-catalog:lineage.loadingLineage')}</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={cn('flex items-center justify-center bg-muted/20 rounded-md', className)}>
        <div className="flex flex-col items-center gap-2 text-destructive">
          <AlertCircle className="h-6 w-6" />
          <span className="text-sm">{error}</span>
        </div>
      </div>
    );
  }

  if (!graph || graph.nodes.length === 0) {
    return (
      <div className={cn('flex items-center justify-center bg-muted/20 rounded-md', className)}>
        <div className="flex flex-col items-center gap-2 text-muted-foreground">
          <Network className="h-6 w-6" />
          <span className="text-sm">{t('data-catalog:lineage.noDataAvailable')}</span>
        </div>
      </div>
    );
  }

  return (
    <div className={cn('flex flex-col rounded-md border bg-background', className)}>
      {showToolbar && (
        <LineageToolbar
          direction={direction}
          onDirectionChange={setDirection}
          maxDepth={maxDepth}
          onMaxDepthChange={setMaxDepth}
          nestingDepth={nestingDepth}
          onNestingDepthChange={setNestingDepth}
          nodeCount={graph.nodes.length}
          edgeCount={graph.edges.length}
          showLegend={showLegend}
          onToggleLegend={() => setShowLegend((p) => !p)}
          onFitView={() => fitView({ padding: 0.12, duration: 300 })}
          onZoomIn={() => zoomIn({ duration: 200 })}
          onZoomOut={() => zoomOut({ duration: 200 })}
        />
      )}

      <div className="flex-1 relative min-h-0">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.12 }}
          minZoom={0.15}
          maxZoom={2}
          proOptions={{ hideAttribution: true }}
          className="bg-background"
        >
          {showMinimap && (
            <MiniMap
              nodeColor={(n) => {
                if (n.type === 'columnHeader') return 'transparent';
                return TYPE_COLOR[n.data?.node?.entity_type]?.hex || DEFAULT_HEX;
              }}
              nodeStrokeWidth={2}
              zoomable
              pannable
              className="!bg-muted/50"
            />
          )}
        </ReactFlow>

        {showLegend && <LineageLegend onClose={() => setShowLegend(false)} />}
      </div>
    </div>
  );
}

// ─── Wrapper with ReactFlowProvider ──────────────────────────────────────

export default function BusinessLineageView(props: BusinessLineageViewProps) {
  return (
    <ReactFlowProvider>
      <BusinessLineageViewInner {...props} />
    </ReactFlowProvider>
  );
}
