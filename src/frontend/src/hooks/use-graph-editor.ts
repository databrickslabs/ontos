/**
 * Graph Editor state management hook.
 *
 * Manages the lifecycle of graph nodes and edges:
 * - Original data from backend
 * - User-created items (NEW status, not yet saved)
 * - Modifications to existing items (MODIFIED status)
 * - Deleted items
 * - Selection and edge-creation mode
 */

import { useState, useCallback, useMemo } from 'react';
import type { GraphNode, GraphEdge, GraphData } from '@/types/graph-explorer';
import { ChangeStatus } from '@/types/graph-explorer';

interface UseGraphEditorOptions {
  initialData: GraphData;
}

interface UseGraphEditorReturn {
  graphData: GraphData;
  userCreatedNodes: GraphNode[];
  userCreatedEdges: GraphEdge[];
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  isEdgeCreateMode: boolean;
  edgeCreateSourceId: string | null;
  addNode: (node: Omit<GraphNode, 'status'>) => void;
  updateNode: (nodeId: string, updates: Partial<GraphNode>) => void;
  deleteNode: (nodeId: string) => void;
  addEdge: (edge: Omit<GraphEdge, 'status'>) => void;
  updateEdge: (edgeId: string, updates: Partial<GraphEdge>) => void;
  deleteEdge: (edgeId: string) => void;
  selectNode: (nodeId: string | null) => void;
  selectEdge: (edgeId: string | null) => void;
  startEdgeCreateMode: () => void;
  cancelEdgeCreateMode: () => void;
  handleNodeClickForEdge: (nodeId: string) => { sourceId: string; targetId: string } | null;
  markItemsAsSaved: (nodeIds: string[], edgeIds: string[]) => void;
  clearModifications: (nodeIds: string[], edgeIds: string[]) => void;
  resetToInitialData: (newData: GraphData) => void;
  getModifiedNodes: () => GraphNode[];
  getModifiedEdges: () => GraphEdge[];
  getStats: () => {
    totalNodes: number;
    totalEdges: number;
    newNodes: number;
    newEdges: number;
    modifiedNodes: number;
    modifiedEdges: number;
  };
}

