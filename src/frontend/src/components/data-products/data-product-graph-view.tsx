import React, { useMemo } from 'react';
import ReactFlow, {
    Node,
    Edge,
    Background,
    Controls,
    MarkerType,
    Position,
    useNodesState,
    useEdgesState,
    NodeProps,
    Handle,
} from 'reactflow';
import { DataProduct, InputPort, OutputPort } from '@/types/data-product';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Table, Workflow } from 'lucide-react';
import * as dagre from 'dagre';
import { type NavigateFunction } from 'react-router-dom';
import { DatabaseZap } from 'lucide-react';
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@/components/ui/tooltip";

import 'reactflow/dist/style.css';

interface DataProductNodeData {
    label: string;
    productType?: string;
    version: string;
    status?: string;
    inputPorts: InputPort[];
    outputPorts: OutputPort[];
    nodeId: string;
    navigate: NavigateFunction;
}

const DataProductNode: React.FC<NodeProps<DataProductNodeData>> = ({ data }) => {
    const handleHeight = 10;
    const handleWidth = 10;
    const inputBaseTopOffset = 25;
    const outputBaseTopOffset = 25;

    return (
        <>
            {/* Input Port Handles (Left) - With Tooltips, NO Provider here */}
            {/* <TooltipProvider delayDuration={100}> */}
                 {Array.isArray(data.inputPorts) && data.inputPorts.map((port, index) => {
                    if (!port) {
                        return null;
                    }
                    // ODPS v1.0.0: Use port.id if available, otherwise fallback to port.name or index
                    const portId = (port as any).id || port.name || `input-${index}`;
                    const calculatedTop = inputBaseTopOffset + index * (handleHeight + 10);
                    return (
                        // Use a wrapper fragment and separate trigger div
                        <React.Fragment key={`input-frag-${portId}`}>
                             <Tooltip>
                                {/* Transparent div as trigger, positioned over the handle */}
                                <TooltipTrigger
                                    style={{
                                        position: 'absolute',
                                        left: '-8px', // Position to cover handle area
                                        top: `${calculatedTop - 2}px`, // Adjust top slightly
                                        width: `${handleWidth + 6}px`, // Make slightly larger than handle
                                        height: `${handleHeight + 4}px`,
                                        zIndex: 10 // Ensure it's above the handle visually
                                    }}
                                    onClick={(e) => e.stopPropagation()} // Keep stopPropagation
                                />
                                <TooltipContent side="left">
                                    <p className="font-semibold">{port.name} (Input)</p>
                                    {(port as any).description && <p className="text-xs text-muted-foreground">{(port as any).description}</p>}
                                    <p className="text-xs"><span className="text-muted-foreground">Contract:</span> {port.contractId}</p>
                                    <p className="text-xs"><span className="text-muted-foreground">Version:</span> {port.version}</p>
                                </TooltipContent>
                            </Tooltip>
                            {/* Render the Handle itself */}
                            <Handle
                                key={`input-${portId}`}
                                type="target"
                                position={Position.Left}
                                id={portId}
                                isConnectable={false}
                                // No onClick needed here now
                                style={{
                                    top: `${calculatedTop}px`,
                                    left: '-5px',
                                    width: `${handleWidth}px`,
                                    height: `${handleHeight}px`,
                                    borderRadius: '2px',
                                    background: '#55aaff',
                                    zIndex: 5 // Lower z-index than trigger
                                }}
                            />
                         </React.Fragment>
                    );
                 })}
            {/* </TooltipProvider> */}
            
            {/* Output Port Handles (Right) - With Tooltips, NO Provider here */}
             {/* <TooltipProvider delayDuration={100}> */}
                {Array.isArray(data.outputPorts) && data.outputPorts.map((port, index) => {
                     if (!port) {
                        return null;
                    }
                    // ODPS v1.0.0: Use port.id if available, otherwise fallback to port.name or index
                    const portId = (port as any).id || port.name || `output-${index}`;
                    const calculatedTop = outputBaseTopOffset + index * (handleHeight + 10);
                    return (
                         // Use a wrapper fragment and separate trigger div
                        <React.Fragment key={`output-frag-${portId}`}>
                             <Tooltip>
                                 {/* Transparent div as trigger, positioned over the handle */}
                                <TooltipTrigger
                                    style={{
                                        position: 'absolute',
                                        right: '-8px', // Position to cover handle area
                                        top: `${calculatedTop - 2}px`, // Adjust top slightly
                                        width: `${handleWidth + 6}px`, // Make slightly larger than handle
                                        height: `${handleHeight + 4}px`,
                                        zIndex: 10 // Ensure it's above the handle visually
                                    }}
                                    onClick={(e) => e.stopPropagation()} // Keep stopPropagation
                                />
                                <TooltipContent side="right">
                                    <p className="font-semibold">{port.name} (Output)</p>
                                    {port.description && <p className="text-xs text-muted-foreground">{port.description}</p>}
                                    {port.contractId && <p className="text-xs"><span className="text-muted-foreground">Contract:</span> {port.contractId}</p>}
                                    <p className="text-xs"><span className="text-muted-foreground">Version:</span> {port.version}</p>
                                </TooltipContent>
                            </Tooltip>
                             {/* Render the Handle itself */}
                            <Handle
                                key={`output-${portId}`}
                                type="source"
                                position={Position.Right}
                                id={portId}
                                isConnectable={false}
                                 // No onClick needed here now
                                style={{
                                    top: `${calculatedTop}px`,
                                    right: '-5px',
                                    width: `${handleWidth}px`,
                                    height: `${handleHeight}px`,
                                    borderRadius: '2px',
                                    background: '#ffaa55',
                                    zIndex: 5 // Lower z-index than trigger
                                }}
                            />
                        </React.Fragment>
                    );
                 })}
            {/* </TooltipProvider> */}

            <div 
                className="cursor-pointer" 
                onClick={(e) => {
                    e.stopPropagation();
                    data.navigate(`/data-products/${data.nodeId}`);
                }}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                         data.navigate(`/data-products/${data.nodeId}`);
                    }
                }} 
            >
                <Card className="w-64 shadow-md border-2 border-primary/50 bg-card hover:border-primary transition-colors">
                    <CardContent className="p-3 text-center">
                        <div className="text-sm font-semibold mb-1">{data.label}</div>
                        <div className="flex justify-center items-center gap-1 text-xs">
                             {data.productType && <Badge variant="outline">{data.productType}</Badge>}
                             <Badge variant="secondary">{data.version}</Badge>
                             {data.status && <Badge variant="default">{data.status}</Badge>}
                        </div>
                    </CardContent>
                </Card>
            </div>
        </>
    );
};

