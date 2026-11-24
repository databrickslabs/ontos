import React, { useCallback, useEffect, useMemo } from 'react';
import ReactFlow, {
  Node,
  Edge,
  MarkerType,
  Position,
  Handle,
  ReactFlowProvider,
  useReactFlow,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { useNavigate } from 'react-router-dom';
import { DataDomain } from '@/types/data-domain';
import { Card } from '@/components/ui/card'; // Simple card for node

interface DataDomainMiniGraphProps {
  currentDomain: DataDomain; // Full current domain for its details
  onNodeClick?: (domainId: string) => void; // Optional override for click handling
}

const nodeWidth = 150;
const nodeHeight = 60;
const horizontalNodeSpacing = 50; // General horizontal spacing for simple layout
const horizontalChildSpacing = 20; // Spacing between horizontal children in Christmas tree
const verticalLevelSpacing = 50;   // Spacing between parent/current/children levels
const fixedPadding = 20;   // Overall padding for the graph canvas (renamed from fixedVerticalPadding)

const CustomNode = ({ data }: { data: { label: string; domainId: string; onClick: (id: string) => void, isCurrent?: boolean } }) => (
  <Card 
    className={`p-2 w-[${nodeWidth}px] h-[${nodeHeight}px] flex items-center justify-center text-center text-sm shadow-md hover:shadow-lg cursor-pointer ${data.isCurrent ? 'bg-primary/10 border-primary' : 'bg-card'}`}
    onClick={() => data.onClick(data.domainId)}
  >
    <Handle type="target" position={Position.Top} id="target-top" style={{ background: 'transparent', border: 'none' }} />
    <Handle type="target" position={Position.Left} id="target-left" style={{ background: 'transparent', border: 'none' }} />
    {data.label}
    <Handle type="source" position={Position.Bottom} id="source-bottom" style={{ background: 'transparent', border: 'none' }} />
    <Handle type="source" position={Position.Right} id="source-right" style={{ background: 'transparent', border: 'none' }} />
  </Card>
);

const nodeTypes = { custom: CustomNode };

// Helper to compute nodes and edges from domain data
function computeNodesAndEdges(
  currentDomain: DataDomain,
  handleNodeClick: (id: string) => void
): { nodes: Node[]; edges: Edge[] } {
  const newNodes: Node[] = [];
  const newEdges: Edge[] = [];
  
  const parentInfo = currentDomain.parent_info;
  const childrenInfo = currentDomain.children_info || [];
  const numChildren = childrenInfo.length;

  // Layout decision
  const isSimpleHorizontalLayout = 
    (parentInfo && numChildren === 0) ||      // P-C
    (!parentInfo && numChildren <= 1) ||     // C or C-S
    (parentInfo && numChildren === 1);       // P-C-S

  if (isSimpleHorizontalLayout) {
    // --- Simple Horizontal Layout ---
    let currentX = fixedPadding;
    const yPos = fixedPadding;

    // Parent Node (if exists)
    if (parentInfo) {
      newNodes.push({
        id: parentInfo.id,
        type: 'custom',
        data: { label: parentInfo.name, domainId: parentInfo.id, onClick: handleNodeClick },
        position: { x: currentX, y: yPos },
      });
      currentX += nodeWidth + horizontalNodeSpacing;
    }

    // Current Domain Node
    newNodes.push({
      id: currentDomain.id,
      type: 'custom',
      data: { label: currentDomain.name, domainId: currentDomain.id, onClick: handleNodeClick, isCurrent: true },
      position: { x: currentX, y: yPos },
    });
    
    if (parentInfo) {
      newEdges.push({
        id: `e-${parentInfo.id}-${currentDomain.id}`,
        source: parentInfo.id,
        target: currentDomain.id,
        sourceHandle: 'source-right',
        targetHandle: 'target-left',
      });
    }
    currentX += nodeWidth + horizontalNodeSpacing;

    // Single Child Node (if exists)
    if (numChildren === 1) {
      const child = childrenInfo[0];
      newNodes.push({
        id: child.id,
        type: 'custom',
        data: { label: child.name, domainId: child.id, onClick: handleNodeClick },
        position: { x: currentX, y: yPos },
      });
      newEdges.push({
        id: `e-${currentDomain.id}-${child.id}`,
        source: currentDomain.id,
        target: child.id,
        sourceHandle: 'source-right',
        targetHandle: 'target-left',
      });
    }
  } else {
    // --- Christmas Tree Layout (Parent top-center, Current mid-center, Children bottom-row) ---
    let currentY = fixedPadding;

    const childrenRowActualWidth = numChildren > 0 ? (numChildren * nodeWidth) + Math.max(0, (numChildren - 1)) * horizontalChildSpacing : 0;
    const parentCurrentRowActualWidth = nodeWidth;
    const maxContentWidth = Math.max(parentCurrentRowActualWidth, childrenRowActualWidth, nodeWidth);

    const centralX = (maxContentWidth - nodeWidth) / 2;
    const childrenRowStartX = (maxContentWidth - childrenRowActualWidth) / 2;
    
    // Parent Node (Top Center)
    if (parentInfo) {
      newNodes.push({
        id: parentInfo.id,
        type: 'custom',
        data: { label: parentInfo.name, domainId: parentInfo.id, onClick: handleNodeClick },
        position: { x: centralX, y: currentY },
      });
      currentY += nodeHeight + verticalLevelSpacing;
    }

    // Current Domain Node (Middle Center)
    const actualCurrentY = currentY;
    newNodes.push({
      id: currentDomain.id,
      type: 'custom',
      data: { label: currentDomain.name, domainId: currentDomain.id, onClick: handleNodeClick, isCurrent: true },
      position: { x: centralX, y: actualCurrentY },
    });
    
    if (parentInfo) {
      newEdges.push({
        id: `e-${parentInfo.id}-${currentDomain.id}`,
        source: parentInfo.id,
        target: currentDomain.id,
        sourceHandle: 'source-bottom',
        targetHandle: 'target-top',
      });
    }

    // Children Nodes (Bottom Row, Horizontal, Centered)
    if (numChildren > 0) {
      const childrenDisplayY = actualCurrentY + nodeHeight + verticalLevelSpacing;
      childrenInfo.forEach((child, index) => {
        newNodes.push({
          id: child.id,
          type: 'custom',
          data: { label: child.name, domainId: child.id, onClick: handleNodeClick },
          position: { 
            x: childrenRowStartX + index * (nodeWidth + horizontalChildSpacing), 
            y: childrenDisplayY 
          }, 
        });
        newEdges.push({
          id: `e-${currentDomain.id}-${child.id}`,
          source: currentDomain.id,
          target: child.id,
          sourceHandle: 'source-bottom',
          targetHandle: 'target-top',
        });
      });
    }
  }
  
  return { nodes: newNodes, edges: newEdges };
}

// Inner component that uses useReactFlow to trigger fitView after nodes update
const DataDomainMiniGraphInner: React.FC<DataDomainMiniGraphProps> = ({ currentDomain, onNodeClick }) => {
  const navigate = useNavigate();
  const { fitView } = useReactFlow();

  // Stable reference: `nodes` below depends on it, and every new `nodes` array re-runs
  // fitView (so each re-render of the host page restarted the fit animation, #1592).
  const handleNodeClick = useCallback((domainId: string) => {
    if (onNodeClick) {
      onNodeClick(domainId);
    } else {
      navigate(`/settings/data-domains/${domainId}`);
    }
  }, [onNodeClick, navigate]);

  // Compute nodes and edges from domain data
  const { nodes, edges } = useMemo(
    () => computeNodesAndEdges(currentDomain, handleNodeClick),
    [currentDomain, handleNodeClick]
  );

  // Trigger fitView after nodes are rendered
  useEffect(() => {
    // Small delay to ensure nodes are rendered before fitting
    const timer = setTimeout(() => {
      fitView({ padding: 0.05, duration: 200 });
    }, 50);
    return () => clearTimeout(timer);
  }, [nodes, fitView]);

  // Detect dark mode
  const isDarkMode = document.documentElement.classList.contains('dark');

  const defaultEdgeOptions = {
    markerEnd: {
      type: MarkerType.ArrowClosed,
      width: 15,
      height: 15,
      color: isDarkMode ? '#94a3b8' : '#64748b'
    },
    style: {
      stroke: isDarkMode ? '#94a3b8' : '#64748b',
      strokeWidth: 1.5
    }
  };

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      defaultEdgeOptions={defaultEdgeOptions}
      fitView
      fitViewOptions={{ padding: 0.05 }}
      proOptions={{ hideAttribution: true }}
      nodesDraggable={false}
      nodesConnectable={false}
      zoomOnScroll={false}
      panOnDrag={false}
      selectNodesOnDrag={false}
      minZoom={0.1}
      maxZoom={1.5}
    />
  );
};

// Fixed height for consistent layout
const graphHeight = 220;

export const DataDomainMiniGraph: React.FC<DataDomainMiniGraphProps> = ({ currentDomain, onNodeClick }) => {
  return (
    <div style={{ height: graphHeight, margin: 'auto' }} className="border rounded-lg overflow-hidden bg-muted/20 w-full">
      <ReactFlowProvider>
        <DataDomainMiniGraphInner currentDomain={currentDomain} onNodeClick={onNodeClick} />
      </ReactFlowProvider>
    </div>
  );
}; 