export function useGraphEditor({ initialData }: UseGraphEditorOptions): UseGraphEditorReturn {
  const [originalData, setOriginalData] = useState<GraphData>(initialData);
  const [userCreatedNodes, setUserCreatedNodes] = useState<GraphNode[]>([]);
  const [userCreatedEdges, setUserCreatedEdges] = useState<GraphEdge[]>([]);
  const [modifiedNodes, setModifiedNodes] = useState<Map<string, Partial<GraphNode>>>(new Map());
  const [modifiedEdges, setModifiedEdges] = useState<Map<string, Partial<GraphEdge>>>(new Map());
  const [deletedNodeIds, setDeletedNodeIds] = useState<Set<string>>(new Set());
  const [deletedEdgeIds, setDeletedEdgeIds] = useState<Set<string>>(new Set());
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [isEdgeCreateMode, setIsEdgeCreateMode] = useState(false);
  const [edgeCreateSourceId, setEdgeCreateSourceId] = useState<string | null>(null);

  // Note: Don't sync initialData via useEffect - it causes infinite loops
  // when callers pass a new object literal each render.
  // Use resetToInitialData() explicitly when new data arrives from the server.

  // Compute combined graph data (original + modifications)
  const graphData: GraphData = useMemo(
    () => ({
      nodes: [
        ...originalData.nodes
          .filter((node) => !deletedNodeIds.has(node.id))
          .map((node) => {
            const modifications = modifiedNodes.get(node.id);
            return modifications ? { ...node, ...modifications } : node;
          }),
        ...userCreatedNodes.filter((node) => !deletedNodeIds.has(node.id)),
      ],
      edges: [
        ...originalData.edges
          .filter((edge) => !deletedEdgeIds.has(edge.id))
          .map((edge) => {
            const modifications = modifiedEdges.get(edge.id);
            return modifications ? { ...edge, ...modifications } : edge;
          }),
        ...userCreatedEdges.filter((edge) => !deletedEdgeIds.has(edge.id)),
      ],
    }),
    [originalData, deletedNodeIds, modifiedNodes, userCreatedNodes, deletedEdgeIds, modifiedEdges, userCreatedEdges],
  );

  const addNode = useCallback((node: Omit<GraphNode, 'status'>) => {
    const newNode: GraphNode = { ...node, status: ChangeStatus.NEW };
    setUserCreatedNodes((prev) => [...prev, newNode]);
  }, []);

  const updateNode = useCallback(
    (nodeId: string, updates: Partial<GraphNode>) => {
      const userNodeIndex = userCreatedNodes.findIndex((n) => n.id === nodeId);
      if (userNodeIndex !== -1) {
        setUserCreatedNodes((prev) =>
          prev.map((node, idx) => (idx === userNodeIndex ? { ...node, ...updates } : node)),
        );
      } else {
        setModifiedNodes((prev) => {
          const newMap = new Map(prev);
          const existing = newMap.get(nodeId) || {};
          newMap.set(nodeId, { ...existing, ...updates });
          return newMap;
        });
      }
    },
    [userCreatedNodes],
  );

  const deleteNode = useCallback(
    (nodeId: string) => {
      const isUserCreated = userCreatedNodes.some((n) => n.id === nodeId);
      if (isUserCreated) {
        setUserCreatedNodes((prev) => prev.filter((n) => n.id !== nodeId));
        setUserCreatedEdges((prev) => prev.filter((e) => e.source !== nodeId && e.target !== nodeId));
      } else {
        setDeletedNodeIds((prev) => new Set(prev).add(nodeId));
        const connectedEdges = originalData.edges
          .filter((e) => e.source === nodeId || e.target === nodeId)
          .map((e) => e.id);
        setDeletedEdgeIds((prev) => {
          const newSet = new Set(prev);
          connectedEdges.forEach((id) => newSet.add(id));
          return newSet;
        });
      }
      if (selectedNodeId === nodeId) setSelectedNodeId(null);
    },
    [userCreatedNodes, originalData.edges, selectedNodeId],
  );

  const addEdge = useCallback((edge: Omit<GraphEdge, 'status'>) => {
    const newEdge: GraphEdge = { ...edge, status: ChangeStatus.NEW };
    setUserCreatedEdges((prev) => [...prev, newEdge]);
  }, []);

  const updateEdge = useCallback(
    (edgeId: string, updates: Partial<GraphEdge>) => {
      const userEdgeIndex = userCreatedEdges.findIndex((e) => e.id === edgeId);
      if (userEdgeIndex !== -1) {
        setUserCreatedEdges((prev) =>
          prev.map((edge, idx) => (idx === userEdgeIndex ? { ...edge, ...updates } : edge)),
        );
      } else {
        setModifiedEdges((prev) => {
          const newMap = new Map(prev);
          const existing = newMap.get(edgeId) || {};
          newMap.set(edgeId, { ...existing, ...updates });
          return newMap;
        });
      }
    },
    [userCreatedEdges],
  );

  const deleteEdge = useCallback(
    (edgeId: string) => {
      const isUserCreated = userCreatedEdges.some((e) => e.id === edgeId);
      if (isUserCreated) {
        setUserCreatedEdges((prev) => prev.filter((e) => e.id !== edgeId));
      } else {
        setDeletedEdgeIds((prev) => new Set(prev).add(edgeId));
      }
      if (selectedEdgeId === edgeId) setSelectedEdgeId(null);
    },
    [userCreatedEdges, selectedEdgeId],
  );

  const selectNode = useCallback((nodeId: string | null) => {
    setSelectedNodeId(nodeId);
    setSelectedEdgeId(null);
  }, []);

  const selectEdge = useCallback((edgeId: string | null) => {
    setSelectedEdgeId(edgeId);
    setSelectedNodeId(null);
  }, []);

  const startEdgeCreateMode = useCallback(() => {
    setIsEdgeCreateMode(true);
    setEdgeCreateSourceId(null);
  }, []);

  const cancelEdgeCreateMode = useCallback(() => {
    setIsEdgeCreateMode(false);
    setEdgeCreateSourceId(null);
  }, []);

  const handleNodeClickForEdge = useCallback(
    (nodeId: string): { sourceId: string; targetId: string } | null => {
      if (!isEdgeCreateMode) return null;
      if (!edgeCreateSourceId) {
        setEdgeCreateSourceId(nodeId);
        return null;
      } else {
        const sourceId = edgeCreateSourceId;
        const targetId = nodeId;
        setIsEdgeCreateMode(false);
        setEdgeCreateSourceId(null);
        return { sourceId, targetId };
      }
    },
    [isEdgeCreateMode, edgeCreateSourceId],
  );

  const markItemsAsSaved = useCallback((nodeIds: string[], edgeIds: string[]) => {
    let savedNodes: GraphNode[] = [];
    let savedEdges: GraphEdge[] = [];

    setUserCreatedNodes((prev) => {
      savedNodes = prev.filter((n) => nodeIds.includes(n.id));
      return prev.filter((n) => !nodeIds.includes(n.id));
    });

    setUserCreatedEdges((prev) => {
      savedEdges = prev.filter((e) => edgeIds.includes(e.id));
      return prev.filter((e) => !edgeIds.includes(e.id));
    });

    if (savedNodes.length > 0 || savedEdges.length > 0) {
      setOriginalData((data) => ({
        nodes: [...data.nodes, ...savedNodes.map((n) => ({ ...n, status: ChangeStatus.EXISTING }))],
        edges: [...data.edges, ...savedEdges.map((e) => ({ ...e, status: ChangeStatus.EXISTING }))],
      }));
    }
  }, []);

  const resetToInitialData = useCallback((newData: GraphData) => {
    setOriginalData(newData);
    setUserCreatedNodes([]);
    setUserCreatedEdges([]);
    setModifiedNodes(new Map());
    setModifiedEdges(new Map());
    setDeletedNodeIds(new Set());
    setDeletedEdgeIds(new Set());
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
  }, []);

  const clearModifications = useCallback((nodeIds: string[], edgeIds: string[]) => {
    setModifiedNodes((prev) => {
      const newMap = new Map(prev);
      nodeIds.forEach((id) => newMap.delete(id));
      return newMap;
    });
    setModifiedEdges((prev) => {
      const newMap = new Map(prev);
      edgeIds.forEach((id) => newMap.delete(id));
      return newMap;
    });
  }, []);

  const getModifiedNodes = useCallback((): GraphNode[] => {
    return originalData.nodes
      .filter((node) => modifiedNodes.has(node.id) && !deletedNodeIds.has(node.id))
      .map((node) => {
        const modifications = modifiedNodes.get(node.id);
        return modifications ? { ...node, ...modifications } : node;
      });
  }, [originalData.nodes, modifiedNodes, deletedNodeIds]);

  const getModifiedEdges = useCallback((): GraphEdge[] => {
    return originalData.edges
      .filter((edge) => modifiedEdges.has(edge.id) && !deletedEdgeIds.has(edge.id))
      .map((edge) => {
        const modifications = modifiedEdges.get(edge.id);
        return modifications ? { ...edge, ...modifications } : edge;
      });
  }, [originalData.edges, modifiedEdges, deletedEdgeIds]);

  const getStats = useCallback(() => {
    return {
      totalNodes: graphData.nodes.length,
      totalEdges: graphData.edges.length,
      newNodes: userCreatedNodes.filter((n) => !deletedNodeIds.has(n.id)).length,
      newEdges: userCreatedEdges.filter((e) => !deletedEdgeIds.has(e.id)).length,
      modifiedNodes: modifiedNodes.size,
      modifiedEdges: modifiedEdges.size,
    };
  }, [graphData, userCreatedNodes, userCreatedEdges, deletedNodeIds, deletedEdgeIds, modifiedNodes, modifiedEdges]);

  return {
    graphData,
    userCreatedNodes: userCreatedNodes.filter((n) => !deletedNodeIds.has(n.id)),
    userCreatedEdges: userCreatedEdges.filter((e) => !deletedEdgeIds.has(e.id)),
    selectedNodeId,
    selectedEdgeId,
    isEdgeCreateMode,
    edgeCreateSourceId,
    addNode,
    updateNode,
    deleteNode,
    addEdge,
    updateEdge,
    deleteEdge,
    selectNode,
    selectEdge,
    startEdgeCreateMode,
    cancelEdgeCreateMode,
    handleNodeClickForEdge,
    markItemsAsSaved,
    clearModifications,
    resetToInitialData,
    getModifiedNodes,
    getModifiedEdges,
    getStats,
  };
}
