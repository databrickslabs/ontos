import { useCallback, useEffect, useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import ReactFlow, {
  Node,
  Edge,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  MarkerType,
  Panel,
  Handle,
  Position,
} from 'reactflow';
import { useTheme } from '@/components/theme/theme-provider';
import dagre from 'dagre';
import 'reactflow/dist/style.css';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { Search, Download, Info } from 'lucide-react';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { GraphCanvasSkeleton } from '@/components/common/list-view-skeleton';

// Types for our schema data
interface Column {
  name: string;
  type: string;
  primary_key: boolean;
  nullable: boolean;
  foreign_key?: {
    target_table: string;
    target_column: string;
  } | null;
}

interface Table {
  id: string;
  name: string;
  columns: Column[];
  description?: string;
}

interface Relationship {
  id: string;
  source: string;
  target: string;
  columns: string[];
}

interface SchemaData {
  tables: Table[];
  relationships: Relationship[];
}

// Custom Table Node Component
function TableNode({ data }: { data: Table }) {
  const { t } = useTranslation(['database-schema', 'common']);
  const handleWheel = (e: React.WheelEvent) => {
    // Stop propagation to prevent React Flow from capturing the wheel event for zooming
    e.stopPropagation();
    // Don't prevent default - we want normal scrolling to work
  };

  return (
    <>
      <Handle type="target" position={Position.Left} style={{ visibility: 'hidden' }} />
      <Card className="min-w-[250px] max-w-[300px] shadow-lg border-border dark:border-slate-700 dark:bg-slate-800">
        {/* Only the header is draggable via drag-handle class */}
        <CardHeader className="drag-handle bg-primary text-primary-foreground py-2 px-3 cursor-move">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0 flex-1">
              <CardTitle className="text-sm font-bold">{data.name}</CardTitle>
              <div className="text-[10px] opacity-75 mt-0.5">{data.columns.length} columns</div>
            </div>
            <Popover>
              <PopoverTrigger asChild>
                <button
                  type="button"
                  className="nodrag nopan shrink-0 rounded p-1 hover:bg-primary-foreground/20 focus:outline-none focus:ring-2 focus:ring-primary-foreground/50"
                  aria-label={t('database-schema:tableInfo')}
                  onClick={(e) => e.stopPropagation()}
                >
                  <Info className="h-4 w-4" />
                </button>
              </PopoverTrigger>
              <PopoverContent className="nodrag max-w-sm text-sm" align="start">
                {data.description ? (
                  <p className="whitespace-pre-wrap">{data.description}</p>
                ) : (
                  <p className="text-muted-foreground">{t('database-schema:noDescription')}</p>
                )}
              </PopoverContent>
            </Popover>
          </div>
        </CardHeader>
        {/* Content is scrollable but not draggable */}
        <CardContent className="p-0">
          <div
            className="max-h-[500px] overflow-y-auto overflow-x-hidden nodrag cursor-default"
            onWheel={handleWheel}
          >
            <table className="w-full text-xs">
              <tbody>
                {data.columns.map((col, idx) => (
                  <tr
                    key={idx}
                    className={`border-b dark:border-slate-600 last:border-b-0 ${
                      col.primary_key
                        ? 'bg-yellow-50 dark:bg-yellow-900/50'
                        : col.foreign_key
                        ? 'bg-blue-50 dark:bg-blue-900/50'
                        : 'dark:bg-slate-800'
                    }`}
                  >
                    <td className="py-1 px-2 font-mono">
                      <div className="flex items-center gap-1">
                        {col.primary_key && (
                          <span className="text-yellow-600 dark:text-yellow-400" title={t('common:tooltips.primaryKey')}>
                            🔑
                          </span>
                        )}
                        {col.foreign_key && (
                          <span className="text-blue-600 dark:text-blue-400" title={t('common:tooltips.foreignKey')}>
                            🔗
                          </span>
                        )}
                        <span className="font-semibold truncate dark:text-slate-100">{col.name}</span>
                      </div>
                      <div className="text-[10px] text-muted-foreground mt-0.5 truncate">
                        {col.type}
                        {!col.nullable && (
                          <span className="text-red-500 ml-1" title="NOT NULL">
                            *
                          </span>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
      <Handle type="source" position={Position.Right} style={{ visibility: 'hidden' }} />
    </>
  );
}

// Custom node types
const nodeTypes = {
  tableNode: TableNode,
};

// Layout configuration using dagre
const getLayoutedElements = (
  tables: Table[],
  relationships: Relationship[],
  direction = 'LR',
  isDarkMode = false
) => {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  dagreGraph.setGraph({ rankdir: direction, nodesep: 150, ranksep: 200 });

  // Theme-aware edge colors
  const edgeColor = isDarkMode ? '#64748b' : '#94a3b8';
  const labelColor = isDarkMode ? '#94a3b8' : '#666';

  // Create nodes
  const nodes: Node[] = tables.map((table) => {
    const node: Node = {
      id: table.id,
      type: 'tableNode',
      data: table,
      position: { x: 0, y: 0 },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
    };
    
    // Estimate node dimensions based on content
    const width = 280;
    const height = Math.min(80 + table.columns.length * 35, 560);
    dagreGraph.setNode(table.id, { width, height });
    
    return node;
  });

  // Create edges
  const edges: Edge[] = relationships.map((rel) => ({
    id: rel.id,
    source: rel.source,
    target: rel.target,
    type: 'smoothstep',
    animated: false,
    markerEnd: {
      type: MarkerType.ArrowClosed,
      width: 20,
      height: 20,
      color: edgeColor,
    },
    style: {
      strokeWidth: 2,
      stroke: edgeColor,
    },
    label: rel.columns.join(', '),
    labelStyle: { fill: labelColor, fontSize: 10 },
  }));

  // Add edges to dagre
  relationships.forEach((rel) => {
    dagreGraph.setEdge(rel.source, rel.target);
  });

  // Calculate layout
  dagre.layout(dagreGraph);

  // Apply calculated positions
  nodes.forEach((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    node.position = {
      x: nodeWithPosition.x - nodeWithPosition.width / 2,
      y: nodeWithPosition.y - nodeWithPosition.height / 2,
    };
  });

  return { nodes, edges };
};

export default function DatabaseSchema() {
  const { t } = useTranslation(['database-schema', 'common']);
  const [schemaData, setSchemaData] = useState<SchemaData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  // Detect dark mode reactively
  const { theme } = useTheme();
  const isDarkMode = useMemo(() => {
    if (theme === 'dark') return true;
    if (theme === 'light') return false;
    // System theme - check the actual class on documentElement
    return document.documentElement.classList.contains('dark');
  }, [theme]);

  const setStaticSegments = useBreadcrumbStore((state: any) => state.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((state: any) => state.setDynamicTitle);

  // Set breadcrumb
  useEffect(() => {
    setStaticSegments([]);
    setDynamicTitle(t('database-schema:title'));
    return () => {
      setStaticSegments([]);
      setDynamicTitle(null);
    };
  }, [setStaticSegments, setDynamicTitle]);

  // Fetch schema data
  useEffect(() => {
    const fetchSchema = async () => {
      try {
        setLoading(true);
        setError(null);
        const response = await fetch('/api/database-schema');
        if (!response.ok) {
          throw new Error(`Failed to load schema: ${response.statusText}`);
        }
        const data = await response.json();
        setSchemaData(data);
      } catch (err) {
        console.error('Error loading database schema:', err);
        setError(err instanceof Error ? err.message : 'Failed to load schema');
      } finally {
        setLoading(false);
      }
    };

    fetchSchema();
  }, []);

  // Filter and layout nodes/edges when schema or search changes
  useEffect(() => {
    if (!schemaData) return;

    // Filter tables based on search
    const filteredTables = schemaData.tables.filter((table) =>
      table.name.toLowerCase().includes(searchTerm.toLowerCase())
    );

    // Filter relationships to only include those between visible tables
    const visibleTableIds = new Set(filteredTables.map((t) => t.id));
    const filteredRelationships = schemaData.relationships.filter(
      (rel) => visibleTableIds.has(rel.source) && visibleTableIds.has(rel.target)
    );

    // Layout the filtered elements
    const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(
      filteredTables,
      filteredRelationships,
      'LR',
      isDarkMode
    );

    setNodes(layoutedNodes);
    setEdges(layoutedEdges);
  }, [schemaData, searchTerm, setNodes, setEdges, isDarkMode]);

  const handleDownload = useCallback(() => {
    // Create a simple text representation for download
    if (!schemaData) return;

    const content = schemaData.tables
      .map((table) => {
        const cols = table.columns
          .map(
            (col) =>
              `  - ${col.name}: ${col.type}${col.primary_key ? ' [PK]' : ''}${
                col.foreign_key ? ` [FK -> ${col.foreign_key.target_table}]` : ''
              }`
          )
          .join('\n');
        return `${table.name}\n${cols}`;
      })
      .join('\n\n');

    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'database-schema.txt';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [schemaData]);

  if (loading) {
    return <GraphCanvasSkeleton showToolbar height="h-[600px]" />;
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-[600px]">
        <Card className="max-w-md">
          <CardHeader>
            <CardTitle className="text-destructive">{t('database-schema:errorLoadingSchema')}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-muted-foreground">{error}</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-4" style={{ height: 'calc(100vh - 80px)' }}>
      {/* Header with search and controls */}
      <div className="flex items-center gap-4 bg-background p-4 rounded-lg border">
        <div className="flex-1 relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            type="text"
            placeholder={t('common:placeholders.searchTables')}
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="pl-10"
          />
        </div>
        <Button onClick={handleDownload} variant="outline" size="sm">
          <Download className="h-4 w-4 mr-2" />
          {t('common:actions.export')}
        </Button>
        <div className="text-sm text-muted-foreground">
          {t('database-schema:tableCount', { count: schemaData?.tables.length || 0 })}, {t('database-schema:relationshipCount', { count: schemaData?.relationships.length || 0 })}
        </div>
      </div>

      {/* React Flow Diagram */}
      <div className="flex-1 border rounded-lg overflow-hidden bg-background" style={{ minHeight: 0 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          fitView
          minZoom={0.1}
          maxZoom={1.5}
          defaultViewport={{ x: 0, y: 0, zoom: 0.8 }}
          noWheelClassName="nodrag"
          defaultEdgeOptions={{
            markerEnd: { type: MarkerType.ArrowClosed },
          }}
        >
          <Background color={isDarkMode ? '#334155' : '#e2e8f0'} gap={16} />
          <Controls />
          <MiniMap
            nodeColor={() => isDarkMode ? '#60a5fa' : '#3b82f6'}
            maskColor={isDarkMode ? 'rgba(0, 0, 0, 0.6)' : 'rgba(240, 240, 240, 0.6)'}
            style={{
              backgroundColor: isDarkMode ? '#1e293b' : '#f8fafc',
            }}
            nodeStrokeWidth={3}
            zoomable
            pannable
          />
          <Panel position="top-left" className="bg-background/95 p-3 rounded-lg border shadow-sm text-xs m-2">
            <div className="font-semibold mb-2">{t('database-schema:legend')}</div>
            <div className="space-y-1.5">
              <div className="flex items-center gap-2">
                <span className="text-yellow-600 dark:text-yellow-400">🔑</span>
                <span>{t('common:tooltips.primaryKey')}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-blue-600 dark:text-blue-400">🔗</span>
                <span>{t('common:tooltips.foreignKey')}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-red-500">*</span>
                <span>{t('database-schema:notNull')}</span>
              </div>
            </div>
          </Panel>
        </ReactFlow>
      </div>
    </div>
  );
}