interface ExternalSourceNodeData {
    label: string; // sourceSystemId
}

const ExternalSourceNode: React.FC<NodeProps<ExternalSourceNodeData>> = ({ data }) => {
    return (
        <>
            <Card className="w-48 bg-muted/50 border-dashed border-muted-foreground/50">
                <CardContent className="p-2 text-center">
                    <div className="flex items-center justify-center gap-2">
                         <DatabaseZap className="h-4 w-4 text-muted-foreground" />
                         <span className="text-xs font-mono text-muted-foreground break-all">{data.label}</span>
                    </div>
                </CardContent>
            </Card>
             {/* Single Source Handle for external node */}
            <Handle 
                type="source" 
                position={Position.Right} 
                id="external-source-handle" // Specific ID for this handle
                isConnectable={false}
                style={{ top: '50%', background: '#aaaaaa' }} // Grey color
            />
        </>
    );
};

const nodeTypes = {
    dataProduct: DataProductNode,
    externalSource: ExternalSourceNode,
};

// --- Dagre Layout Helper ---
const dagreGraph = new dagre.graphlib.Graph();
dagreGraph.setDefaultEdgeLabel(() => ({}));

const nodeWidth = 256; // Approx width of DataProductNode (w-64)
const nodeHeight = 80; // Approx height of DataProductNode
const externalNodeWidth = 192; // w-48
const externalNodeHeight = 50; // Smaller height

const getLayoutedElements = (nodes: Node[], edges: Edge[], direction = 'LR') => {
  const isHorizontal = direction === 'LR';
  dagreGraph.setGraph({ rankdir: direction, ranksep: 70, nodesep: 30 });

  nodes.forEach((node) => {
    const width = node.type === 'externalSource' ? externalNodeWidth : nodeWidth;
    const height = node.type === 'externalSource' ? externalNodeHeight : nodeHeight;
    dagreGraph.setNode(node.id, { width, height });
  });

  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  dagre.layout(dagreGraph);

  nodes.forEach((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    const width = node.type === 'externalSource' ? externalNodeWidth : nodeWidth;
    const height = node.type === 'externalSource' ? externalNodeHeight : nodeHeight;
    node.targetPosition = isHorizontal ? Position.Left : Position.Top;
    node.sourcePosition = isHorizontal ? Position.Right : Position.Bottom;
    node.position = {
      x: nodeWithPosition.x - width / 2,
      y: nodeWithPosition.y - height / 2,
    };
  });

  return { nodes, edges };
};

interface DataProductGraphViewProps {
    products: DataProduct[];
    viewMode: 'table' | 'graph';
    setViewMode: (mode: 'table' | 'graph') => void;
    navigate: NavigateFunction;
}

