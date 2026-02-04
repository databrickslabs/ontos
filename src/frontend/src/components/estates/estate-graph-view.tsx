import React, { useEffect } from 'react';
import ReactFlow, {
    Node,
    Edge,
    Background,
    Controls,
    MiniMap,
    useNodesState,
    useEdgesState,
    Position,
    MarkerType,
} from 'reactflow';
import 'reactflow/dist/style.css';
import dagre from 'dagre';
import EstateNode, { EstateNodeData } from './estate-node'; // DynamicHandle removed - unused

// --- TypeScript Interfaces (Consider moving to src/types/estate.ts later) ---
type CloudType = 'aws' | 'azure' | 'gcp';
type SyncStatus = 'pending' | 'running' | 'success' | 'failed';
type ConnectionType = 'delta_share' | 'database';
// Sharing related types (can be removed if not directly used by graph nodes display logic)
// type SharingResourceType = 'data_product' | 'business_glossary';
// type SharingRuleOperator = 'equals' | 'contains' | 'starts_with' | 'regex';

// interface SharingRule {
//   filter_type: string;
//   operator: SharingRuleOperator;
//   filter_value: string;
// }

// interface SharingPolicy {
//   id?: string;
//   name: string;
//   description?: string;
//   resource_type: SharingResourceType;
//   rules: SharingRule[];
//   is_enabled: boolean;
//   created_at: string; 
//   updated_at: string; 
// }

export interface Estate { // Exporting Estate as it's used in EstateNodeData via EstateNode
  id: string;
  name: string;
  description: string;
  workspace_url: string;
  cloud_type: CloudType;
  metastore_name: string;
  connection_type: ConnectionType;
  sharing_policies: any[]; // Simplified for graph view, assuming full SharingPolicy not needed for node display
  is_enabled: boolean;
  sync_schedule: string;
  last_sync_time?: string;
  last_sync_status?: SyncStatus;
  last_sync_error?: string;
  created_at: string;
  updated_at: string;
}
// --- End TypeScript Interfaces ---

interface EstateGraphViewProps {
  estates: Estate[];
  onNodeClick: (estateId: string) => void;
}

const nodeTypes = { estateNode: EstateNode };

const NODE_WIDTH = 288; // w-72, from EstateNode
const NODE_HEIGHT = 128; // Approximate height of EstateNode

const dagreGraph = new dagre.graphlib.Graph();
dagreGraph.setDefaultEdgeLabel(() => ({}));

const getLayoutedElements = (
    estates: Estate[],
    localInstanceNodeData: Partial<Estate>,
    onNodeClick: (estateId: string) => void,
    direction = 'TB' // Top-to-Bottom layout might be better for a central node
) => {
    // Detect dark mode
    const isDarkMode = document.documentElement.classList.contains('dark');

    dagreGraph.setGraph({ rankdir: direction, nodesep: 60, ranksep: 90 }); // Increased ranksep

    const initialNodes: Node<EstateNodeData | any>[] = [];
    const initialEdges: Edge[] = [];

    // Add Local Instance Node
    initialNodes.push({
        id: 'local-instance',
        type: 'estateNode',
        data: {
            estate: localInstanceNodeData as Estate,
            onClick: () => console.log('Local instance node clicked'), // Or navigate to a specific local info page
            isLocalInstance: true,
        },
        position: { x: 0, y: 0 }, // Dagre will set this
    });
    dagreGraph.setNode('local-instance', { width: NODE_WIDTH, height: NODE_HEIGHT });
    
    // Add Remote Estate Nodes
    estates.forEach(estate => {
        initialNodes.push({
            id: estate.id,
            type: 'estateNode',
            data: { estate, onClick: onNodeClick },
            position: { x: 0, y: 0 }, // Dagre will set this
        });
        dagreGraph.setNode(estate.id, { width: NODE_WIDTH, height: NODE_HEIGHT });

        if (estate.is_enabled) {
            initialEdges.push({
                id: `edge-local-to-${estate.id}`,
                source: 'local-instance',
                target: estate.id,
                type: 'smoothstep',
                animated: true,
                markerEnd: {
                    type: MarkerType.ArrowClosed,
                    color: isDarkMode ? '#94a3b8' : '#888'
                },
                style: {
                    strokeWidth: 1.5,
                    stroke: isDarkMode ? '#94a3b8' : '#888'
                },
            });
            dagreGraph.setEdge('local-instance', estate.id);
        }
    });
    
    dagre.layout(dagreGraph);

    return {
        nodes: initialNodes.map(node => {
            const nodeWithPosition = dagreGraph.node(node.id);
            return {
                ...node,
                targetPosition: direction === 'LR' ? Position.Left : Position.Top,
                sourcePosition: direction === 'LR' ? Position.Right : Position.Bottom,
                position: {
                    x: nodeWithPosition.x - (node.id === 'local-instance' ? NODE_WIDTH : NODE_WIDTH) / 2,
                    y: nodeWithPosition.y - (node.id === 'local-instance' ? NODE_HEIGHT : NODE_HEIGHT) / 2,
                },
            };
        }),
        edges: initialEdges,
    };
};


const EstateGraphView: React.FC<EstateGraphViewProps> = ({ estates, onNodeClick }) => {
  const [nodes, setNodes, onNodesChange] = useNodesState<EstateNodeData | any>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const reactFlowWrapper = React.useRef<HTMLDivElement>(null);

  // Detect dark mode
  const isDarkMode = document.documentElement.classList.contains('dark');

  useEffect(() => {
    if (!estates || !reactFlowWrapper.current) {
      setNodes([]);
      setEdges([]);
      return;
    }

    const localInstanceNodeData: Partial<Estate> = {
      id: 'local-instance',
      name: 'Local Application Instance',
      description: 'This application instance, managing connections to remote estates.',
      cloud_type: 'aws', // Example
      connection_type: 'delta_share', // Example
      is_enabled: true,
      sharing_policies: [],
      metastore_name: 'local_app_metastore',
      workspace_url: 'N/A',
      sync_schedule: 'N/A',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    
    const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(
        estates, 
        localInstanceNodeData, 
        onNodeClick,
        'TB' // Using Top-to-Bottom layout
    );
    
    setNodes(layoutedNodes);
    setEdges(layoutedEdges);

  }, [estates, onNodeClick, setNodes, setEdges, reactFlowWrapper]); // Removed reactFlowWrapper.current

  return (
    <div ref={reactFlowWrapper} className="h-full w-full" data-testid="estate-graph-view-rf">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        attributionPosition="bottom-right"
        className="bg-background"
      >
        <Controls />
        <MiniMap nodeStrokeWidth={3} zoomable pannable />
        <Background color={isDarkMode ? '#334155' : '#e2e8f0'} gap={16} />
      </ReactFlow>
    </div>
  );
};

export default EstateGraphView; 