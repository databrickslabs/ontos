/**
 * ERD-style column lineage visualization — Collibra/Informatica inspired.
 *
 * Entities as ERD cards in vertical columns, flowing left-to-right. When the
 * backend tags nodes with a model layer, columns are lanes
 * (Business → Delivery → Logical → Physical → Other) instead of hop distance.
 * Containment relationships collapse children inside parent cards.
 * Edges route to specific child-row handles for column-level lineage.
 * Infrastructure (System) shown as badges, not nodes.
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import type { CSSProperties } from 'react';
import ReactFlow, {
  Node,
  Edge,
  MarkerType,
  useNodesState,
  useEdgesState,
  MiniMap,
  Panel,
  useReactFlow,
  ReactFlowProvider,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Loader2, AlertCircle, Network, Maximize, ZoomIn, ZoomOut, Info } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

import type { LineageGraph } from '@/types/ontology-schema';
import { layoutLineageGraph, DEFAULT_CONFIG } from './layout';
import type { LayoutConfig, LayoutResult, LineageDetail } from './layout';
import { computeHighlight, filterGraph, focusGraph, DEFAULT_VIEW_OPTIONS } from './highlight';
import type { Highlight, ViewOptions } from './highlight';
import { useLineagePreferencesStore } from '@/stores/lineage-preferences-store';
import { TYPE_COLOR, DEFAULT_HEX, getEntityRoute, categorizeEdge } from './constants';
import type { LineageDirection } from './lineage-toolbar';
import LineageToolbar from './lineage-toolbar';
import LineageLegend from './lineage-legend';
import LineageEntityCard from './lineage-entity-card';
import type { GroupCardData } from './lineage-entity-card';
import LineageColumnHeader from './lineage-column-header';
import type { ColumnHeaderData } from './lineage-column-header';
import LineageLaneBand from './lineage-lane-band';
import type { LaneBandData } from './lineage-lane-band';

// ─── Custom node types ──────────────────────────────────────────────────

const nodeTypes = {
  lineageCard: LineageEntityCard,
  columnHeader: LineageColumnHeader,
  laneBand: LineageLaneBand,
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
    case 'implementation':
      return {
        style: {
          stroke: isDark ? 'rgba(251,113,133,0.75)' : 'rgba(225,29,72,0.6)',
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
  direction: pinnedDirection,
  maxDepth: pinnedMaxDepth,
  showToolbar = true,
  showMinimap = true,
}: BusinessLineageViewProps) {
  const navigate = useNavigate();
  const { t } = useTranslation(['data-catalog', 'common']);
  const { fitView, zoomIn, zoomOut } = useReactFlow();

  // Preferences persist (localStorage) for the interactive view. Embedded views
  // that pin direction/depth or hide the toolbar keep local state instead.
  const persistent = showToolbar && pinnedDirection === undefined && pinnedMaxDepth === undefined;
  const prefs = useLineagePreferencesStore();
  const [localDirection, setLocalDirection] = useState<LineageDirection>(pinnedDirection ?? 'both');
  const [localMaxDepth, setLocalMaxDepth] = useState(pinnedMaxDepth ?? 2);
  const [localDetail, setLocalDetail] = useState<LineageDetail>('structure');
  const [localViewOptions, setLocalViewOptions] = useState<ViewOptions>(DEFAULT_VIEW_OPTIONS);
  const [localFocusMode, setLocalFocusMode] = useState(true);

  const direction = persistent ? prefs.direction : localDirection;
  const setDirection = persistent ? prefs.setDirection : setLocalDirection;
  const maxDepth = persistent ? prefs.maxDepth : localMaxDepth;
  const setMaxDepth = persistent ? prefs.setMaxDepth : setLocalMaxDepth;
  const detail = persistent ? prefs.detail : localDetail;
  const setDetail = persistent ? prefs.setDetail : setLocalDetail;
  const viewOptions = persistent ? prefs.viewOptions : localViewOptions;
  const setViewOptions = persistent ? prefs.setViewOptions : setLocalViewOptions;
  const focusMode = persistent ? prefs.focusMode : localFocusMode;
  const setFocusMode = persistent ? prefs.setFocusMode : setLocalFocusMode;
  const [graph, setGraph] = useState<LineageGraph | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showLegend, setShowLegend] = useState(false);
  const [isDark, setIsDark] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hoveredEdgeId, setHoveredEdgeId] = useState<string | null>(null);

  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  const layoutConfig = useMemo<LayoutConfig>(() => ({ ...DEFAULT_CONFIG, detail }), [detail]);

  // Dark mode detection
  useEffect(() => {
    const check = () => setIsDark(document.documentElement.classList.contains('dark'));
    check();
    const obs = new MutationObserver(check);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => obs.disconnect();
  }, []);

  // Navigation handler
  const handleNodeClick = useCallback((eType: string, eId: string, contextId?: string | null) => {
    navigate(getEntityRoute(eType, eId, contextId));
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

  // Filter → layout (pure); selection only re-styles, it never re-lays out
  const filteredGraph = useMemo(() => (graph ? filterGraph(graph, viewOptions) : null), [graph, viewOptions]);
  const layout = useMemo<LayoutResult | null>(
    () => (filteredGraph ? layoutLineageGraph(filteredGraph, layoutConfig) : null),
    [filteredGraph, layoutConfig],
  );
  const highlight = useMemo<Highlight | null>(() => {
    if (!layout || !selectedId || !filteredGraph?.nodes.some((n) => n.id === selectedId)) return null;
    const layers = new Map(filteredGraph.nodes.map((n) => [n.id, n.layer]));
    return computeHighlight(selectedId, layout.flowEdges, layout.parentOf, layout.childrenOf, (id) => layers.get(id));
  }, [layout, selectedId, filteredGraph]);
  const selectedNode = useMemo(
    () => (highlight && selectedId ? filteredGraph?.nodes.find((n) => n.id === selectedId) ?? null : null),
    [highlight, selectedId, filteredGraph],
  );

  // Focus re-lays out only the path; dim mode keeps the full layout
  const renderLayout = useMemo<LayoutResult | null>(() => {
    if (!layout || !filteredGraph || !highlight || !focusMode) return layout;
    // Rows on the path always show, whatever the detail level
    return layoutLineageGraph(focusGraph(filteredGraph, highlight), { ...layoutConfig, alwaysShow: highlight.nodes });
  }, [layout, filteredGraph, highlight, focusMode, layoutConfig]);

  // A new graph (entity, direction, breadth) starts without a selection
  useEffect(() => { setSelectedId(null); }, [graph]);

  const handleSelect = useCallback((nodeId: string) => {
    setSelectedId((prev) => (prev === nodeId ? null : nodeId));
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setSelectedId(null); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // Build React Flow nodes when the rendered layout changes
  useEffect(() => {
    if (!graph || !renderLayout) {
      setNodes((prev) => prev.length ? [] : prev);
      setEdges((prev) => prev.length ? [] : prev);
      return;
    }

    const centerId = `${graph.center_entity_type}:${graph.center_entity_id}`;
    const rfNodes: Node[] = [];

    // Lane bands (layer mode) or hop-distance column headers (legacy graphs)
    renderLayout.lanes.forEach((lane, i) => {
      rfNodes.push({
        id: `lane-${lane.layer}`,
        type: 'laneBand',
        position: { x: lane.x, y: -8 },
        data: {
          label: t(`common:businessLineage.layers.${lane.layer}`, { defaultValue: lane.layer }),
          width: lane.width,
          height: lane.height,
          shaded: i % 2 === 0,
        } satisfies LaneBandData,
        draggable: false,
        selectable: false,
        connectable: false,
        focusable: false,
        zIndex: -1,
        style: { pointerEvents: 'none' },
      });
    });
    if (renderLayout.lanes.length === 0) {
      for (const col of renderLayout.columns) {
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
    }

    // ERD-style group cards
    for (const g of renderLayout.groups) {
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
          onSelect: handleSelect,
          selectedId: null,
          highlight: null,
        } satisfies GroupCardData,
        draggable: true,
        selectable: false,
        connectable: false,
      });
    }

    setNodes(rfNodes);
    // Fit once React Flow has measured the new nodes (rAF alone fits the old bounds)
    const timer = window.setTimeout(() => fitView({ padding: 0.08, duration: 300 }), 80);
    return () => window.clearTimeout(timer);
  }, [graph, renderLayout, handleNodeClick, handleSelect, setNodes, setEdges, fitView, layoutConfig, t]);

  // Selection → card/row dimming (keeps dragged positions)
  useEffect(() => {
    setNodes((prev) => prev.map((n) => (
      n.type === 'lineageCard'
        ? {
          ...n,
          data: {
            ...n.data,
            selectedId: highlight ? selectedId : null,
            // In focus mode everything shown is on the path — no dimming needed
            highlight: highlight && !focusMode ? highlight.nodes : null,
          },
        }
        : n
    )));
  }, [highlight, selectedId, focusMode, renderLayout, setNodes]);

  // Edges: style by category; selection highlights the path and fades the rest
  useEffect(() => {
    if (!renderLayout) return;
    const rfEdges: Edge[] = renderLayout.edges.map((le) => {
      const edgeStyle = getEdgeStyle(le.edge.relationship_type, isDark);
      const baseStyle = (edgeStyle.style || {}) as CSSProperties;
      const strokeColor = (baseStyle.stroke as string) || '#64748b';
      const onPath = !!highlight && le.memberKeys.some((k) => highlight.edges.has(k));
      const faded = !!highlight && !onPath;
      // Labels on hover (or always via View → Edge labels) — never a wall of text
      const showLabel = hoveredEdgeId === le.id || (viewOptions.showLabels && !faded);
      const marker = { type: MarkerType.ArrowClosed, width: 10, height: 10, color: strokeColor };

      return {
        id: le.id,
        // Drawn in flow direction (left → right); the arrow keeps the stored
        // semantics, so reversed edges (e.g. depends on) point back upstream
        source: le.sourceRootId,
        target: le.targetRootId,
        sourceHandle: le.sourceHandle || 'parent',
        targetHandle: le.targetHandle || 'parent',
        type: 'smoothstep',
        label: showLabel ? (le.edge.label || undefined) : undefined,
        labelStyle: { fontSize: 10, fill: isDark ? '#94a3b8' : '#64748b' },
        labelBgStyle: {
          fill: isDark ? '#1e293b' : '#ffffff',
          fillOpacity: 0.85,
        },
        labelBgPadding: [6, 3] as [number, number],
        ...(le.reversed ? { markerStart: marker } : { markerEnd: marker }),
        // Edges stay behind cards (no z-raise) so crossings never cover content
        interactionWidth: 14,
        style: {
          ...baseStyle,
          strokeWidth: onPath && !focusMode ? Number(baseStyle.strokeWidth || 1) + 1 : baseStyle.strokeWidth,
          opacity: faded ? 0.08 : 1,
          transition: 'opacity 150ms',
        },
      };
    });
    setEdges(rfEdges);
  }, [renderLayout, highlight, focusMode, hoveredEdgeId, isDark, viewOptions.showLabels, setEdges]);

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
          detail={detail}
          onDetailChange={setDetail}
          nodeCount={filteredGraph?.nodes.length ?? graph.nodes.length}
          edgeCount={filteredGraph?.edges.length ?? graph.edges.length}
          viewOptions={viewOptions}
          onViewOptionsChange={setViewOptions}
          selection={selectedNode && highlight ? {
            name: selectedNode.name,
            upstream: highlight.upstreamCount,
            downstream: highlight.downstreamCount,
          } : null}
          onClearSelection={() => setSelectedId(null)}
          focusMode={focusMode}
          onFocusModeChange={setFocusMode}
        />
      )}

      <div className="flex-1 relative min-h-0">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onPaneClick={() => setSelectedId(null)}
          onEdgeMouseEnter={(_, e) => setHoveredEdgeId(e.id)}
          onEdgeMouseLeave={() => setHoveredEdgeId(null)}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.12 }}
          minZoom={0.15}
          maxZoom={2}
          proOptions={{ hideAttribution: true }}
          className="bg-background"
        >
          <Panel position="top-right" className="!m-2 flex items-center gap-0.5 rounded-md border bg-background/90 p-0.5 shadow-sm">
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => zoomIn({ duration: 200 })} aria-label={t('data-catalog:lineage.toolbar.zoomIn')} title={t('data-catalog:lineage.toolbar.zoomIn')}>
              <ZoomIn className="h-3.5 w-3.5" />
            </Button>
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => zoomOut({ duration: 200 })} aria-label={t('data-catalog:lineage.toolbar.zoomOut')} title={t('data-catalog:lineage.toolbar.zoomOut')}>
              <ZoomOut className="h-3.5 w-3.5" />
            </Button>
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => fitView({ padding: 0.08, duration: 300 })} aria-label={t('data-catalog:lineage.toolbar.fitView')} title={t('data-catalog:lineage.toolbar.fitView')}>
              <Maximize className="h-3.5 w-3.5" />
            </Button>
            <Button variant="ghost" size="icon" className={cn('h-7 w-7', showLegend && 'bg-accent')} onClick={() => setShowLegend((p) => !p)} aria-label={t('common:labels.legend')} title={t('common:labels.legend')}>
              <Info className="h-3.5 w-3.5" />
            </Button>
          </Panel>

          {showMinimap && viewOptions.showMinimap && (
            <MiniMap
              nodeColor={(n) => {
                if (n.type === 'columnHeader') return 'transparent';
                return TYPE_COLOR[n.data?.node?.entity_type]?.hex || DEFAULT_HEX;
              }}
              nodeStrokeWidth={2}
              zoomable
              pannable
              style={{ width: 150, height: 90 }}
              className="!bg-muted/50"
            />
          )}
        </ReactFlow>

        {!highlight && (
          <div className="pointer-events-none absolute bottom-2 left-3 text-[11px] text-muted-foreground bg-background/80 rounded px-1.5 py-0.5">
            {t('data-catalog:lineage.toolbar.selectHint')}
          </div>
        )}

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
