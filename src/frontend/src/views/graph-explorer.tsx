import { useState, useCallback, useRef, useEffect } from 'react';
import { useToast } from '@/hooks/use-toast';
import { useGraphEditor } from '@/hooks/use-graph-editor';
import type { GraphData, GraphNode, GraphEdge } from '@/types/graph-explorer';
import GraphVisualization, { type GraphVisualizationRef } from '@/components/graph-explorer/graph-visualization';
import GraphControls from '@/components/graph-explorer/graph-controls';
import NodePalette from '@/components/graph-explorer/node-palette';
import NodeSearch from '@/components/graph-explorer/node-search';
import { NodeForm, EdgeForm } from '@/components/graph-explorer/node-edge-form';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent } from '@/components/ui/card';
import { Loader2, Save, RefreshCw, Database } from 'lucide-react';

const DEFAULT_TABLE = 'main.default.property_graph_entity_edges';

const EMPTY_GRAPH_DATA: GraphData = { nodes: [], edges: [] };

export default function GraphExplorerView() {
  const { toast } = useToast();
  const graphRef = useRef<GraphVisualizationRef>(null);

  // Table name state
  const [tableName, setTableName] = useState(DEFAULT_TABLE);
  const [tableInput, setTableInput] = useState(DEFAULT_TABLE);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [hasLoaded, setHasLoaded] = useState(false);

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
  } = editor;

  // Visualization settings
  const [showProposed, setShowProposed] = useState(true);
  const [selectedNodeTypes, setSelectedNodeTypes] = useState<string[]>([]);
  const [selectedRelationshipTypes, setSelectedRelationshipTypes] = useState<string[]>([]);
  const [showNodeLabels, setShowNodeLabels] = useState(false);
  const [showEdgeLabels, setShowEdgeLabels] = useState(false);
  const [edgeLength, setEdgeLength] = useState(80);
  const [nodeSize, setNodeSize] = useState(6);

  // Dialog states
  const [nodeFormOpen, setNodeFormOpen] = useState(false);
  const [nodeFormMode, setNodeFormMode] = useState<'create' | 'edit'>('create');
  const [nodeFormData, setNodeFormData] = useState<GraphNode | undefined>();
  const [edgeFormOpen, setEdgeFormOpen] = useState(false);
  const [edgeFormMode, setEdgeFormMode] = useState<'create' | 'edit'>('create');
  const [edgeFormData, setEdgeFormData] = useState<GraphEdge | undefined>();
  const [edgeFormSourceId, setEdgeFormSourceId] = useState<string | undefined>();
  const [edgeFormTargetId, setEdgeFormTargetId] = useState<string | undefined>();

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
      const data: GraphData = await response.json();
      resetToInitialData(data);
      setHasLoaded(true);
      toast({ title: 'Graph loaded', description: `${data.nodes.length} nodes, ${data.edges.length} edges from ${tableName}` });
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      toast({ title: 'Error loading graph', description: message, variant: 'destructive' });
    } finally {
      setIsLoading(false);
    }
  }, [tableName, toast, resetToInitialData]);

  // Save new/modified data to backend
  const handleSave = useCallback(async () => {
    const newNodes = editor.userCreatedNodes;
    const newEdges = editor.userCreatedEdges;

    if (newNodes.length === 0 && newEdges.length === 0) {
      toast({ title: 'Nothing to save', description: 'No new nodes or edges to write.' });
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
        title: 'Saved to Databricks',
        description: `Wrote ${result.nodesWritten} nodes and ${result.edgesWritten} edges to ${tableName}`,
      });
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      toast({ title: 'Error saving', description: message, variant: 'destructive' });
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
        toast({ title: 'Node deleted', description: `Removed node ${nodeId} from ${tableName}` });
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : String(error);
        toast({ title: 'Error deleting node', description: message, variant: 'destructive' });
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
        toast({ title: 'Edge deleted' });
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : String(error);
        toast({ title: 'Error deleting edge', description: message, variant: 'destructive' });
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
              Databricks Table
            </Label>
            <Input
              id="table-name"
              value={tableInput}
              onChange={(e) => setTableInput(e.target.value)}
              placeholder="catalog.schema.table"
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleConnect();
              }}
            />
          </div>
          <Button onClick={handleConnect} disabled={isLoading || !tableInput.trim()}>
            {isLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
            {hasLoaded ? 'Reload' : 'Connect'}
          </Button>
          <Button onClick={handleSave} disabled={isSaving || !hasUnsaved} variant={hasUnsaved ? 'default' : 'outline'}>
            {isSaving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
            Save ({editor.userCreatedNodes.length + editor.userCreatedEdges.length})
          </Button>
        </CardContent>
      </Card>

      {/* Main Layout */}
      <div className="flex flex-1 gap-4 min-h-0">
        {/* Left Sidebar */}
        <div className="w-72 flex-shrink-0 space-y-4 overflow-y-auto">
          <NodeSearch graphData={editor.graphData} onNodeSelect={handleNodeClick} disabled={!hasLoaded} />
          <NodePalette
            onStartCreateNode={() => {
              setNodeFormData(undefined);
              setNodeFormMode('create');
              setNodeFormOpen(true);
            }}
            onStartCreateEdge={startEdgeCreateMode}
            disabled={!hasLoaded}
          />
        </div>

        {/* Graph Canvas */}
        <div ref={containerRef} className="flex-1 rounded-lg border bg-background overflow-hidden relative min-h-[400px]">
          {isLoading && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/80">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          )}
          {!hasLoaded && !isLoading && (
            <div className="absolute inset-0 flex items-center justify-center text-muted-foreground">
              <div className="text-center space-y-2">
                <Database className="h-12 w-12 mx-auto opacity-50" />
                <p>Enter a Databricks table name and click Connect to load graph data.</p>
              </div>
            </div>
          )}
          <GraphVisualization
            ref={graphRef}
            data={editor.graphData}
            showProposed={showProposed}
            selectedNodeTypes={selectedNodeTypes}
            selectedRelationshipTypes={selectedRelationshipTypes}
            showNodeLabels={showNodeLabels}
            showEdgeLabels={showEdgeLabels}
            edgeLength={edgeLength}
            nodeSize={nodeSize}
            width={dimensions.width}
            height={dimensions.height}
            onNodeClick={handleNodeClick}
            onEdgeClick={handleEdgeClick}
            edgeCreateMode={isEdgeCreateMode}
            edgeCreateSourceId={edgeCreateSourceId}
            selectedNodeId={selectedNodeId}
          />
        </div>

        {/* Right Sidebar */}
        <div className="w-72 flex-shrink-0 overflow-y-auto">
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
            nodeSize={nodeSize}
            onNodeSizeChange={setNodeSize}
            onResetView={() => graphRef.current?.resetView()}
            graphData={editor.graphData}
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
                ? `Click a target node to connect from "${edgeCreateSourceId}"`
                : 'Click a source node to start creating an edge'}
            </span>
            <Button variant="outline" size="sm" onClick={cancelEdgeCreateMode}>
              Cancel
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
    </div>
  );
}
