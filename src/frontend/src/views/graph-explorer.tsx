import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';
import { useToast } from '@/hooks/use-toast';
import { useGraphEditor } from '@/hooks/use-graph-editor';
import type { GraphData, GraphNode, GraphEdge } from '@/types/graph-explorer';
import GraphVisualization, {
  type GraphVisualizationRef,
  type NodeRightClickEvent,
  type EdgeRightClickEvent,
  type CanvasRightClickEvent,
} from '@/components/graph-explorer/graph-visualization';
import {
  GraphContextMenu,
  type ContextMenuTarget,
  type ContextMenuPosition,
} from '@/components/graph-explorer/graph-context-menu';
import GraphControls from '@/components/graph-explorer/graph-controls';
import { GraphTableView } from '@/components/graph-explorer/graph-table-view';
import { DiagramManager } from '@/components/graph-explorer/diagram-manager';
import { ConceptTooltip } from '@/components/graph-explorer/concept-tooltip';
import NodePalette from '@/components/graph-explorer/node-palette';
import NodeSearch from '@/components/graph-explorer/node-search';
import { NodeForm, EdgeForm } from '@/components/graph-explorer/node-edge-form';
import GraphQueryPanel from '@/components/graph-explorer/graph-query-panel';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { Loader2, Save, RefreshCw, Database, AlertTriangle, LayoutGrid, Table2, Columns2 } from 'lucide-react';

type ViewMode = 'graph' | 'table' | 'split';

const DEFAULT_TABLE = 'main.default.property_graph_entity_edges';

const EMPTY_GRAPH_DATA: GraphData = { nodes: [], edges: [] };