const DataProductGraphView: React.FC<DataProductGraphViewProps> = ({ products, viewMode, setViewMode, navigate }) => {
    // Detect dark mode
    const isDarkMode = document.documentElement.classList.contains('dark');

    const initialElements = useMemo(() => {
        const validProducts = products.filter(p => p.id);
        const productNodes: Node<DataProductNodeData>[] = validProducts.map((product) => {
            // ODPS v1.0.0: Get first output port type if available
            const firstOutputType = (product.outputPorts && product.outputPorts.length > 0)
                ? product.outputPorts[0].type
                : undefined;

            return {
                id: product.id!,
                type: 'dataProduct',
                position: { x: 0, y: 0 },
                data: {
                    label: product.name || 'Unnamed Product', // ODPS v1.0.0: use name field
                    productType: firstOutputType, // ODPS v1.0.0: use first output port type
                    version: product.version || 'N/A',
                    status: product.status, // ODPS v1.0.0: status is at root level
                    inputPorts: product.inputPorts || [],
                    outputPorts: product.outputPorts || [],
                    nodeId: product.id!,
                    navigate: navigate
                },
            };
        });

        // Track product node IDs (computed for future filtering needs)
        new Set(productNodes.map(n => n.id));
        const initialEdges: Edge[] = [];

        // ODPS v1.0.0: Create a map of contractId -> {productId, outputPortId}
        const contractToOutputPort = new Map<string, {productId: string, portId: string}[]>();

        validProducts.forEach((product) => {
            if (Array.isArray(product.outputPorts) && product.id) {
                product.outputPorts.forEach((outputPort, index) => {
                    if (outputPort?.contractId) {
                        // Use port.id if available, otherwise use port.name or generate from index
                        const portId = (outputPort as any).id || outputPort.name || `output-${index}`;
                        const entries = contractToOutputPort.get(outputPort.contractId) || [];
                        entries.push({ productId: product.id!, portId });
                        contractToOutputPort.set(outputPort.contractId, entries);
                    }
                });
            }
        });

        // ODPS v1.0.0: Match input ports to output ports via contractId
        validProducts.forEach((product) => {
            if (Array.isArray(product.inputPorts) && product.id) {
                product.inputPorts.forEach((inputPort, index) => {
                    if (inputPort?.contractId) {
                        // Use port.id if available, otherwise use port.name or generate from index
                        const inputPortId = (inputPort as any).id || inputPort.name || `input-${index}`;

                        // Find output ports with matching contractId
                        const sourceOutputPorts = contractToOutputPort.get(inputPort.contractId);

                        if (sourceOutputPorts && sourceOutputPorts.length > 0) {
                            // Create edge from each matching output port
                            sourceOutputPorts.forEach((source) => {
                                // Don't create self-loops
                                if (source.productId !== product.id) {
                                    const edgeId = `e-${source.productId}-${source.portId}-${product.id}-${inputPortId}`;
                                    initialEdges.push({
                                        id: edgeId,
                                        source: source.productId,
                                        target: product.id!,
                                        sourceHandle: source.portId,
                                        targetHandle: inputPortId,
                                        type: 'smoothstep',
                                        markerEnd: { type: MarkerType.ArrowClosed },
                                        animated: true,
                                    });
                                }
                            });
                        }
                    }
                });
            }
        });

        // Use only product nodes (no external sources in ODPS v1.0.0)
        const allInitialNodes = productNodes;

        // Pass 2: Apply layout to ALL nodes and edges
        return getLayoutedElements(allInitialNodes, initialEdges);

    }, [products, navigate]);

    // Reinstate state hooks for controlled component
    const [nodes, _setNodes, onNodesChange] = useNodesState(initialElements.nodes);
    const [edges, _setEdges, onEdgesChange] = useEdgesState(initialElements.edges);

    const tableButtonVariant = viewMode === 'table' ? 'secondary' : 'ghost';
    const graphButtonVariant = viewMode === 'graph' ? 'secondary' : 'ghost';

    return (
        <div className="h-[calc(100vh-300px)] w-full border rounded-lg relative" style={{ minHeight: '600px' }}>
            <div className="absolute top-2 right-2 z-10 flex items-center gap-1 border rounded-md p-0.5 bg-background/80 backdrop-blur-sm">
                <Button
                    variant={tableButtonVariant}
                    size="sm"
                    onClick={() => setViewMode('table')}
                    className="h-8 px-2"
                    title="Switch to Table View"
                >
                    <Table className="h-4 w-4" />
                </Button>
                <Button
                    variant={graphButtonVariant}
                    size="sm"
                    onClick={() => setViewMode('graph')}
                    className="h-8 px-2"
                    title="Switch to Graph View"
                    disabled
                >
                    <Workflow className="h-4 w-4" />
                </Button>
            </div>
            <TooltipProvider delayDuration={100}>
                <ReactFlow
                    nodes={nodes}
                    edges={edges}
                    onNodesChange={onNodesChange}
                    onEdgesChange={onEdgesChange}
                    nodeTypes={nodeTypes}
                    fitView
                    attributionPosition="bottom-left"
                     defaultEdgeOptions={{
                        style: {
                            strokeWidth: 1.5,
                            stroke: isDarkMode ? '#94a3b8' : '#888'
                        },
                        markerEnd: {
                            type: MarkerType.ArrowClosed,
                            color: isDarkMode ? '#94a3b8' : '#888'
                        },
                    }}
                    nodesDraggable={true}
                    nodesConnectable={false}
                    elementsSelectable={false}
                >
                    <Controls />
                    <Background color={isDarkMode ? '#334155' : '#e2e8f0'} gap={16} />
                </ReactFlow>
            </TooltipProvider>
        </div>
    );
};

export default DataProductGraphView; 