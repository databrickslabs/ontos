import React, { useRef, useMemo, useCallback, useEffect, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { ZoomIn, ZoomOut } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
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

export interface GraphVisualizationProps {
  data: GraphData;
  showProposed: boolean;
  selectedNodeTypes: string[];
  selectedRelationshipTypes: string[];
  showNodeLabels?: boolean;
  showEdgeLabels?: boolean;
  edgeLength?: number;
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
    const nodePositionsRef = useRef<Map<string, { x: number; y: number }>>(new Map());
    const dataSignatureRef = useRef<string>('');
    const hasInitialFitRef = useRef(false);
    const hoverTimeoutRef = useRef<NodeJS.Timeout | null>(null);
    const [hoveredNode, setHoveredNode] = useState<ForceGraphNode | null>(null);
    const [mousePosition, setMousePosition] = useState<{ x: number; y: number } | null>(null);
    const containerRef = useRef<HTMLDivElement>(null);

    // Use refs for callbacks to avoid stale closures in react-force-graph-2d.
    // The library may not synchronously update event handlers when props change,
    // so we always call through refs that hold the latest callbacks.
    const onNodeClickRef = useRef(onNodeClick);
    onNodeClickRef.current = onNodeClick;
    const onEdgeClickRef = useRef(onEdgeClick);
    onEdgeClickRef.current = onEdgeClick;

    // Stable refs for rendering params that change frequently
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

    // Detect dark mode
    const isDarkMode = document.documentElement.classList.contains('dark');

    // Generate data signature for change detection
    const currentDataSignature = useMemo(
      () => JSON.stringify({ nodes: data.nodes.map((n) => n.id).sort(), edges: data.edges.map((e) => e.id).sort() }),
      [data]
    );

    // Transform and filter graph data
    const forceGraphData = useMemo<ForceGraphData>(() => {
      // Filter nodes
      const filteredNodes = data.nodes.filter((node) => {
        if (selectedNodeTypes.length > 0 && !selectedNodeTypes.includes(node.type)) {
          return false;
        }
        if (!showProposed && node.status === ChangeStatus.NEW) {
          return false;
        }
        return true;
      });

      // Filter edges
      const filteredEdges = data.edges.filter((edge) => {
        if (selectedRelationshipTypes.length > 0 && !selectedRelationshipTypes.includes(edge.relationshipType)) {
          return false;
        }
        if (!showProposed && edge.status === ChangeStatus.NEW) {
          return false;
        }
        // Only include edges where both source and target nodes are in filteredNodes
        const sourceExists = filteredNodes.some((n) => n.id === edge.source);
        const targetExists = filteredNodes.some((n) => n.id === edge.target);
        return sourceExists && targetExists;
      });

      // Transform to force graph format (positions applied via useEffect below)
      const nodes: ForceGraphNode[] = filteredNodes.map((node) => ({
        id: node.id,
        name: node.label,
        type: node.type,
        status: node.status,
        properties: node.properties,
        val: nodeSize,
        color: getColorForType(node.type, isDarkMode),
      }));

      const links: ForceGraphLink[] = filteredEdges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        relationshipType: edge.relationshipType,
        status: edge.status,
        properties: edge.properties,
        color: isDarkMode ? '#64748b' : '#94a3b8',
      }));

      return { nodes, links };
    }, [data, selectedNodeTypes, selectedRelationshipTypes, showProposed, nodeSize, isDarkMode]);

    // Apply cached positions from ref (outside of render/memo)
    useEffect(() => {
      forceGraphData.nodes.forEach((node) => {
        const cached = nodePositionsRef.current.get(node.id);
        if (cached) {
          node.x = cached.x;
          node.y = cached.y;
        }
      });
    }, [forceGraphData]);

    // Update data signature when data changes
    useEffect(() => {
      if (currentDataSignature !== dataSignatureRef.current) {
        dataSignatureRef.current = currentDataSignature;
      }
    }, [currentDataSignature]);

    // Expose ref methods
    React.useImperativeHandle(ref, () => ({
      resetView: () => {
        if (graphRef.current) {
          graphRef.current.zoomToFit(400, 20);
        }
      },
      centerOnNode: (nodeId: string) => {
        if (graphRef.current) {
          const node = forceGraphData.nodes.find((n) => n.id === nodeId);
          if (node && node.x !== undefined && node.y !== undefined) {
            graphRef.current.centerAt(node.x, node.y, 1000);
            graphRef.current.zoom(2, 1000);
          }
        }
      },
      zoomIn: () => {
        if (graphRef.current) {
          const currentZoom = graphRef.current.zoom() || 1;
          graphRef.current.zoom(currentZoom * 1.2, 300);
        }
      },
      zoomOut: () => {
        if (graphRef.current) {
          const currentZoom = graphRef.current.zoom() || 1;
          graphRef.current.zoom(currentZoom / 1.2, 300);
        }
      },
    }));

    // Zoom to fit on initial load only
    useEffect(() => {
      if (!hasInitialFitRef.current && forceGraphData.nodes.length > 0 && graphRef.current) {
        hasInitialFitRef.current = true;
        setTimeout(() => {
          if (graphRef.current) {
            graphRef.current.zoomToFit(400, 20);
          }
        }, 100);
      }
    }, [forceGraphData.nodes.length]);

    // Handle node click — uses ref to always call the latest callback,
    // preventing stale closure issues when edge-create mode changes.
    const handleNodeClick = useCallback(
      (node: ForceGraphNode) => {
        if (onNodeClickRef.current) {
          onNodeClickRef.current(node.id);
        }
      },
      [] // eslint-disable-line react-hooks/exhaustive-deps -- intentionally stable via ref
    );

    // Handle edge click — same ref pattern
    const handleLinkClick = useCallback(
      (link: ForceGraphLink) => {
        if (onEdgeClickRef.current) {
          onEdgeClickRef.current(link.id);
        }
      },
      [] // eslint-disable-line react-hooks/exhaustive-deps -- intentionally stable via ref
    );

    // Handle node drag end - save position
    const handleNodeDragEnd = useCallback((node: ForceGraphNode) => {
      if (node.x !== undefined && node.y !== undefined) {
        nodePositionsRef.current.set(node.id, { x: node.x, y: node.y });
      }
    }, []);

    // Track mouse position
    const handleMouseMove = useCallback((event: MouseEvent) => {
      if (containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect();
        setMousePosition({
          x: event.clientX - rect.left,
          y: event.clientY - rect.top,
        });
      }
    }, []);

    // Throttled hover handler
    const handleNodeHover = useCallback(
      (node: ForceGraphNode | null) => {
        if (hoverTimeoutRef.current) {
          clearTimeout(hoverTimeoutRef.current);
        }

        hoverTimeoutRef.current = setTimeout(() => {
          setHoveredNode(node);
          if (!node) {
            setMousePosition(null);
          }
        }, 50);
      },
      []
    );

    // Set up mouse tracking
    useEffect(() => {
      const container = containerRef.current;
      if (container) {
        container.addEventListener('mousemove', handleMouseMove);
        return () => {
          container.removeEventListener('mousemove', handleMouseMove);
        };
      }
    }, [handleMouseMove]);

    // Custom node renderer — reads interactive state from refs to prevent
    // stale closure issues and unnecessary re-creation of this callback.
    // Node fill color always reflects its type; interactive states are shown
    // via a surrounding ring so the type color is never lost.
    const nodeCanvasObject = useCallback(
      (node: ForceGraphNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
        const curSelectedNodeId = selectedNodeIdRef.current;
        const curHoveredNode = hoveredNodeRef.current;
        const curEdgeCreateMode = edgeCreateModeRef.current;
        const curEdgeCreateSourceId = edgeCreateSourceIdRef.current;
        const curNodeSize = nodeSizeRef.current;
        const curShowNodeLabels = showNodeLabelsRef.current;

        const isSelected = curSelectedNodeId === node.id;
        const isHovered = curHoveredNode?.id === node.id;
        const isEdgeCreateSource = curEdgeCreateMode && curEdgeCreateSourceId === node.id;
        const isNew = node.status === ChangeStatus.NEW;

        // Always use the type-based fill color
        const typeColor = node.color || getColorForType(node.type, isDarkMode);

        const x = node.x ?? 0;
        const y = node.y ?? 0;

        // Draw outer ring for interactive states (drawn first, behind the node)
        if (isSelected || isHovered || isEdgeCreateSource) {
          const ringColor = isSelected
            ? '#a855f7'  // purple-500 for selection
            : isEdgeCreateSource
              ? '#22c55e'  // green-500 for edge source
              : '#3b82f6'; // blue-500 for hover
          ctx.fillStyle = `${ringColor}30`; // translucent glow
          ctx.beginPath();
          ctx.arc(x, y, curNodeSize + 5, 0, 2 * Math.PI);
          ctx.fill();
          ctx.strokeStyle = ringColor;
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.arc(x, y, curNodeSize + 3, 0, 2 * Math.PI);
          ctx.stroke();
        }

        // Draw dashed ring for new (unsaved) nodes
        if (isNew && !isSelected && !isHovered && !isEdgeCreateSource) {
          ctx.strokeStyle = '#22c55e'; // green-500
          ctx.lineWidth = 1.5;
          ctx.setLineDash([3, 3]);
          ctx.beginPath();
          ctx.arc(x, y, curNodeSize + 3, 0, 2 * Math.PI);
          ctx.stroke();
          ctx.setLineDash([]);
        }

        // Draw node circle — always uses the type color
        ctx.fillStyle = typeColor;
        ctx.beginPath();
        ctx.arc(x, y, curNodeSize, 0, 2 * Math.PI);
        ctx.fill();

        // Draw label if enabled
        if (curShowNodeLabels && globalScale > 0.5) {
          ctx.fillStyle = isDarkMode ? '#e2e8f0' : '#1e293b';
          ctx.font = `${12 / globalScale}px sans-serif`;
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(node.name, x, y + curNodeSize + 12 / globalScale);
        }
      },
      [isDarkMode] // Only depends on dark mode; interactive state read from refs
    );

    // Custom link renderer — reads showEdgeLabels from ref for stability.
    // Uses `== null` instead of falsy checks to correctly handle 0 coordinates.
    const linkCanvasObject = useCallback(
      (link: ForceGraphLink, ctx: CanvasRenderingContext2D, globalScale: number) => {
        // Handle both string IDs and node objects (d3-force replaces IDs with objects)
        const sourceNode =
          typeof link.source === 'string'
            ? forceGraphData.nodes.find((n) => n.id === link.source)
            : (link.source as ForceGraphNode);
        const targetNode =
          typeof link.target === 'string'
            ? forceGraphData.nodes.find((n) => n.id === link.target)
            : (link.target as ForceGraphNode);

        if (!sourceNode || !targetNode) return;
        // Use == null to allow 0 coordinates (which are valid positions)
        if (sourceNode.x == null || sourceNode.y == null || targetNode.x == null || targetNode.y == null) return;

        const isNew = link.status === ChangeStatus.NEW;
        const linkColor = isNew ? '#22c55e' : link.color || (isDarkMode ? '#64748b' : '#94a3b8');

        ctx.strokeStyle = linkColor;
        ctx.lineWidth = isNew ? 2 : 1;
        ctx.beginPath();
        ctx.moveTo(sourceNode.x, sourceNode.y);
        ctx.lineTo(targetNode.x, targetNode.y);
        ctx.stroke();

        // Draw label if enabled
        const curShowEdgeLabels = showEdgeLabelsRef.current;
        if (curShowEdgeLabels && globalScale > 0.5) {
          const midX = (sourceNode.x + targetNode.x) / 2;
          const midY = (sourceNode.y + targetNode.y) / 2;

          ctx.fillStyle = isDarkMode ? '#94a3b8' : '#64748b';
          ctx.font = `${10 / globalScale}px sans-serif`;
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(link.relationshipType, midX, midY);
        }
      },
      [isDarkMode, forceGraphData.nodes]
    );

    // Configure d3 forces via effect on graph ref
    useEffect(() => {
      if (graphRef.current) {
        const linkForce = graphRef.current.d3Force('link');
        if (linkForce) {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any -- d3 force types not fully exposed
          (linkForce as any).distance(edgeLength).strength(0.5);
        }
        const chargeForce = graphRef.current.d3Force('charge');
        if (chargeForce) {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any -- d3 force types not fully exposed
          (chargeForce as any).strength(-300 / Math.max(edgeLength / 80, 1));
        }
        graphRef.current.d3ReheatSimulation();
      }
    }, [edgeLength]);

    return (
      <div ref={containerRef} className="relative w-full h-full" style={{ width, height }}>
        {/* Canvas with dot grid background */}
        <div
          className="absolute inset-0"
          style={{
            backgroundImage: `radial-gradient(circle, ${isDarkMode ? '#475569' : '#cbd5e1'} 1px, transparent 1px)`,
            backgroundSize: '20px 20px',
            backgroundPosition: '0 0',
          }}
        />
        <ForceGraph2D
          ref={graphRef}
          graphData={forceGraphData}
          nodeLabel=""
          linkLabel=""
          nodeCanvasObject={nodeCanvasObject}
          linkCanvasObject={linkCanvasObject}
          onNodeClick={handleNodeClick}
          onLinkClick={handleLinkClick}
          onNodeDragEnd={handleNodeDragEnd}
          onNodeHover={handleNodeHover}
          onLinkHover={() => handleNodeHover(null)}
          cooldownTicks={100}
          onEngineStop={() => {
            // Save all node positions when simulation stops
            forceGraphData.nodes.forEach((node) => {
              if (node.x !== undefined && node.y !== undefined) {
                nodePositionsRef.current.set(node.id, { x: node.x, y: node.y });
              }
            });
          }}
          width={width}
          height={height}
        />

        {/* Zoom Controls */}
        <div className="absolute bottom-4 right-4 flex flex-col gap-2">
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="outline"
                  size="icon"
                  onClick={() => {
                    if (graphRef.current) {
                      const currentZoom = graphRef.current.zoom() || 1;
                      graphRef.current.zoom(currentZoom * 1.2, 300);
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
                      const currentZoom = graphRef.current.zoom() || 1;
                      graphRef.current.zoom(currentZoom / 1.2, 300);
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
        {hoveredNode && mousePosition && (
          <Card
            className="absolute z-50 min-w-[200px] max-w-[300px] bg-background/95 backdrop-blur-sm pointer-events-none"
            style={{
              left: `${Math.min(mousePosition.x + 10, width - 220)}px`,
              top: `${Math.min(mousePosition.y + 10, height - 150)}px`,
            }}
          >
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
                    hoveredNode.status === ChangeStatus.MODIFIED && 'bg-yellow-500/20 text-yellow-500'
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
  }
);

GraphVisualization.displayName = 'GraphVisualization';

export default GraphVisualization;
