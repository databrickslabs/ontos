import React, { useRef, useMemo, useCallback, useEffect, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { forceCollide, forceX, forceY } from 'd3-force';
import { ZoomIn, ZoomOut } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import type {
  GraphData,
  ForceGraphData,
  ForceGraphNode,
  ForceGraphLink,
} from '@/types/graph-explorer';
import { getColorForType, ChangeStatus } from '@/types/graph-explorer';
import { useTranslation } from 'react-i18next';

// ---------------------------------------------------------------------------
// Throttle helper for hover events.
// The first argument being null (mouse-leave) always fires immediately
// so that tooltips/hover states are never left "stuck".
// ---------------------------------------------------------------------------
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function throttle<T extends (...args: any[]) => void>(fn: T, delay: number): T {
  let lastCall = 0;
  return ((...args: Parameters<T>) => {
    if (!args[0]) {
      lastCall = 0;
      fn(...args);
      return;
    }
    const now = Date.now();
    if (now - lastCall >= delay) {
      lastCall = now;
      fn(...args);
    }
  }) as T;
}

// Cached node positions to preserve across data updates (prevents snapping)
interface NodePosition {
  x: number;
  y: number;
  vx?: number;
  vy?: number;
}

// Vibrant status colours (shared with link renderer)
const STATUS_COLORS = {
  NEW: '#22c55e',       // green-500
  MODIFIED: '#f59e0b',  // amber-500
  SELECTED: '#a855f7',  // purple-500
  HOVER: '#3b82f6',     // blue-500
  EDGE_SOURCE: '#22c55e',
} as const;

export interface GraphVisualizationProps {
  data: GraphData;
  showProposed: boolean;
  selectedNodeTypes: string[];
  selectedRelationshipTypes: string[];
  showNodeLabels?: boolean;
  showEdgeLabels?: boolean;
  edgeLength?: number;
  edgeOpacity?: number;
  nodeSize?: number;
  width?: number;
  height?: number;
  onNodeClick?: (nodeId: string) => void;
  onEdgeClick?: (edgeId: string) => void;
  edgeCreateMode?: boolean;
  edgeCreateSourceId?: string | null;
  selectedNodeId?: string | null;
}

export interface GraphVisualizationRef {
  resetView: () => void;
  centerOnNode: (nodeId: string) => void;
  zoomIn: () => void;
  zoomOut: () => void;
}

const GraphVisualization = React.forwardRef<GraphVisualizationRef, GraphVisualizationProps>(
  (
    {
      data,
      showProposed,
      selectedNodeTypes,
      selectedRelationshipTypes,
      showNodeLabels = false,
      showEdgeLabels = false,
      edgeLength = 80,
      edgeOpacity: edgeOpacityProp,
      nodeSize = 6,
      width = 800,
      height = 600,
      onNodeClick,
      onEdgeClick,
      edgeCreateMode = false,
      edgeCreateSourceId = null,
      selectedNodeId = null,
    },
    ref
  ) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- react-force-graph-2d doesn't export a ref type
    const graphRef = useRef<any>(null);
    const containerRef = useRef<HTMLDivElement>(null);

    const [hoveredNode, setHoveredNode] = useState<ForceGraphNode | null>(null);
    const [graphData, setGraphData] = useState<ForceGraphData>({ nodes: [], links: [] });
    const [hasInitialized, setHasInitialized] = useState(false);

    // Position & signature caches
    const nodePositionsRef = useRef<Map<string, NodePosition>>(new Map());
    const prevDataSignatureRef = useRef<string>('');
    const filteredDataSignatureRef = useRef<string>('');

    // Stable refs for rendering params (avoids stale closures in force-graph callbacks)
    const onNodeClickRef = useRef(onNodeClick);
    onNodeClickRef.current = onNodeClick;
    const onEdgeClickRef = useRef(onEdgeClick);
    onEdgeClickRef.current = onEdgeClick;
    const selectedNodeIdRef = useRef(selectedNodeId);
    selectedNodeIdRef.current = selectedNodeId;
    const edgeCreateModeRef = useRef(edgeCreateMode);
    edgeCreateModeRef.current = edgeCreateMode;
    const edgeCreateSourceIdRef = useRef(edgeCreateSourceId);
    edgeCreateSourceIdRef.current = edgeCreateSourceId;
    const hoveredNodeRef = useRef(hoveredNode);
    hoveredNodeRef.current = hoveredNode;
    const showNodeLabelsRef = useRef(showNodeLabels);
    showNodeLabelsRef.current = showNodeLabels;
    const showEdgeLabelsRef = useRef(showEdgeLabels);
    showEdgeLabelsRef.current = showEdgeLabels;
    const nodeSizeRef = useRef(nodeSize);
    nodeSizeRef.current = nodeSize;

    const { t } = useTranslation('graph-explorer');

    const isDarkMode = typeof document !== 'undefined' && document.documentElement.classList.contains('dark');

    // ---------------------------------------------------------------------------
    // Graph density thresholds for progressive quality reduction
    // ---------------------------------------------------------------------------
    const MEDIUM_GRAPH_THRESHOLD = 300;
    const LARGE_GRAPH_THRESHOLD = 5000;
    const totalElements = data.nodes.length + data.edges.length;
    const isLargeGraph = totalElements > LARGE_GRAPH_THRESHOLD;
    const isMediumGraph = totalElements > MEDIUM_GRAPH_THRESHOLD && !isLargeGraph;
    const isDenseGraph = isMediumGraph || isLargeGraph;

    // ---------------------------------------------------------------------------
    // Edge opacity: use prop directly, or auto-compute from visible edge count
    // ---------------------------------------------------------------------------
    const edgeOpacity = useMemo(() => {
      if (edgeOpacityProp != null) return edgeOpacityProp;
      const edgeCount = graphData.links.length;
      if (edgeCount < 50) return 1.0;
      if (edgeCount < 200) return 0.6;
      if (edgeCount < 500) return 0.35;
      if (edgeCount < 1000) return 0.2;
      if (edgeCount < 3000) return 0.12;
      return 0.06;
    }, [edgeOpacityProp, graphData.links.length]);

    // Node degree map for degree-based sizing
    const nodeDegreeMap = useMemo(() => {
      const degreeMap = new Map<string, number>();
      data.edges.forEach((edge) => {
        degreeMap.set(edge.source, (degreeMap.get(edge.source) || 0) + 1);
        degreeMap.set(edge.target, (degreeMap.get(edge.target) || 0) + 1);
      });
      return degreeMap;
    }, [data.edges]);

    // Type-to-cluster-index mapping for cluster force
    const typeClusterMap = useMemo(() => {
      const types = [...new Set(data.nodes.map((n) => n.type))].sort();
      const map = new Map<string, number>();
      types.forEach((type, i) => map.set(type, i));
      return map;
    }, [data.nodes]);

    // ---------------------------------------------------------------------------
    // Node & link colour helpers
    // ---------------------------------------------------------------------------
    const getNodeColor = useCallback(
      (node: ForceGraphNode): string => {
        if (node.status === ChangeStatus.NEW) return STATUS_COLORS.NEW;
        if (node.status === ChangeStatus.MODIFIED) return STATUS_COLORS.MODIFIED;
        return getColorForType(node.type, isDarkMode);
      },
      [isDarkMode],
    );

    const getLinkColor = useCallback(
      (link: ForceGraphLink): string => {
        if (link.status === ChangeStatus.NEW) return STATUS_COLORS.NEW;
        if (link.status === ChangeStatus.MODIFIED) return STATUS_COLORS.MODIFIED;
        return isDarkMode ? '#64748b' : '#94a3b8';
      },
      [isDarkMode],
    );

    // ---------------------------------------------------------------------------
    // Transform + filter data for react-force-graph while preserving positions
    // ---------------------------------------------------------------------------
    useEffect(() => {
      const filteredNodes = data.nodes.filter((node) => {
        if (!showProposed && node.status === ChangeStatus.NEW) return false;
        if (selectedNodeTypes.length > 0 && !selectedNodeTypes.includes(node.type)) return false;
        return true;
      });

      const nodeIds = new Set(filteredNodes.map((n) => n.id));

      const filteredEdges = data.edges.filter((edge) => {
        if (!showProposed && edge.status === ChangeStatus.NEW) return false;
        if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) return false;
        if (
          selectedRelationshipTypes.length > 0 &&
          !selectedRelationshipTypes.includes(edge.relationshipType)
        )
          return false;
        return true;
      });

      // Capture current positions from force-graph internal state
      if (graphRef.current && typeof graphRef.current.graphData === 'function') {
        try {
          const currentNodes = graphRef.current.graphData()?.nodes || [];
          currentNodes.forEach((node: ForceGraphNode) => {
            if (node.id && isFinite(node.x ?? NaN) && isFinite(node.y ?? NaN)) {
              nodePositionsRef.current.set(node.id as string, {
                x: node.x!,
                y: node.y!,
                vx: node.vx,
                vy: node.vy,
              });
            }
          });
        } catch {
          // Graph not fully initialised yet
        }
      }

      // Signature to detect real data changes vs filter changes
      const dataSignature = JSON.stringify({
        nodeIds: data.nodes.map((n) => n.id).sort(),
        edgeIds: data.edges.map((e) => e.id).sort(),
      });
      const isDataChange = dataSignature !== prevDataSignatureRef.current;
      prevDataSignatureRef.current = dataSignature;

      // Degree-based node sizing
      const maxDegree = Math.max(1, ...Array.from(nodeDegreeMap.values()));

      const forceNodes: ForceGraphNode[] = filteredNodes.map((node) => {
        const cachedPosition = nodePositionsRef.current.get(node.id);
        const degree = nodeDegreeMap.get(node.id) || 0;
        const degreeScale = isDenseGraph
          ? 0.5 + (degree / maxDegree) * 1.5
          : 0.8 + (degree / maxDegree) * 0.6;
        const scaledSize = nodeSize * degreeScale;
        const finalSize = node.status === ChangeStatus.NEW ? scaledSize * 1.3 : scaledSize;

        const baseNode: ForceGraphNode = {
          id: node.id,
          name: node.label,
          type: node.type,
          status: node.status,
          properties: node.properties,
          val: finalSize,
          color: getColorForType(node.type, isDarkMode),
        };

        if (cachedPosition) {
          baseNode.x = cachedPosition.x;
          baseNode.y = cachedPosition.y;
        }

        return baseNode;
      });

      const forceLinks: ForceGraphLink[] = filteredEdges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        relationshipType: edge.relationshipType,
        status: edge.status,
        properties: edge.properties,
      }));

      // Only update state if filtered data actually changed
      const filteredDataSignature = JSON.stringify({
        nodes: forceNodes
          .map((n) => ({ id: n.id, name: n.name, type: n.type, status: n.status, properties: n.properties }))
          .sort((a, b) => (a.id as string).localeCompare(b.id as string)),
        links: forceLinks
          .map((l) => ({ id: l.id, relationshipType: l.relationshipType, status: l.status, properties: l.properties }))
          .sort((a, b) => a.id.localeCompare(b.id)),
        nodeSize,
      });

      if (filteredDataSignature !== filteredDataSignatureRef.current) {
        filteredDataSignatureRef.current = filteredDataSignature;
        setGraphData({ nodes: forceNodes, links: forceLinks });

        if (isDataChange && data.nodes.length > 0 && forceNodes.length === 0) {
          setHasInitialized(false);
        }
      }
    }, [data, showProposed, selectedNodeTypes, selectedRelationshipTypes, nodeSize, nodeDegreeMap, isDenseGraph, isDarkMode]);

    // ---------------------------------------------------------------------------
    // Configure d3 forces: collision, charge, clustering
    // ---------------------------------------------------------------------------
    useEffect(() => {
      if (graphRef.current && graphData.nodes.length > 0) {
        const nodeCount = graphData.nodes.length;

        // Link distance scales with density
        const densityFactor = isDenseGraph ? Math.max(1, Math.log10(nodeCount) * 0.8) : 1;
        const scaledEdgeLength = edgeLength * densityFactor;
        graphRef.current.d3Force('link')?.distance(scaledEdgeLength);

        // Charge repulsion scales with sqrt(nodeCount)
        const baseCharge = -(edgeLength * 2.5);
        const chargeStrength = isDenseGraph
          ? Math.min(baseCharge, -(Math.sqrt(nodeCount) * 25 + 100))
          : baseCharge;
        graphRef.current.d3Force('charge')?.strength(chargeStrength);

        // Collision force prevents overlap
        const collisionRadius = isDenseGraph ? nodeSize + 3 : nodeSize + 1;
        graphRef.current.d3Force(
          'collision',
          forceCollide<ForceGraphNode>()
            .radius((d) => (d.val || collisionRadius) + (isDenseGraph ? 4 : 2))
            .strength(isDenseGraph ? 0.9 : 0.7)
            .iterations(isDenseGraph ? 3 : 1),
        );

        // Cluster force: same-type nodes pulled toward angular positions
        if (isDenseGraph && typeClusterMap.size > 1) {
          const numTypes = typeClusterMap.size;
          const clusterRadius = Math.sqrt(nodeCount) * (edgeLength * 0.12);
          const clusterStrength = 0.04;

          graphRef.current.d3Force(
            'clusterX',
            forceX<ForceGraphNode>((d: ForceGraphNode) => {
              const clusterIndex = typeClusterMap.get(d.type) || 0;
              const angle = (clusterIndex / numTypes) * 2 * Math.PI;
              return Math.cos(angle) * clusterRadius;
            }).strength(clusterStrength),
          );
          graphRef.current.d3Force(
            'clusterY',
            forceY<ForceGraphNode>((d: ForceGraphNode) => {
              const clusterIndex = typeClusterMap.get(d.type) || 0;
              const angle = (clusterIndex / numTypes) * 2 * Math.PI;
              return Math.sin(angle) * clusterRadius;
            }).strength(clusterStrength),
          );
        } else {
          graphRef.current.d3Force('clusterX', forceX<ForceGraphNode>(0).strength(0.02));
          graphRef.current.d3Force('clusterY', forceY<ForceGraphNode>(0).strength(0.02));
        }

        graphRef.current.d3ReheatSimulation();
      }
    }, [edgeLength, graphData.nodes.length, graphData.links.length, isDenseGraph, nodeSize, typeClusterMap]);

    // ---------------------------------------------------------------------------
    // Expose imperative methods to parent
    // ---------------------------------------------------------------------------
    React.useImperativeHandle(ref, () => ({
      resetView: () => {
        if (graphRef.current) graphRef.current.zoomToFit(400, 50);
      },
      centerOnNode: (nodeId: string) => {
        if (graphRef.current) {
          const node = graphData.nodes.find((n) => n.id === nodeId);
          if (node && node.x !== undefined && node.y !== undefined) {
            graphRef.current.centerAt(node.x, node.y, 1000);
            graphRef.current.zoom(2, 1000);
          }
        }
      },
      zoomIn: () => {
        if (graphRef.current) {
          const currentZoom = graphRef.current.zoom() || 1;
          graphRef.current.zoom(currentZoom * 1.3, 300);
        }
      },
      zoomOut: () => {
        if (graphRef.current) {
          const currentZoom = graphRef.current.zoom() || 1;
          graphRef.current.zoom(currentZoom / 1.3, 300);
        }
      },
    }));

    // ---------------------------------------------------------------------------
    // Throttled hover handler (null first-arg fires immediately)
    // ---------------------------------------------------------------------------
    const handleNodeHover = useMemo(
      () =>
        throttle((node: ForceGraphNode | null) => {
          setHoveredNode(node);
        }, 50),
      [],
    );

    // Stable click handlers via refs
    const handleNodeClick = useCallback(
      (node: ForceGraphNode) => {
        if (onNodeClickRef.current) onNodeClickRef.current(node.id);
      },
      [], // eslint-disable-line react-hooks/exhaustive-deps
    );

    const handleLinkClick = useCallback(
      (link: ForceGraphLink) => {
        if (onEdgeClickRef.current) onEdgeClickRef.current(link.id);
      },
      [], // eslint-disable-line react-hooks/exhaustive-deps
    );

    // Save position after drag
    const handleNodeDragEnd = useCallback((node: ForceGraphNode) => {
      if (node.id && isFinite(node.x ?? NaN) && isFinite(node.y ?? NaN)) {
        nodePositionsRef.current.set(node.id as string, { x: node.x!, y: node.y! });
      }
    }, []);

    // ---------------------------------------------------------------------------
    // Custom node renderer — full-featured with performance paths
    // ---------------------------------------------------------------------------
    const paintNode = useCallback(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
        if (!isFinite(node.x) || !isFinite(node.y)) return;

        // Reset globalAlpha (edge rendering may have left it low)
        ctx.globalAlpha = 1.0;

        const labelScale = Math.max(1, 1 / globalScale);
        const labelsVisible = globalScale > 0.3;

        const curSelectedNodeId = selectedNodeIdRef.current;
        const curHoveredNode = hoveredNodeRef.current;
        const curEdgeCreateMode = edgeCreateModeRef.current;
        const curEdgeCreateSourceId = edgeCreateSourceIdRef.current;
        const curShowNodeLabels = showNodeLabelsRef.current;
        const curNodeSize = nodeSizeRef.current;

        // LARGE GRAPH FAST PATH: simple circle + border
        if (isLargeGraph) {
          const nodeRadius = node.val || 5;
          const nodeColor = getNodeColor(node);
          ctx.beginPath();
          ctx.arc(node.x, node.y, nodeRadius, 0, 2 * Math.PI);
          ctx.fillStyle = nodeColor;
          ctx.fill();
          ctx.strokeStyle = isDarkMode ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.15)';
          ctx.lineWidth = 0.5;
          ctx.stroke();
          if (node.status === ChangeStatus.NEW) {
            ctx.strokeStyle = STATUS_COLORS.NEW;
            ctx.lineWidth = 2;
            ctx.stroke();
          }
          return;
        }

        const nodeRadius = node.val || curNodeSize;
        const nodeColor = getNodeColor(node);
        const isNew = node.status === ChangeStatus.NEW;
        const isModified = node.status === ChangeStatus.MODIFIED;
        const isSelected = curSelectedNodeId && curSelectedNodeId === node.id;
        const isEdgeCreateSource = curEdgeCreateMode && curEdgeCreateSourceId === node.id;
        const isHovered = !curShowNodeLabels && curHoveredNode && curHoveredNode.id === node.id;
        const isSpecialNode = isHovered || isSelected || isEdgeCreateSource || isNew || isModified;

        // PERF MODE: when labels on, ultra-minimal for non-special nodes
        if (curShowNodeLabels && !isSpecialNode) {
          ctx.beginPath();
          ctx.arc(node.x, node.y, nodeRadius, 0, 2 * Math.PI);
          ctx.fillStyle = nodeColor;
          ctx.fill();
          if (labelsVisible) {
            const fontSize = Math.min(14, 10 * labelScale);
            ctx.fillStyle = isDarkMode ? '#e2e8f0' : '#1e293b';
            ctx.font = `${fontSize}px sans-serif`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'top';
            ctx.fillText(node.name, node.x, node.y + nodeRadius + 2 * labelScale);
          }
          return;
        }

        // FULL RENDERING: glow for special/new nodes
        if (isSpecialNode || isNew) {
          const glowRadius = nodeRadius + (isHovered ? 8 : 6);
          const gradient = ctx.createRadialGradient(node.x, node.y, nodeRadius, node.x, node.y, glowRadius);

          if (isNew) {
            gradient.addColorStop(0, `${STATUS_COLORS.NEW}40`);
            gradient.addColorStop(1, `${STATUS_COLORS.NEW}00`);
          } else if (isModified) {
            gradient.addColorStop(0, `${STATUS_COLORS.MODIFIED}40`);
            gradient.addColorStop(1, `${STATUS_COLORS.MODIFIED}00`);
          } else if (isEdgeCreateSource) {
            gradient.addColorStop(0, `${STATUS_COLORS.EDGE_SOURCE}60`);
            gradient.addColorStop(1, `${STATUS_COLORS.EDGE_SOURCE}00`);
          } else if (isSelected) {
            gradient.addColorStop(0, `${STATUS_COLORS.SELECTED}60`);
            gradient.addColorStop(1, `${STATUS_COLORS.SELECTED}00`);
          } else if (isHovered) {
            gradient.addColorStop(0, `${STATUS_COLORS.HOVER}60`);
            gradient.addColorStop(1, `${STATUS_COLORS.HOVER}00`);
          }

          ctx.beginPath();
          ctx.arc(node.x, node.y, glowRadius, 0, 2 * Math.PI);
          ctx.fillStyle = gradient;
          ctx.fill();
        }

        // Draw node circle
        ctx.beginPath();
        ctx.arc(node.x, node.y, nodeRadius, 0, 2 * Math.PI);
        ctx.fillStyle = nodeColor;
        ctx.fill();

        // Subtle border for non-special nodes
        if (!isNew && !isModified && !isSelected && !isEdgeCreateSource) {
          ctx.strokeStyle = isDarkMode ? 'rgba(255,255,255,0.25)' : 'rgba(0,0,0,0.12)';
          ctx.lineWidth = 0.8;
          ctx.stroke();
        }

        // New node indicator
        if (isNew) {
          ctx.strokeStyle = STATUS_COLORS.NEW;
          ctx.lineWidth = 3;
          ctx.stroke();
        }

        // Modified node indicator (dashed orange)
        if (isModified) {
          ctx.strokeStyle = STATUS_COLORS.MODIFIED;
          ctx.lineWidth = 3;
          ctx.setLineDash([4, 3]);
          ctx.stroke();
          ctx.setLineDash([]);
        }

        // Label for special nodes
        if (isSpecialNode && labelsVisible) {
          const fontSize = Math.min(16, 12 * labelScale);
          ctx.font = `bold ${fontSize}px sans-serif`;
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          const labelY = node.y + nodeRadius + 6 * labelScale;

          const textWidth = ctx.measureText(node.name).width;
          const bgPadX = 4 * labelScale;
          const bgPadY = 4 * labelScale;
          ctx.fillStyle = isDarkMode ? 'rgba(15, 23, 42, 0.9)' : 'rgba(255, 255, 255, 0.9)';
          ctx.fillRect(node.x - textWidth / 2 - bgPadX, labelY - bgPadY, textWidth + bgPadX * 2, bgPadY * 2 + fontSize);

          ctx.fillStyle = isNew
            ? STATUS_COLORS.NEW
            : isModified
              ? STATUS_COLORS.MODIFIED
              : isSelected
                ? STATUS_COLORS.SELECTED
                : STATUS_COLORS.HOVER;
          ctx.fillText(node.name, node.x, labelY + fontSize / 2);
        }

        // Labels for all nodes when showNodeLabels is on (including special)
        if (curShowNodeLabels && isSpecialNode && labelsVisible) {
          const fontSize = Math.min(14, 10 * labelScale);
          ctx.fillStyle = isDarkMode ? '#e2e8f0' : '#1e293b';
          ctx.font = `${fontSize}px sans-serif`;
          ctx.textAlign = 'center';
          ctx.textBaseline = 'top';
          ctx.fillText(node.name, node.x, node.y + nodeRadius + 2 * labelScale);
        }

        // Highlight rings
        if (isHovered) {
          ctx.beginPath();
          ctx.arc(node.x, node.y, nodeRadius + 3, 0, 2 * Math.PI);
          ctx.strokeStyle = STATUS_COLORS.HOVER;
          ctx.lineWidth = 3;
          ctx.stroke();
        }
        if (isSelected) {
          ctx.beginPath();
          ctx.arc(node.x, node.y, nodeRadius + 4, 0, 2 * Math.PI);
          ctx.strokeStyle = STATUS_COLORS.SELECTED;
          ctx.lineWidth = 3;
          ctx.stroke();
        }
        if (isEdgeCreateSource) {
          ctx.beginPath();
          ctx.arc(node.x, node.y, nodeRadius + 5, 0, 2 * Math.PI);
          ctx.strokeStyle = STATUS_COLORS.EDGE_SOURCE;
          ctx.lineWidth = 4;
          ctx.stroke();
        }
      },
      [getNodeColor, isDarkMode, isLargeGraph],
    );

    // ---------------------------------------------------------------------------
    // Custom link renderer — performance-aware with opacity support
    // ---------------------------------------------------------------------------
    const paintLink = useCallback(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (link: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
        const start = link.source;
        const end = link.target;
        if (!isFinite(start.x) || !isFinite(start.y) || !isFinite(end.x) || !isFinite(end.y)) return;

        const isNew = link.status === ChangeStatus.NEW;
        const isModified = link.status === ChangeStatus.MODIFIED;
        const linkColor = getLinkColor(link);
        const labelScale = Math.max(1, 1 / globalScale);
        const labelsVisible = globalScale > 0.3;
        const curShowEdgeLabels = showEdgeLabelsRef.current;

        // Dynamic opacity for dense graphs
        ctx.globalAlpha = isNew || isModified ? Math.max(edgeOpacity, 0.5) : edgeOpacity;

        // LARGE GRAPH: simple lines only
        if (isLargeGraph) {
          ctx.beginPath();
          ctx.moveTo(start.x, start.y);
          ctx.lineTo(end.x, end.y);
          ctx.strokeStyle = isNew ? STATUS_COLORS.NEW : linkColor;
          ctx.lineWidth = isNew ? 1.5 : 0.5;
          ctx.stroke();
          ctx.globalAlpha = 1.0;
          return;
        }

        const angle = Math.atan2(end.y - start.y, end.x - start.x);
        const perpAngle = angle + Math.PI / 2;
        const labelOffset = 10 * labelScale;
        const baseWidth = isDenseGraph ? 1 : 2;

        // PERF MODE: when edge labels on, minimal for non-new/modified
        if (curShowEdgeLabels && !isNew && !isModified) {
          ctx.beginPath();
          ctx.moveTo(start.x, start.y);
          ctx.lineTo(end.x, end.y);
          ctx.strokeStyle = linkColor;
          ctx.lineWidth = isDenseGraph ? 0.5 : 1;
          ctx.stroke();

          if (link.relationshipType && labelsVisible) {
            ctx.globalAlpha = 1.0;
            const midX = (start.x + end.x) / 2;
            const midY = (start.y + end.y) / 2;
            const labelX = midX + Math.cos(perpAngle) * labelOffset;
            const labelY = midY + Math.sin(perpAngle) * labelOffset;
            const fontSize = Math.min(12, 9 * labelScale);
            ctx.font = `${fontSize}px sans-serif`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            const textWidth = ctx.measureText(link.relationshipType).width;
            const padding = 3 * labelScale;
            ctx.fillStyle = isDarkMode ? 'rgba(15, 23, 42, 0.85)' : 'rgba(255, 255, 255, 0.9)';
            ctx.fillRect(labelX - textWidth / 2 - padding, labelY - fontSize / 2 - 1, textWidth + padding * 2, fontSize + 2);
            ctx.fillStyle = isDarkMode ? '#94a3b8' : '#64748b';
            ctx.fillText(link.relationshipType, labelX, labelY);
          }
          ctx.globalAlpha = 1.0;
          return;
        }

        // FULL RENDERING
        ctx.beginPath();
        ctx.moveTo(start.x, start.y);
        ctx.lineTo(end.x, end.y);

        if (isNew) {
          ctx.strokeStyle = STATUS_COLORS.NEW;
          ctx.lineWidth = baseWidth + 1;
          ctx.setLineDash([8, 4]);
        } else if (isModified) {
          ctx.strokeStyle = STATUS_COLORS.MODIFIED;
          ctx.lineWidth = baseWidth + 1;
          ctx.setLineDash([6, 3]);
        } else {
          ctx.strokeStyle = linkColor;
          ctx.lineWidth = baseWidth;
          ctx.setLineDash([]);
        }
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.globalAlpha = 1.0;

        // Draw label for new/modified links when labels are on
        if (curShowEdgeLabels && (isNew || isModified) && link.relationshipType && labelsVisible) {
          const midX = (start.x + end.x) / 2;
          const midY = (start.y + end.y) / 2;
          const labelX = midX + Math.cos(perpAngle) * labelOffset;
          const labelY = midY + Math.sin(perpAngle) * labelOffset;
          const fontSize = Math.min(14, 10 * labelScale);
          ctx.font = `bold ${fontSize}px sans-serif`;
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          const textWidth = ctx.measureText(link.relationshipType).width;
          const padding = 4 * labelScale;
          ctx.fillStyle = isDarkMode ? 'rgba(15, 23, 42, 0.9)' : 'rgba(255, 255, 255, 0.95)';
          ctx.fillRect(labelX - textWidth / 2 - padding, labelY - fontSize / 2 - 2, textWidth + padding * 2, fontSize + 4);
          ctx.strokeStyle = isModified ? STATUS_COLORS.MODIFIED : STATUS_COLORS.NEW;
          ctx.lineWidth = 1;
          ctx.strokeRect(labelX - textWidth / 2 - padding, labelY - fontSize / 2 - 2, textWidth + padding * 2, fontSize + 4);
          ctx.fillStyle = isModified ? STATUS_COLORS.MODIFIED : STATUS_COLORS.NEW;
          ctx.fillText(link.relationshipType, labelX, labelY);
        }
        ctx.globalAlpha = 1.0;
      },
      [getLinkColor, isDarkMode, isLargeGraph, isDenseGraph, edgeOpacity],
    );

    return (
      <div ref={containerRef} className={cn('relative w-full h-full', edgeCreateMode && 'cursor-crosshair')} style={{ width, height }}>
        {/* Dot grid background */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            backgroundImage: `radial-gradient(circle, ${isDarkMode ? 'rgba(0,102,255,0.1)' : 'rgba(0,102,255,0.05)'} 1px, transparent 1px)`,
            backgroundSize: '20px 20px',
            opacity: 0.3,
          }}
        />
        <ForceGraph2D
          ref={graphRef}
          graphData={graphData}
          width={width}
          height={height}
          backgroundColor="transparent"
          nodeCanvasObject={paintNode}
          linkCanvasObject={paintLink}
          onNodeHover={isLargeGraph || (showNodeLabels && showEdgeLabels) ? undefined : handleNodeHover}
          onNodeClick={handleNodeClick}
          onNodeDragEnd={handleNodeDragEnd}
          onLinkClick={isLargeGraph ? undefined : handleLinkClick}
          enableNodeDrag={!isLargeGraph}
          enableZoomInteraction={true}
          enablePanInteraction={true}
          cooldownTicks={isLargeGraph ? 50 : isDenseGraph ? 100 : 50}
          warmupTicks={isLargeGraph ? 30 : isDenseGraph ? 80 : showNodeLabels || showEdgeLabels ? 100 : 0}
          onEngineStop={() => {
            // Save final positions
            if (graphRef.current && typeof graphRef.current.graphData === 'function') {
              try {
                const currentNodes = graphRef.current.graphData()?.nodes || [];
                currentNodes.forEach((node: ForceGraphNode) => {
                  if (node.id && isFinite(node.x ?? NaN) && isFinite(node.y ?? NaN)) {
                    nodePositionsRef.current.set(node.id as string, { x: node.x!, y: node.y! });
                  }
                });
              } catch {
                // not ready
              }
            }
            // Zoom to fit only on initial load
            if (!hasInitialized && graphData.nodes.length > 0) {
              graphRef.current?.zoomToFit(400, 50);
              setHasInitialized(true);
            }
          }}
          d3AlphaDecay={isLargeGraph ? 0.05 : isDenseGraph ? 0.02 : showNodeLabels || showEdgeLabels ? 0.05 : 0.02}
          d3VelocityDecay={isLargeGraph ? 0.4 : isDenseGraph ? 0.3 : showNodeLabels || showEdgeLabels ? 0.5 : 0.3}
        />

        {/* Performance mode indicator */}
        {isLargeGraph && (
          <Badge
            variant="outline"
            className="absolute top-2.5 left-2.5 z-10 bg-background/80 backdrop-blur-sm text-amber-500 border-amber-500"
          >
            Performance mode ({data.nodes.length.toLocaleString()} nodes, {data.edges.length.toLocaleString()} edges)
          </Badge>
        )}

        {/* Zoom Controls */}
        <div className="absolute bottom-4 right-4 flex flex-col gap-2 z-10">
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="outline"
                  size="icon"
                  onClick={() => {
                    if (graphRef.current) {
                      const z = graphRef.current.zoom() || 1;
                      graphRef.current.zoom(z * 1.3, 300);
                    }
                  }}
                  className="bg-background/80 backdrop-blur-sm"
                >
                  <ZoomIn className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>{t('tooltip.zoomIn')}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="outline"
                  size="icon"
                  onClick={() => {
                    if (graphRef.current) {
                      const z = graphRef.current.zoom() || 1;
                      graphRef.current.zoom(z / 1.3, 300);
                    }
                  }}
                  className="bg-background/80 backdrop-blur-sm"
                >
                  <ZoomOut className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>{t('tooltip.zoomOut')}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>

        {/* Hover Tooltip */}
        {hoveredNode && (
          <Card className="absolute top-4 right-16 z-50 min-w-[200px] max-w-[300px] bg-background/95 backdrop-blur-sm pointer-events-none">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold">{hoveredNode.name}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-xs">
              <div className="flex items-center gap-2">
                <span className="font-medium">{t('tooltip.type')}:</span>
                <span
                  className="rounded px-2 py-0.5 text-xs font-medium"
                  style={{
                    backgroundColor: `${hoveredNode.color}20`,
                    color: hoveredNode.color,
                  }}
                >
                  {hoveredNode.type}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="font-medium">{t('tooltip.status')}:</span>
                <span
                  className={cn(
                    'rounded px-2 py-0.5 text-xs font-medium',
                    hoveredNode.status === ChangeStatus.NEW && 'bg-green-500/20 text-green-500',
                    hoveredNode.status === ChangeStatus.EXISTING && 'bg-gray-500/20 text-gray-500',
                    hoveredNode.status === ChangeStatus.MODIFIED && 'bg-yellow-500/20 text-yellow-500',
                  )}
                >
                  {hoveredNode.status.toUpperCase()}
                </span>
              </div>
              {Object.keys(hoveredNode.properties).length > 0 && (
                <div className="mt-2 space-y-1">
                  <span className="font-medium">{t('tooltip.properties')}:</span>
                  <div className="ml-2 space-y-0.5">
                    {Object.entries(hoveredNode.properties).map(([key, value]) => (
                      <div key={key} className="text-xs">
                        <span className="font-medium">{key}:</span> {String(value)}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    );
  },
);

GraphVisualization.displayName = 'GraphVisualization';

export default GraphVisualization;