export default function GraphExplorerView() {
  const { t } = useTranslation(['graph-explorer', 'common']);
  const { toast } = useToast();
  const graphRef = useRef<GraphVisualizationRef>(null);
  const [searchParams, setSearchParams] = useSearchParams();

  // Table name state
  const [tableName, setTableName] = useState(DEFAULT_TABLE);
  const [tableInput, setTableInput] = useState(DEFAULT_TABLE);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [isTruncated, setIsTruncated] = useState(false);
  const [totalAvailable, setTotalAvailable] = useState<number | null>(null);

  // Graph editor hook — destructure stable callbacks for dependency arrays
  const editor = useGraphEditor({ initialData: EMPTY_GRAPH_DATA });
  const {
    resetToInitialData,
    markItemsAsSaved,
    deleteNode: editorDeleteNode,
    deleteEdge: editorDeleteEdge,
    addNode,
    updateNode,
    addEdge,
    updateEdge,
    selectNode,
    selectEdge,
    startEdgeCreateMode,
    cancelEdgeCreateMode,
    handleNodeClickForEdge,
    isEdgeCreateMode,
    edgeCreateSourceId,
    selectedNodeId,
    mergeNeighbors,
    collapseNode,
    expandedNodeIds,
  } = editor;

  // Derive the type of the currently-selected node (for ConceptTooltip)
  const selectedNodeType = useMemo(() => {
    if (!selectedNodeId) return null;
    const node = editor.graphData.nodes.find((n) => n.id === selectedNodeId);
    return node?.type ?? null;
  }, [selectedNodeId, editor.graphData.nodes]);

  // Phase 2b: read ?filterType= URL param and apply as node type filter
  const filterTypeParam = searchParams.get('filterType');

  // Visualization settings
  const [showProposed, setShowProposed] = useState(true);
  const [selectedNodeTypes, setSelectedNodeTypes] = useState<string[]>([]);
  const [selectedRelationshipTypes, setSelectedRelationshipTypes] = useState<string[]>([]);
  const [showNodeLabels, setShowNodeLabels] = useState(false);
  const [showEdgeLabels, setShowEdgeLabels] = useState(false);
  const [edgeLength, setEdgeLength] = useState(80);
  const [edgeOpacity, setEdgeOpacity] = useState(0.6);
  const [nodeSize, setNodeSize] = useState(6);
  const [viewMode, setViewMode] = useState<ViewMode>('graph');

  // Dialog states
  const [nodeFormOpen, setNodeFormOpen] = useState(false);
  const [nodeFormMode, setNodeFormMode] = useState<'create' | 'edit'>('create');
  const [nodeFormData, setNodeFormData] = useState<GraphNode | undefined>();
  const [edgeFormOpen, setEdgeFormOpen] = useState(false);
  const [edgeFormMode, setEdgeFormMode] = useState<'create' | 'edit'>('create');
  const [edgeFormData, setEdgeFormData] = useState<GraphEdge | undefined>();
  const [edgeFormSourceId, setEdgeFormSourceId] = useState<string | undefined>();
  const [edgeFormTargetId, setEdgeFormTargetId] = useState<string | undefined>();

  // Query panel overlay — when a query is active, we show its results instead of the full graph
  const [queryOverrideData, setQueryOverrideData] = useState<GraphData | null>(null);

  // Context menu state
  const [contextMenuPosition, setContextMenuPosition] = useState<ContextMenuPosition | null>(null);
  const [contextMenuTarget, setContextMenuTarget] = useState<ContextMenuTarget | null>(null);

  const closeContextMenu = useCallback(() => {
    setContextMenuPosition(null);
    setContextMenuTarget(null);
  }, []);

  // Build the set of edge types connected to a given node
  const getConnectedEdgeTypes = useCallback(
    (nodeId: string): string[] => {
      const types = new Set<string>();
      editor.graphData.edges.forEach((e) => {
        if (e.source === nodeId || e.target === nodeId) {
          types.add(e.relationshipType);
        }
      });
      return [...types].sort();
    },
    [editor.graphData.edges],
  );

  // Right-click handlers for context menu
  const handleNodeRightClick = useCallback(
    (event: NodeRightClickEvent) => {
      setContextMenuPosition({ x: event.screenX, y: event.screenY });
      setContextMenuTarget({
        type: 'node',
        id: event.nodeId,
        label: event.label,
        nodeType: event.type,
        isExpanded: expandedNodeIds.has(event.nodeId),
        connectedEdgeTypes: getConnectedEdgeTypes(event.nodeId),
      });
    },
    [expandedNodeIds, getConnectedEdgeTypes],
  );

  const handleEdgeRightClick = useCallback((event: EdgeRightClickEvent) => {
    setContextMenuPosition({ x: event.screenX, y: event.screenY });
    setContextMenuTarget({
      type: 'edge',
      id: event.edgeId,
      relationshipType: event.relationshipType,
    });
  }, []);

  const handleCanvasRightClick = useCallback((event: CanvasRightClickEvent) => {
    setContextMenuPosition({ x: event.screenX, y: event.screenY });
    setContextMenuTarget({ type: 'canvas' });
  }, []);

  // Expand neighbors of a node via the API
  const handleExpandNeighbors = useCallback(
    async (nodeId: string, direction: 'outgoing' | 'incoming' | 'both') => {
      try {
        const params = new URLSearchParams({
          nodeId,
          tableName,
          direction,
          limit: '25',
        });
        const response = await fetch(`/api/graph-explorer/neighbors?${params}`);
        if (!response.ok) {
          const err = await response.json().catch(() => ({ detail: response.statusText }));
          throw new Error(err.detail || `HTTP ${response.status}`);
        }
        const data: GraphData & { truncated?: boolean; totalAvailable?: number } = await response.json();
        mergeNeighbors(nodeId, data);

        const newNodeCount = data.nodes.length;
        const newEdgeCount = data.edges.length;
        if (newNodeCount > 0 || newEdgeCount > 0) {
          toast({
            title: t('contextMenu.neighborsLoaded'),
            description: t('contextMenu.neighborsLoadedDescription', { nodeCount: newNodeCount, edgeCount: newEdgeCount }),
          });
        } else {
          toast({ title: t('contextMenu.noNewNeighbors') });
        }
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : String(error);
        toast({ title: t('contextMenu.errorLoadingNeighbors'), description: message, variant: 'destructive' });
      }
    },
    [tableName, mergeNeighbors, toast, t],
  );

  // Expand neighbors filtered by a specific edge type
  const handleExpandByType = useCallback(
    async (nodeId: string, edgeType: string) => {
      try {
        const params = new URLSearchParams({
          nodeId,
          tableName,
          direction: 'both',
          limit: '25',
        });
        params.append('edgeTypes', edgeType);
        const response = await fetch(`/api/graph-explorer/neighbors?${params}`);
        if (!response.ok) {
          const err = await response.json().catch(() => ({ detail: response.statusText }));
          throw new Error(err.detail || `HTTP ${response.status}`);
        }
        const data: GraphData & { truncated?: boolean; totalAvailable?: number } = await response.json();
        mergeNeighbors(nodeId, data);

        const newNodeCount = data.nodes.length;
        const newEdgeCount = data.edges.length;
        if (newNodeCount > 0 || newEdgeCount > 0) {
          toast({
            title: t('contextMenu.neighborsLoaded'),
            description: t('contextMenu.neighborsLoadedDescription', { nodeCount: newNodeCount, edgeCount: newEdgeCount }),
          });
        } else {
          toast({ title: t('contextMenu.noNewNeighbors') });
        }
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : String(error);
        toast({ title: t('contextMenu.errorLoadingNeighbors'), description: message, variant: 'destructive' });
      }
    },
    [tableName, mergeNeighbors, toast, t],
  );

  // Collapse handler delegates to editor hook
  const handleCollapseNode = useCallback(
    (nodeId: string) => {
      collapseNode(nodeId);
    },
    [collapseNode],
  );

  // Center on node via graph ref
  const handleCenterOnNode = useCallback(
    (nodeId: string) => {
      graphRef.current?.centerOnNode(nodeId);
    },
    [],
  );

  // Edit node via context menu — opens the node form
  const handleContextEditNode = useCallback(
    (nodeId: string) => {
      selectNode(nodeId);
      const node = editor.graphData.nodes.find((n) => n.id === nodeId);
      if (node) {
        setNodeFormData(node);
        setNodeFormMode('edit');
        setNodeFormOpen(true);
      }
    },
    [selectNode, editor.graphData.nodes],
  );

  // Edit edge via context menu — opens the edge form
  const handleContextEditEdge = useCallback(
    (edgeId: string) => {
      selectEdge(edgeId);
      const edge = editor.graphData.edges.find((e) => e.id === edgeId);
      if (edge) {
        setEdgeFormData(edge);
        setEdgeFormMode('edit');
        setEdgeFormOpen(true);
      }
    },
    [selectEdge, editor.graphData.edges],
  );

  // Create node from canvas context menu
  const handleContextCreateNode = useCallback(() => {
    setNodeFormData(undefined);
    setNodeFormMode('create');
    setNodeFormOpen(true);
  }, []);

  const handleQueryApply = useCallback((nodes: GraphNode[], edges: GraphEdge[]) => {
    setQueryOverrideData({ nodes, edges });
  }, []);

  const handleQueryClear = useCallback(() => {
    setQueryOverrideData(null);
  }, []);

  // The data fed to the visualization — query results take precedence
  const displayData = useMemo<GraphData>(
    () => queryOverrideData ?? editor.graphData,
    [queryOverrideData, editor.graphData],
  );

  // Container dimensions
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const containerRef = useRef<HTMLDivElement>(null);

  // Measure container
  useEffect(() => {
    const measure = () => {
      if (containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect();
        setDimensions({ width: rect.width, height: Math.max(rect.height, 400) });
      }
    };
    measure();
    window.addEventListener('resize', measure);
    return () => window.removeEventListener('resize', measure);
  }, []);

  // Fetch graph data from backend
  const fetchGraphData = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await fetch(`/api/graph-explorer?tableName=${encodeURIComponent(tableName)}`);
      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: response.statusText }));
        throw new Error(err.detail || `HTTP ${response.status}`);
      }
      const data = await response.json() as GraphData & { truncated?: boolean; totalAvailable?: number | null };
      resetToInitialData(data);
      setHasLoaded(true);
      setIsTruncated(!!data.truncated);
      setTotalAvailable(data.totalAvailable ?? null);
      toast({ title: t('toast.graphLoaded'), description: t('toast.graphLoadedDescription', { nodeCount: data.nodes.length, edgeCount: data.edges.length, tableName }) });
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      toast({ title: t('toast.errorLoading'), description: message, variant: 'destructive' });
    } finally {
      setIsLoading(false);
    }
  }, [tableName, toast, resetToInitialData]);

  // Save new/modified data to backend
  const handleSave = useCallback(async () => {
    const newNodes = editor.userCreatedNodes;
    const newEdges = editor.userCreatedEdges;

    if (newNodes.length === 0 && newEdges.length === 0) {
      toast({ title: t('toast.nothingToSave'), description: t('toast.nothingToSaveDescription') });
      return;
    }

    setIsSaving(true);
    try {
      const response = await fetch('/api/graph-explorer/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tableName,
          nodes: newNodes.map((n) => ({
            id: n.id,
            label: n.label,
            type: n.type,
            properties: n.properties,
          })),
          edges: newEdges.map((e) => ({
            id: e.id,
            source: e.source,
            target: e.target,
            relationshipType: e.relationshipType,
            properties: e.properties,
          })),
        }),
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: response.statusText }));
        throw new Error(err.detail || `HTTP ${response.status}`);
      }

      const result = await response.json();
      markItemsAsSaved(
        newNodes.map((n) => n.id),
        newEdges.map((e) => e.id),
      );
      toast({
        title: t('toast.savedToDatabricks'),
        description: t('toast.savedDescription', { nodesWritten: result.nodesWritten, edgesWritten: result.edgesWritten, tableName }),
      });
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      toast({ title: t('toast.errorSaving'), description: message, variant: 'destructive' });
    } finally {
      setIsSaving(false);
    }
  }, [tableName, editor.userCreatedNodes, editor.userCreatedEdges, markItemsAsSaved, toast]);

  // Delete a node via backend
  const handleDeleteNode = useCallback(
    async (nodeId: string) => {
      try {
        const response = await fetch('/api/graph-explorer/node', {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tableName, nodeId }),
        });
        if (!response.ok) {
          const err = await response.json().catch(() => ({ detail: response.statusText }));
          throw new Error(err.detail || `HTTP ${response.status}`);
        }
        editorDeleteNode(nodeId);
        toast({ title: t('toast.nodeDeleted'), description: t('toast.nodeDeletedDescription', { nodeId, tableName }) });
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : String(error);
        toast({ title: t('toast.errorDeletingNode'), description: message, variant: 'destructive' });
      }
    },
    [tableName, editorDeleteNode, toast],
  );

  // Delete an edge via backend
  const handleDeleteEdge = useCallback(
    async (edgeId: string) => {
      const edge = editor.graphData.edges.find((e) => e.id === edgeId);
      if (!edge) return;
      try {
        const response = await fetch('/api/graph-explorer/edge', {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            tableName,
            sourceId: edge.source,
            targetId: edge.target,
            relationshipType: edge.relationshipType,
          }),
        });
        if (!response.ok) {
          const err = await response.json().catch(() => ({ detail: response.statusText }));
          throw new Error(err.detail || `HTTP ${response.status}`);
        }
        editorDeleteEdge(edgeId);
        toast({ title: t('toast.edgeDeleted') });
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : String(error);
        toast({ title: t('toast.errorDeletingEdge'), description: message, variant: 'destructive' });
      }
    },
    [tableName, editor.graphData.edges, editorDeleteEdge, toast],
  );

  // Node click handler
  const handleNodeClick = useCallback(
    (nodeId: string) => {
      if (isEdgeCreateMode) {
        const result = handleNodeClickForEdge(nodeId);
        if (result) {
          setEdgeFormSourceId(result.sourceId);
          setEdgeFormTargetId(result.targetId);
          setEdgeFormMode('create');
          setEdgeFormData(undefined);
          setEdgeFormOpen(true);
        }
        return;
      }
      selectNode(nodeId);
      const node = editor.graphData.nodes.find((n) => n.id === nodeId);
      if (node) {
        setNodeFormData(node);
        setNodeFormMode('edit');
        setNodeFormOpen(true);
      }
    },
    [isEdgeCreateMode, handleNodeClickForEdge, selectNode, editor.graphData.nodes],
  );

  // Edge click handler
  const handleEdgeClick = useCallback(
    (edgeId: string) => {
      selectEdge(edgeId);
      const edge = editor.graphData.edges.find((e) => e.id === edgeId);
      if (edge) {
        setEdgeFormData(edge);
        setEdgeFormMode('edit');
        setEdgeFormOpen(true);
      }
    },
    [selectEdge, editor.graphData.edges],
  );

  // Node form save
  const handleNodeFormSave = useCallback(
    (node: Omit<GraphNode, 'status'>) => {
      if (nodeFormMode === 'create') {
        addNode(node);
      } else {
        updateNode(node.id, node);
      }
    },
    [nodeFormMode, addNode, updateNode],
  );

  // Edge form save
  const handleEdgeFormSave = useCallback(
    (edge: Omit<GraphEdge, 'status'>) => {
      if (edgeFormMode === 'create') {
        addEdge(edge);
      } else {
        updateEdge(edge.id, edge);
      }
    },
    [edgeFormMode, addEdge, updateEdge],
  );

  // Connect table input
  const handleConnect = useCallback(() => {
    const trimmed = tableInput.trim();
    if (!trimmed) return;
    setTableName(trimmed);
  }, [tableInput]);

  // Auto-fetch when tableName changes
  useEffect(() => {
    if (tableName) {
      fetchGraphData();
    }
  }, [tableName]); // eslint-disable-line react-hooks/exhaustive-deps

  // Phase 2b: apply ?filterType= URL param as a node type filter
  useEffect(() => {
    if (filterTypeParam) {
      setSelectedNodeTypes([filterTypeParam]);
    }
  }, [filterTypeParam]);

  // Clear the filterType param from the URL (user action)
  const clearFilterType = useCallback(() => {
    setSelectedNodeTypes([]);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete('filterType');
      return next;
    });
  }, [setSearchParams]);

  const stats = editor.getStats();
  const hasUnsaved = editor.userCreatedNodes.length > 0 || editor.userCreatedEdges.length > 0;

  return (
    <div className="flex flex-col h-full gap-4 p-4">
      {/* Table Selector Bar */}
      <Card>
        <CardContent className="flex items-end gap-4 pt-4 pb-4">
          <div className="flex-1 space-y-1">
            <Label htmlFor="table-name" className="flex items-center gap-2 text-sm font-medium">
              <Database className="h-4 w-4" />
              {t('databricksTable')}
            </Label>
            <Input
              id="table-name"
              value={tableInput}
              onChange={(e) => setTableInput(e.target.value)}
              placeholder={t('placeholders.catalogSchemaTable')}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleConnect();
              }}
            />
          </div>
          <Button onClick={handleConnect} disabled={isLoading || !tableInput.trim()}>
            {isLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
            {hasLoaded ? t('actions.reload') : t('actions.connect')}
          </Button>
          <Button onClick={handleSave} disabled={isSaving || !hasUnsaved} variant={hasUnsaved ? 'default' : 'outline'}>
            {isSaving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
            {t('actions.save')} ({editor.userCreatedNodes.length + editor.userCreatedEdges.length})
          </Button>
        </CardContent>
      </Card>

      {/* Graph Query Panel */}
      <GraphQueryPanel
        onApplyResults={handleQueryApply}
        onClearQuery={handleQueryClear}
        graphData={editor.graphData}
        tableName={tableName}
      />

      {/* filterType URL param banner */}
      {filterTypeParam && (
        <Card className="border-blue-500/50 bg-blue-50 dark:bg-blue-950/20">
          <CardContent className="flex items-center gap-3 py-2.5">
            <span className="text-sm text-blue-700 dark:text-blue-400">
              {t('filterType.active', { type: filterTypeParam })}
            </span>
            {!hasLoaded && (
              <span className="text-xs text-blue-500 dark:text-blue-400/70">
                {t('filterType.connectHint', { type: filterTypeParam })}
              </span>
            )}
            <Button
              variant="ghost"
              size="sm"
              className="ml-auto h-6 px-2 text-xs text-blue-600 hover:text-blue-700"
              onClick={clearFilterType}
            >
              {t('filterType.clear')}
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Truncation Banner */}
      {isTruncated && totalAvailable && (
        <Card className="border-amber-500/50 bg-amber-50 dark:bg-amber-950/20">
          <CardContent className="flex items-center gap-3 py-2.5">
            <AlertTriangle className="h-4 w-4 text-amber-500 flex-shrink-0" />
            <span className="text-sm text-amber-700 dark:text-amber-400">
              {t('limits.truncatedDescription', {
                shown: editor.graphData.nodes.length + editor.graphData.edges.length,
                total: totalAvailable,
              })}
            </span>
            <Badge variant="outline" className="ml-auto text-amber-600 border-amber-400 text-xs">
              {t('limits.truncated')}
            </Badge>
          </CardContent>
        </Card>
      )}

      {/* Main Layout */}
      <div className="flex flex-1 gap-4 min-h-0">
        {/* Left Sidebar */}
        <div className="w-72 flex-shrink-0 space-y-4 overflow-y-auto">
          <NodeSearch graphData={displayData} onNodeSelect={handleNodeClick} disabled={!hasLoaded} />
          <NodePalette
            onStartCreateNode={() => {
              setNodeFormData(undefined);
              setNodeFormMode('create');
              setNodeFormOpen(true);
            }}
            onStartCreateEdge={startEdgeCreateMode}
            disabled={!hasLoaded}
          />
          <DiagramManager
            tableName={tableName}
            currentData={displayData}
            onRestoreDiagram={resetToInitialData}
            disabled={!hasLoaded}
          />
        </div>

        {/* Graph Canvas / Table / Split */}
        <div ref={containerRef} className="flex-1 flex flex-col min-h-[400px] gap-0 relative">
          {/* View mode toggle */}
          <div className="absolute top-2 left-2 z-20 flex gap-0.5 rounded-md border bg-background/90 backdrop-blur-sm p-0.5">
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant={viewMode === 'graph' ? 'default' : 'ghost'}
                    size="icon"
                    className="h-7 w-7"
                    onClick={() => setViewMode('graph')}
                  >
                    <LayoutGrid className="h-3.5 w-3.5" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="bottom"><p>{t('viewMode.graph')}</p></TooltipContent>
              </Tooltip>
            </TooltipProvider>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant={viewMode === 'split' ? 'default' : 'ghost'}
                    size="icon"
                    className="h-7 w-7"
                    onClick={() => setViewMode('split')}
                  >
                    <Columns2 className="h-3.5 w-3.5" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="bottom"><p>{t('viewMode.split')}</p></TooltipContent>
              </Tooltip>
            </TooltipProvider>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant={viewMode === 'table' ? 'default' : 'ghost'}
                    size="icon"
                    className="h-7 w-7"
                    onClick={() => setViewMode('table')}
                  >
                    <Table2 className="h-3.5 w-3.5" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="bottom"><p>{t('viewMode.table')}</p></TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>

          {isLoading && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/80">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          )}
          {!hasLoaded && !isLoading && (
            <div className="absolute inset-0 flex items-center justify-center text-muted-foreground rounded-lg border bg-background">
              <div className="text-center space-y-2">
                <Database className="h-12 w-12 mx-auto opacity-50" />
                <p>{t('emptyState.message')}</p>
              </div>
            </div>
          )}

          {viewMode === 'graph' && (
            <div className="flex-1 rounded-lg border bg-background overflow-hidden">
              <GraphVisualization
                ref={graphRef}
                data={displayData}
                showProposed={showProposed}
                selectedNodeTypes={selectedNodeTypes}
                selectedRelationshipTypes={selectedRelationshipTypes}
                showNodeLabels={showNodeLabels}
                showEdgeLabels={showEdgeLabels}
                edgeLength={edgeLength}
                edgeOpacity={edgeOpacity}
                nodeSize={nodeSize}
                width={dimensions.width}
                height={dimensions.height}
                onNodeClick={handleNodeClick}
                onEdgeClick={handleEdgeClick}
                onNodeRightClick={handleNodeRightClick}
                onEdgeRightClick={handleEdgeRightClick}
                onCanvasRightClick={handleCanvasRightClick}
                edgeCreateMode={isEdgeCreateMode}
                edgeCreateSourceId={edgeCreateSourceId}
                selectedNodeId={selectedNodeId}
              />
            </div>
          )}

          {viewMode === 'table' && (
            <GraphTableView
              data={displayData}
              onNodeClick={handleNodeClick}
              onEdgeClick={handleEdgeClick}
              selectedNodeId={selectedNodeId}
              className="flex-1 rounded-lg"
            />
          )}

          {viewMode === 'split' && (
            <div className="flex-1 flex flex-col gap-2">
              <div className="flex-1 rounded-lg border bg-background overflow-hidden min-h-[200px]">
                <GraphVisualization
                  ref={graphRef}
                  data={displayData}
                  showProposed={showProposed}
                  selectedNodeTypes={selectedNodeTypes}
                  selectedRelationshipTypes={selectedRelationshipTypes}
                  showNodeLabels={showNodeLabels}
                  showEdgeLabels={showEdgeLabels}
                  edgeLength={edgeLength}
                  edgeOpacity={edgeOpacity}
                  nodeSize={nodeSize}
                  width={dimensions.width}
                  height={Math.max(Math.floor(dimensions.height * 0.55), 200)}
                  onNodeClick={handleNodeClick}
                  onEdgeClick={handleEdgeClick}
                  onNodeRightClick={handleNodeRightClick}
                  onEdgeRightClick={handleEdgeRightClick}
                  onCanvasRightClick={handleCanvasRightClick}
                  edgeCreateMode={isEdgeCreateMode}
                  edgeCreateSourceId={edgeCreateSourceId}
                  selectedNodeId={selectedNodeId}
                />
              </div>
              <GraphTableView
                data={displayData}
                onNodeClick={handleNodeClick}
                onEdgeClick={handleEdgeClick}
                selectedNodeId={selectedNodeId}
                className="h-[250px] rounded-lg"
              />
            </div>
          )}
        </div>

        {/* Right Sidebar */}
        <div className="w-72 flex-shrink-0 overflow-y-auto space-y-4">
          <ConceptTooltip nodeType={selectedNodeType} />
          <GraphControls
            showProposed={showProposed}
            onToggleProposed={setShowProposed}
            selectedNodeTypes={selectedNodeTypes}
            onNodeTypeChange={setSelectedNodeTypes}
            selectedRelationshipTypes={selectedRelationshipTypes}
            onRelationshipTypeChange={setSelectedRelationshipTypes}
            showNodeLabels={showNodeLabels}
            onToggleNodeLabels={setShowNodeLabels}
            showEdgeLabels={showEdgeLabels}
            onToggleEdgeLabels={setShowEdgeLabels}
            edgeLength={edgeLength}
            onEdgeLengthChange={setEdgeLength}
            edgeOpacity={edgeOpacity}
            onEdgeOpacityChange={setEdgeOpacity}
            nodeSize={nodeSize}
            onNodeSizeChange={setNodeSize}
            onResetView={() => graphRef.current?.resetView()}
            graphData={displayData}
            stats={stats}
          />
        </div>
      </div>

      {/* Edge Create Mode Banner */}
      {isEdgeCreateMode && (
        <Card className="border-green-500 bg-green-50 dark:bg-green-950/20">
          <CardContent className="flex items-center justify-between py-3">
            <span className="text-sm font-medium text-green-700 dark:text-green-400">
              {edgeCreateSourceId
                ? t('edgeCreateMode.clickTarget', { sourceId: edgeCreateSourceId })
                : t('edgeCreateMode.clickSource')}
            </span>
            <Button variant="outline" size="sm" onClick={cancelEdgeCreateMode}>
              {t('common:actions.cancel')}
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Node Form Dialog — key forces remount when data changes */}
      <NodeForm
        key={`node-${nodeFormData?.id ?? 'new'}-${nodeFormOpen}`}
        open={nodeFormOpen}
        onClose={() => setNodeFormOpen(false)}
        onSave={handleNodeFormSave}
        onDelete={nodeFormMode === 'edit' && nodeFormData ? handleDeleteNode : undefined}
        initialData={nodeFormData}
        mode={nodeFormMode}
      />

      {/* Edge Form Dialog — key forces remount when data changes */}
      <EdgeForm
        key={`edge-${edgeFormData?.id ?? 'new'}-${edgeFormOpen}`}
        open={edgeFormOpen}
        onClose={() => {
          setEdgeFormOpen(false);
          setEdgeFormSourceId(undefined);
          setEdgeFormTargetId(undefined);
        }}
        onSave={handleEdgeFormSave}
        onDelete={edgeFormMode === 'edit' && edgeFormData ? handleDeleteEdge : undefined}
        initialData={edgeFormData}
        sourceNodeId={edgeFormSourceId}
        targetNodeId={edgeFormTargetId}
        mode={edgeFormMode}
        availableNodes={editor.graphData.nodes}
      />

      {/* Context Menu */}
      <GraphContextMenu
        position={contextMenuPosition}
        target={contextMenuTarget}
        onClose={closeContextMenu}
        onExpandNeighbors={handleExpandNeighbors}
        onExpandByType={handleExpandByType}
        onCollapseNode={handleCollapseNode}
        onEditNode={handleContextEditNode}
        onDeleteNode={handleDeleteNode}
        onCenterOnNode={handleCenterOnNode}
        onEditEdge={handleContextEditEdge}
        onDeleteEdge={handleDeleteEdge}
        onCreateNode={handleContextCreateNode}
        onResetView={() => graphRef.current?.resetView()}
        onFitToScreen={() => graphRef.current?.resetView()}
      />
    </div>
  );
}
