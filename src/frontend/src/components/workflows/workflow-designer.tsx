import { useState, useCallback, useMemo, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import ReactFlow, {
  Node,
  Edge,
  Connection,
  Controls,
  Background,
  MiniMap,
  useNodesState,
  useEdgesState,
  MarkerType,
  Panel,
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  type EdgeProps,
} from 'reactflow';
import 'reactflow/dist/style.css';
import dagre from 'dagre';

import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { Button } from '@/components/ui/button';
// Card components commented out - not currently used
// import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Checkbox } from '@/components/ui/checkbox';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Separator } from '@/components/ui/separator';
import { Badge } from '@/components/ui/badge';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { 
  Save, 
  ArrowLeft, 
  // Plus - unused
  Trash2, 
  Loader2,
  Shield,
  Bell,
  Tag,
  GitBranch,
  Code,
  CheckCircle,
  XCircle,
  UserCheck,
  // Play - unused
  ClipboardCheck,
  FileSearch,
  Globe,
  MessageSquare,
  Zap,
} from 'lucide-react';

import {
  TriggerNode,
  ValidationNode,
  ApprovalNode,
  NotificationNode,
  UserActionNode,
  DefaultStepNode,
  AssignTagNode,
  ConditionalNode,
  ScriptNode,
  EndNode,
  PolicyCheckNode,
  CreateAssetReviewNode,
  WebhookNode,
  EntityActionNode,
} from './workflow-nodes';

import type {
  ProcessWorkflow,
  ProcessWorkflowCreate,
  ProcessWorkflowUpdate,
  // WorkflowStep - unused
  WorkflowStepCreate,
  StepType,
  TriggerType,
  EntityType,
  StepTypeSchema,
  CompliancePolicyRef,
  HttpConnectionRef,
} from '@/types/process-workflow';
import { 
  getTriggerTypeLabel, 
  getEntityTypeLabel, 
  ALL_TRIGGER_TYPES, 
  ALL_ENTITY_TYPES 
} from '@/lib/workflow-labels';

// Node types registry (default = fallback for unknown step_type e.g. generate_pdf)
const nodeTypes = {
  trigger: TriggerNode,
  validation: ValidationNode,
  approval: ApprovalNode,
  notification: NotificationNode,
  user_action: UserActionNode,
  assign_tag: AssignTagNode,
  conditional: ConditionalNode,
  script: ScriptNode,
  pass: EndNode,
  fail: EndNode,
  policy_check: PolicyCheckNode,
  create_asset_review: CreateAssetReviewNode,
  webhook: WebhookNode,
  entity_action: EntityActionNode,
  default: DefaultStepNode,
};

// Custom edge with visible delete button when selected
function DeletableEdge({
  id, sourceX, sourceY, targetX, targetY,
  sourcePosition, targetPosition, style, label, labelStyle, markerEnd, selected, data,
}: EdgeProps) {
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition,
  });

  return (
    <>
      <BaseEdge path={edgePath} markerEnd={markerEnd} style={style} />
      <EdgeLabelRenderer>
        <div
          style={{
            position: 'absolute',
            transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
            pointerEvents: 'all',
          }}
          className="nodrag nopan flex items-center gap-1"
        >
          {label && (
            <span className="text-xs font-medium" style={{ ...labelStyle, color: (labelStyle as any)?.fill || (labelStyle as any)?.color }}>
              {label}
            </span>
          )}
          {selected && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                data?.onDelete?.(id);
              }}
              className="flex items-center justify-center w-5 h-5 rounded-full
                bg-red-500 hover:bg-red-600 text-white text-xs leading-none
                shadow-sm transition-colors dark:bg-red-600 dark:hover:bg-red-700"
              title="Delete connection"
            >
              ✕
            </button>
          )}
        </div>
      </EdgeLabelRenderer>
    </>
  );
}

// Edge types registry
const edgeTypes = {
  deletable: DeletableEdge,
};

// Layout helper
const getLayoutedElements = (nodes: Node[], edges: Edge[], direction = 'TB') => {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  dagreGraph.setGraph({ rankdir: direction, nodesep: 50, ranksep: 80 });

  const nodeWidth = 250;
  const nodeHeight = 100;

  nodes.forEach((node) => {
    dagreGraph.setNode(node.id, { width: nodeWidth, height: nodeHeight });
  });

  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  dagre.layout(dagreGraph);

  const layoutedNodes = nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    return {
      ...node,
      position: {
        x: nodeWithPosition.x - nodeWidth / 2,
        y: nodeWithPosition.y - nodeHeight / 2,
      },
    };
  });

  return { nodes: layoutedNodes, edges };
};

// Convert workflow to React Flow elements
const workflowToElements = (
  workflow: ProcessWorkflow | null,
  rolesMap: Record<string, string> = {}
) => {
  if (!workflow) return { nodes: [], edges: [] };

  const nodes: Node[] = [];
  const edges: Edge[] = [];

  // Add trigger node
  nodes.push({
    id: 'trigger',
    type: 'trigger',
    data: { trigger: workflow.trigger },
    position: { x: 0, y: 0 },
  });

  // Add step nodes (use 'default' for unregistered step_type so we never get an empty box)
  const stepNodeTypes = Object.keys(nodeTypes);
  workflow.steps.forEach((step, index) => {
    const nodeType = stepNodeTypes.includes(step.step_type) ? step.step_type : 'default';
    nodes.push({
      id: step.step_id,
      type: nodeType,
      data: { step, rolesMap },
      position: step.position || { x: 0, y: (index + 1) * 120 },
    });
  });

  // Connect trigger to first step
  if (workflow.steps.length > 0) {
    edges.push({
      id: 'trigger-to-first',
      source: 'trigger',
      target: workflow.steps[0].step_id,
      type: 'deletable',
      markerEnd: { type: MarkerType.ArrowClosed },
    });
  }

  // Add step edges
  workflow.steps.forEach((step) => {
    if (step.on_pass) {
      edges.push({
        id: `${step.step_id}-pass`,
        source: step.step_id,
        sourceHandle: 'pass',
        target: step.on_pass,
        type: 'deletable',
        label: 'Pass',
        labelStyle: { fill: '#22c55e', fontWeight: 500 },
        markerEnd: { type: MarkerType.ArrowClosed },
        style: { stroke: '#22c55e' },
      });
    }
    if (step.on_fail) {
      edges.push({
        id: `${step.step_id}-fail`,
        source: step.step_id,
        sourceHandle: 'fail',
        target: step.on_fail,
        type: 'deletable',
        label: 'Fail',
        labelStyle: { fill: '#ef4444', fontWeight: 500 },
        markerEnd: { type: MarkerType.ArrowClosed },
        style: { stroke: '#ef4444' },
      });
    }
  });

  return getLayoutedElements(nodes, edges);
};

interface WorkflowDesignerProps {
  workflowId?: string;
}

export default function WorkflowDesigner({ workflowId }: WorkflowDesignerProps) {
  const navigate = useNavigate();
  const params = useParams();
  const id = workflowId || params.workflowId;
  const isNew = !id || id === 'new';
  
  const { get, post, put } = useApi();
  const { toast } = useToast();
  const { t } = useTranslation(['common']);
  
  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((state) => state.setDynamicTitle);

  const [workflow, setWorkflow] = useState<ProcessWorkflow | null>(null);
  const [isLoading, setIsLoading] = useState(!isNew);
  const [isSaving, setIsSaving] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [_stepTypes, setStepTypes] = useState<StepTypeSchema[]>([]);
  const [compliancePolicies, setCompliancePolicies] = useState<CompliancePolicyRef[]>([]);
  const [availableRoles, setAvailableRoles] = useState<{ id: string; name: string; has_groups: boolean }[]>([]);
  const [httpConnections, setHttpConnections] = useState<HttpConnectionRef[]>([]);
  const [showDiscardDialog, setShowDiscardDialog] = useState(false);
  
  // Form state
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [triggerType, setTriggerType] = useState<TriggerType>('on_create');
  const [entityTypes, setEntityTypes] = useState<EntityType[]>(['table']);
  const [triggerFromStatus, setTriggerFromStatus] = useState('');
  const [triggerToStatus, setTriggerToStatus] = useState('');
  const [isActive, setIsActive] = useState(true);
  const [steps, setSteps] = useState<WorkflowStepCreate[]>([]);
  
  // Track initial state for dirty checking
  interface OriginalState {
    name: string;
    description: string;
    triggerType: TriggerType;
    entityTypes: EntityType[];
    isActive: boolean;
    steps: WorkflowStepCreate[];
  }
  const [originalState, setOriginalState] = useState<OriginalState | null>(null);

  // React Flow state
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChangeBase] = useEdgesState([]);

  // Wrap onEdgesChange to sync step on_pass/on_fail when edges are removed
  const onEdgesChange = useCallback((changes: import('reactflow').EdgeChange[]) => {
    onEdgesChangeBase(changes);
    for (const change of changes) {
      if (change.type === 'remove') {
        const removed = edges.find(e => e.id === change.id);
        if (removed) {
          const field = removed.sourceHandle === 'fail' ? 'on_fail' : 'on_pass';
          setSteps(prev => prev.map(s =>
            s.step_id === removed.source ? { ...s, [field]: undefined } : s
          ));
        }
      }
    }
  }, [onEdgesChangeBase, edges]);

  // Delete edge handler — removes edge and syncs step on_pass/on_fail
  const onDeleteEdge = useCallback((edgeId: string) => {
    const target = edges.find(e => e.id === edgeId);
    if (target) {
      const field = target.sourceHandle === 'fail' ? 'on_fail' : 'on_pass';
      setSteps(prev => prev.map(s =>
        s.step_id === target.source ? { ...s, [field]: undefined } : s
      ));
    }
    setEdges(prev => prev.filter(e => e.id !== edgeId));
  }, [edges, setEdges]);

  // Inject onDelete callback into every edge's data so DeletableEdge can call it
  const edgesWithDelete = useMemo(
    () => edges.map(e => ({ ...e, data: { ...e.data, onDelete: onDeleteEdge } })),
    [edges, onDeleteEdge],
  );

  // Compute dirty state - compare current values to original
  const isDirty = useMemo(() => {
    if (!originalState) {
      // For new workflows, dirty if any content exists
      return isNew && (name.trim() !== '' || description.trim() !== '' || steps.length > 0);
    }
    
    // Compare each field
    if (name !== originalState.name) return true;
    if (description !== originalState.description) return true;
    if (triggerType !== originalState.triggerType) return true;
    if (isActive !== originalState.isActive) return true;
    
    // Compare entity types
    if (entityTypes.length !== originalState.entityTypes.length) return true;
    if (!entityTypes.every(et => originalState.entityTypes.includes(et))) return true;
    
    // Compare steps (deep comparison via JSON)
    if (JSON.stringify(steps) !== JSON.stringify(originalState.steps)) return true;
    
    return false;
  }, [originalState, name, description, triggerType, entityTypes, isActive, steps, isNew]);

  // Set up breadcrumbs
  useEffect(() => {
    setStaticSegments([
      { label: 'Workflows', path: '/workflows' },
    ]);
    setDynamicTitle(isNew ? 'New Workflow' : 'Loading...');
    
    return () => {
      setStaticSegments([]);
      setDynamicTitle(null);
    };
  }, [setStaticSegments, setDynamicTitle, isNew]);

  // Update breadcrumb title when name changes
  useEffect(() => {
    if (name) {
      setDynamicTitle(name);
    }
  }, [name, setDynamicTitle]);

  // Warn user when navigating away with unsaved changes (browser-level)
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (isDirty) {
        e.preventDefault();
        e.returnValue = '';  // Required for Chrome
        return '';
      }
    };

    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [isDirty]);

  // Load workflow
  useEffect(() => {
    const loadData = async () => {
      // Load step types
      try {
        const typesResponse = await get<StepTypeSchema[]>('/api/workflows/step-types');
        if (typesResponse.data) {
          setStepTypes(typesResponse.data);
        }
      } catch (error) {
        console.error('Failed to load step types:', error);
      }
      
      // Load compliance policies for policy_check step selector
      try {
        const policiesResponse = await get<CompliancePolicyRef[]>('/api/workflows/compliance-policies');
        if (policiesResponse.data && Array.isArray(policiesResponse.data)) {
          setCompliancePolicies(policiesResponse.data);
        } else {
          setCompliancePolicies([]);
        }
      } catch (error) {
        console.error('Failed to load compliance policies:', error);
        setCompliancePolicies([]);
      }
      
      // Load available roles for approval/notification step selectors
      try {
        const rolesResponse = await get<{ id: string; name: string; has_groups: boolean }[]>('/api/workflows/roles');
        if (rolesResponse.data && Array.isArray(rolesResponse.data)) {
          setAvailableRoles(rolesResponse.data);
        } else {
          setAvailableRoles([]);
        }
      } catch (error) {
        console.error('Failed to load roles:', error);
        setAvailableRoles([]);
      }
      
      // Load HTTP connections for webhook step selector
      try {
        const connectionsResponse = await get<HttpConnectionRef[]>('/api/workflows/http-connections');
        if (connectionsResponse.data && Array.isArray(connectionsResponse.data)) {
          setHttpConnections(connectionsResponse.data);
        } else {
          setHttpConnections([]);
        }
      } catch (error) {
        console.error('Failed to load HTTP connections:', error);
        setHttpConnections([]);
      }

      // Load workflow if editing
      if (!isNew) {
        setIsLoading(true);
        try {
          const response = await get<ProcessWorkflow>(`/api/workflows/${id}`);
          if (response.data) {
            setWorkflow(response.data);
            setName(response.data.name);
            setDynamicTitle(response.data.name);
            setDescription(response.data.description || '');
            setTriggerType(response.data.trigger.type);
            setEntityTypes(response.data.trigger.entity_types);
            setTriggerFromStatus(response.data.trigger.from_status || '');
            setTriggerToStatus(response.data.trigger.to_status || '');
            setIsActive(response.data.is_active);
            const loadedSteps = response.data.steps.map(s => ({
              step_id: s.step_id,
              name: s.name,
              step_type: s.step_type,
              config: s.config,
              on_pass: s.on_pass,
              on_fail: s.on_fail,
              order: s.order,
              position: s.position,
            }));
            setSteps(loadedSteps);
            
            // Store original state for dirty tracking
            setOriginalState({
              name: response.data.name,
              description: response.data.description || '',
              triggerType: response.data.trigger.type,
              entityTypes: [...response.data.trigger.entity_types],
              isActive: response.data.is_active,
              steps: loadedSteps.map(s => ({ ...s })),
            });
            
            // Convert to flow elements - rolesMap will be empty initially, but nodes will be updated
            // when availableRoles loads (via updateNodesWithRoles effect)
            const { nodes: flowNodes, edges: flowEdges } = workflowToElements(response.data, {});
            setNodes(flowNodes);
            setEdges(flowEdges);
          }
        } catch (error) {
          toast({
            title: 'Error',
            description: 'Failed to load workflow',
            variant: 'destructive',
          });
        } finally {
          setIsLoading(false);
        }
      } else {
        // Initialize with trigger node for new workflow
        setNodes([{
          id: 'trigger',
          type: 'trigger',
          data: { trigger: { type: 'on_create', entity_types: ['table'] } },
          position: { x: 100, y: 50 },
        }]);
        
        // Set original state for new workflow dirty tracking
        setOriginalState({
          name: '',
          description: '',
          triggerType: 'on_create',
          entityTypes: ['table'],
          isActive: true,
          steps: [],
        });
      }
    };

    loadData();
  }, [id, isNew, get, toast, setNodes, setEdges]);

  // Create rolesMap from availableRoles
  const rolesMap = useMemo(() => {
    const map: Record<string, string> = {};
    availableRoles.forEach(role => {
      map[role.id] = role.name;
    });
    return map;
  }, [availableRoles]);

  // Update node data when rolesMap changes
  useEffect(() => {
    if (Object.keys(rolesMap).length > 0) {
      setNodes(prevNodes => prevNodes.map(node => {
        if (node.type === 'trigger') return node;
        return {
          ...node,
          data: { ...node.data, rolesMap }
        };
      }));
    }
  }, [rolesMap, setNodes]);

  // Handle node selection
  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNodeId(node.id);
  }, []);

  // Handle edge reconnection (drag an existing edge endpoint to a different node)
  const onReconnect = useCallback((oldEdge: Edge, newConnection: Connection) => {
    if (!newConnection.source || !newConnection.target) return;
    const handleType = oldEdge.sourceHandle || 'pass';
    const isPass = handleType !== 'fail';

    // Remove old edge and add reconnected edge
    setEdges(prev => {
      const filtered = prev.filter(e => e.id !== oldEdge.id);
      const reconnectedEdge: Edge = {
        id: `${newConnection.source}-${handleType}-to-${newConnection.target}`,
        source: newConnection.source!,
        sourceHandle: handleType,
        target: newConnection.target!,
        type: 'deletable',
        label: isPass ? 'Pass' : 'Fail',
        labelStyle: { fill: isPass ? '#22c55e' : '#ef4444', fontWeight: 500 },
        markerEnd: { type: MarkerType.ArrowClosed },
        style: { stroke: isPass ? '#22c55e' : '#ef4444' },
      };
      return [...filtered, reconnectedEdge];
    });

    // Clear old target, set new target in step data
    setSteps(prev => prev.map(s => {
      if (s.step_id === oldEdge.source) {
        return { ...s, [isPass ? 'on_pass' : 'on_fail']: newConnection.target };
      }
      return s;
    }));
  }, [setEdges]);

  // Handle manual edge creation (drag from handle to handle)
  const onConnect = useCallback((connection: Connection) => {
    if (!connection.source || !connection.target) return;
    const handleType = connection.sourceHandle || 'pass';
    const isPass = handleType !== 'fail';

    // Remove any existing edge from the same source handle
    setEdges(prev => prev.filter(e =>
      !(e.source === connection.source && e.sourceHandle === handleType)
    ));

    const newEdge: Edge = {
      id: `${connection.source}-${handleType}-to-${connection.target}`,
      source: connection.source,
      sourceHandle: handleType,
      target: connection.target,
      type: 'deletable',
      label: isPass ? 'Pass' : 'Fail',
      labelStyle: { fill: isPass ? '#22c55e' : '#ef4444', fontWeight: 500 },
      markerEnd: { type: MarkerType.ArrowClosed },
      style: { stroke: isPass ? '#22c55e' : '#ef4444' },
    };
    setEdges(prev => [...prev, newEdge]);

    // Update the step's on_pass or on_fail
    setSteps(prev => prev.map(s =>
      s.step_id === connection.source
        ? { ...s, [isPass ? 'on_pass' : 'on_fail']: connection.target }
        : s
    ));
  }, [setEdges]);

  // Add new step
  const addStep = (type: StepType) => {
    const stepId = `step-${Date.now()}`;
    const newStep: WorkflowStepCreate = {
      step_id: stepId,
      name: `New ${type} Step`,
      step_type: type,
      config: type === 'entity_action' ? { action: 'certify' } : {},
      order: steps.length,
    };
    
    setSteps(prev => [...prev, newStep]);
    
    // Add node with rolesMap
    const newNode: Node = {
      id: stepId,
      type: type,
      data: { step: newStep, rolesMap },
      position: { x: 100, y: (nodes.length + 1) * 120 },
    };
    setNodes(prev => [...prev, newNode]);
    
    // Connect to previous step or trigger
    if (nodes.length > 0) {
      const lastNode = nodes[nodes.length - 1];
      const newEdge: Edge = {
        id: `${lastNode.id}-to-${stepId}`,
        source: lastNode.id,
        sourceHandle: lastNode.id === 'trigger' ? undefined : 'pass',
        target: stepId,
        type: 'deletable',
        markerEnd: { type: MarkerType.ArrowClosed },
      };
      setEdges(prev => [...prev, newEdge]);
      
      // Update previous step's on_pass
      if (lastNode.id !== 'trigger') {
        setSteps(prev => prev.map(s => 
          s.step_id === lastNode.id ? { ...s, on_pass: stepId } : s
        ));
      }
    }
    
    setSelectedNodeId(stepId);
  };

  // Delete step
  const deleteStep = (stepId: string) => {
    setSteps(prev => prev.filter(s => s.step_id !== stepId));
    setNodes(prev => prev.filter(n => n.id !== stepId));
    setEdges(prev => prev.filter(e => e.source !== stepId && e.target !== stepId));
    setSelectedNodeId(null);
  };

  // Update step
  const updateStep = (stepId: string, updates: Partial<WorkflowStepCreate>) => {
    setSteps(prev => prev.map(s => 
      s.step_id === stepId ? { ...s, ...updates } : s
    ));
    
    // Update node data
    setNodes(prev => prev.map(n => 
      n.id === stepId ? { ...n, data: { ...n.data, step: { ...n.data.step, ...updates } } } : n
    ));
  };

  // Save workflow
  const handleSave = async () => {
    if (!name.trim()) {
      toast({
        title: 'Validation Error',
        description: 'Workflow name is required',
        variant: 'destructive',
      });
      return;
    }

    setIsSaving(true);
    try {
      const workflowData: ProcessWorkflowCreate = {
        name,
        description,
        trigger: {
          type: triggerType,
          entity_types: entityTypes,
          ...(triggerFromStatus ? { from_status: triggerFromStatus } : {}),
          ...(triggerToStatus ? { to_status: triggerToStatus } : {}),
        },
        is_active: isActive,
        steps: steps.map((s, i) => ({ ...s, order: i })),
      };

      let response;
      if (isNew) {
        response = await post<ProcessWorkflow>('/api/workflows', workflowData);
      } else {
        response = await put<ProcessWorkflow>(`/api/workflows/${id}`, workflowData as ProcessWorkflowUpdate);
      }

      if (response.error) {
        toast({
          title: 'Validation Error',
          description: response.error,
          variant: 'destructive',
        });
        return;
      }

      if (response.data && response.data.id) {
        // Update original state to match current (clears dirty flag)
        setOriginalState({
          name,
          description,
          triggerType,
          entityTypes: [...entityTypes],
          isActive,
          steps: steps.map(s => ({ ...s })),
        });
        
        toast({
          title: 'Success',
          description: `Workflow ${isNew ? 'created' : 'updated'} successfully`,
        });
        navigate('/workflows');
      }
    } catch (error) {
      toast({
        title: 'Error',
        description: `Failed to ${isNew ? 'create' : 'update'} workflow: ${error instanceof Error ? error.message : 'Unknown error'}`,
        variant: 'destructive',
      });
    } finally {
      setIsSaving(false);
    }
  };

  // Get selected step
  const selectedStep = useMemo(() => {
    if (!selectedNodeId || selectedNodeId === 'trigger') return null;
    return steps.find(s => s.step_id === selectedNodeId);
  }, [selectedNodeId, steps]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-96">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    );
  }

  return (
    <div className="py-6 space-y-4 h-[calc(100vh-120px)] flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Button 
            variant="outline" 
            size="sm" 
            onClick={() => {
              if (isDirty) {
                setShowDiscardDialog(true);
              } else {
                navigate('/workflows');
              }
            }}
          >
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back
          </Button>
          {workflow?.is_default && (
            <Badge variant="secondary">Default</Badge>
          )}
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Workflow name"
            className="text-lg font-semibold border-none shadow-none px-2 h-8 min-w-[200px]"
            style={{ width: `${Math.max(200, name.length * 12 + 20)}px` }}
          />
          {isDirty && (
            <Badge variant="outline" className="text-amber-600 border-amber-500 dark:text-amber-400 dark:border-amber-400/50">
              Unsaved changes
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-2 mr-2">
            <Switch checked={isActive} onCheckedChange={setIsActive} />
            <span className="text-sm">{isActive ? 'Active' : 'Inactive'}</span>
          </div>
          <Button onClick={handleSave} disabled={isSaving} size="sm" className={isDirty ? 'ring-2 ring-amber-500/50' : ''}>
            {isSaving ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Save className="h-4 w-4 mr-2" />}
            Save{isDirty ? ' *' : ''}
          </Button>
        </div>
      </div>

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Flow canvas */}
        <div className="flex-1">
          <ReactFlow
            nodes={nodes}
            edges={edgesWithDelete}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onReconnect={onReconnect}
            onNodeClick={onNodeClick}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            defaultEdgeOptions={{ interactionWidth: 20 }}
            deleteKeyCode={['Backspace', 'Delete']}
            edgesUpdatable
            edgesFocusable
            fitView
            fitViewOptions={{ maxZoom: 1, padding: 0.2 }}
            minZoom={0.3}
            maxZoom={2}
            defaultViewport={{ x: 0, y: 0, zoom: 0.8 }}
            className="bg-slate-50 dark:bg-slate-900"
          >
            <Background />
            <Controls />
            <MiniMap />
            
            {/* Step type toolbar */}
            <Panel position="top-left" className="bg-background/95 backdrop-blur-sm border border-border rounded-lg shadow-lg p-2 dark:bg-slate-800/95">
              <div className="flex flex-col gap-1">
                <span className="text-xs font-medium text-muted-foreground dark:text-slate-300 px-2 mb-1">Add Step</span>
                <Button variant="ghost" size="sm" className="justify-start" onClick={() => addStep('policy_check')}>
                  <ClipboardCheck className="h-4 w-4 mr-2" /> Policy Check
                </Button>
                <Button variant="ghost" size="sm" className="justify-start" onClick={() => addStep('validation')}>
                  <Shield className="h-4 w-4 mr-2" /> Validation
                </Button>
                <Button variant="ghost" size="sm" className="justify-start" onClick={() => addStep('approval')}>
                  <UserCheck className="h-4 w-4 mr-2" /> Approval
                </Button>
                <Button variant="ghost" size="sm" className="justify-start" onClick={() => addStep('user_action')}>
                  <MessageSquare className="h-4 w-4 mr-2" /> User Action
                </Button>
                <Button variant="ghost" size="sm" className="justify-start" onClick={() => addStep('entity_action')}>
                  <Zap className="h-4 w-4 mr-2 text-lime-600 dark:text-lime-400" /> Entity Action
                </Button>
                <Button variant="ghost" size="sm" className="justify-start" onClick={() => addStep('notification')}>
                  <Bell className="h-4 w-4 mr-2" /> Notification
                </Button>
                <Button variant="ghost" size="sm" className="justify-start" onClick={() => addStep('assign_tag')}>
                  <Tag className="h-4 w-4 mr-2" /> Assign Tag
                </Button>
                <Button variant="ghost" size="sm" className="justify-start" onClick={() => addStep('conditional')}>
                  <GitBranch className="h-4 w-4 mr-2" /> Conditional
                </Button>
                <Button variant="ghost" size="sm" className="justify-start" onClick={() => addStep('script')}>
                  <Code className="h-4 w-4 mr-2" /> Script
                </Button>
                <Button variant="ghost" size="sm" className="justify-start" onClick={() => addStep('create_asset_review')}>
                  <FileSearch className="h-4 w-4 mr-2" /> Asset Review
                </Button>
                <Button variant="ghost" size="sm" className="justify-start" onClick={() => addStep('webhook')}>
                  <Globe className="h-4 w-4 mr-2 text-orange-500" /> Webhook
                </Button>
                <Separator className="my-1" />
                <Button variant="ghost" size="sm" className="justify-start" onClick={() => addStep('pass')}>
                  <CheckCircle className="h-4 w-4 mr-2 text-green-500" /> Pass
                </Button>
                <Button variant="ghost" size="sm" className="justify-start" onClick={() => addStep('fail')}>
                  <XCircle className="h-4 w-4 mr-2 text-red-500" /> Fail
                </Button>
              </div>
            </Panel>
          </ReactFlow>
        </div>

        {/* Discard changes confirmation dialog */}
        <AlertDialog open={showDiscardDialog} onOpenChange={setShowDiscardDialog}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Discard unsaved changes?</AlertDialogTitle>
              <AlertDialogDescription>
                You have unsaved changes to this workflow. If you leave now, your changes will be lost.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Stay</AlertDialogCancel>
              <AlertDialogAction
                onClick={() => navigate('/workflows')}
                className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              >
                Discard Changes
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        {/* Properties panel */}
        <Sheet open={!!selectedNodeId} onOpenChange={() => setSelectedNodeId(null)}>
          <SheetContent className="w-[400px]">
            <SheetHeader>
              <SheetTitle>
                {selectedNodeId === 'trigger' ? 'Trigger Configuration' : 'Step Configuration'}
              </SheetTitle>
            </SheetHeader>
            
            <div className="mt-6 space-y-4">
              {selectedNodeId === 'trigger' ? (
                // Trigger configuration
                <>
                  <div>
                    <Label>{t('common:labels.type')}</Label>
                    <Select value={triggerType} onValueChange={(v) => setTriggerType(v as TriggerType)}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {ALL_TRIGGER_TYPES.map(tt => (
                          <SelectItem key={tt} value={tt}>
                            {getTriggerTypeLabel(tt, t)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label>{t('common:labels.category')}</Label>
                    <div className="flex flex-wrap gap-2 mt-2">
                      {ALL_ENTITY_TYPES.map(et => (
                        <Badge
                          key={et}
                          variant={entityTypes.includes(et) ? 'default' : 'outline'}
                          className="cursor-pointer"
                          onClick={() => {
                            if (entityTypes.includes(et)) {
                              setEntityTypes(prev => prev.filter(e => e !== et));
                            } else {
                              setEntityTypes(prev => [...prev, et]);
                            }
                          }}
                        >
                          {getEntityTypeLabel(et, t)}
                        </Badge>
                      ))}
                    </div>
                  </div>
                  {(triggerType === 'on_status_change' || triggerType === 'before_status_change' || triggerType === 'on_request_status_change') && (
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <Label>From Status</Label>
                        <Input
                          value={triggerFromStatus}
                          onChange={(e) => setTriggerFromStatus(e.target.value)}
                          placeholder="e.g. draft"
                        />
                      </div>
                      <div>
                        <Label>To Status</Label>
                        <Input
                          value={triggerToStatus}
                          onChange={(e) => setTriggerToStatus(e.target.value)}
                          placeholder="e.g. active"
                        />
                      </div>
                    </div>
                  )}

                  <div>
                    <Label>Description</Label>
                    <Textarea
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                      placeholder="Workflow description"
                      rows={3}
                    />
                  </div>
                  
                  <Separator />
                  
                  <Button 
                    className="w-full"
                    onClick={() => setSelectedNodeId(null)}
                  >
                    Done
                  </Button>
                </>
              ) : selectedStep ? (
                // Step configuration
                <>
                  <div>
                    <Label>Step Name</Label>
                    <Input
                      value={selectedStep.name || ''}
                      onChange={(e) => updateStep(selectedStep.step_id, { name: e.target.value })}
                    />
                  </div>
                  <div>
                    <Label>Step Type</Label>
                    <Input value={selectedStep.step_type} disabled />
                  </div>
                  
                  {/* Type-specific config */}
                  {selectedStep.step_type === 'entity_action' && (
                    <>
                      <div>
                        <Label>Action</Label>
                        <Select
                          value={(selectedStep.config as { action?: string })?.action || 'certify'}
                          onValueChange={(v) =>
                            updateStep(selectedStep.step_id, {
                              config: { ...selectedStep.config, action: v },
                            })
                          }
                        >
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="certify">Certify</SelectItem>
                            <SelectItem value="decertify">Decertify</SelectItem>
                            <SelectItem value="publish">Publish</SelectItem>
                            <SelectItem value="unpublish">Unpublish</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      {((selectedStep.config as { action?: string })?.action || 'certify') === 'certify' && (
                        <>
                          <div>
                            <Label>Certification level source</Label>
                            <Select
                              value={
                                (selectedStep.config as { level_source?: string })?.level_source ||
                                'from_request'
                              }
                              onValueChange={(v) =>
                                updateStep(selectedStep.step_id, {
                                  config: { ...selectedStep.config, level_source: v },
                                })
                              }
                            >
                              <SelectTrigger>
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="from_request">From request</SelectItem>
                                <SelectItem value="fixed">Fixed level</SelectItem>
                                <SelectItem value="from_approval">From approval</SelectItem>
                              </SelectContent>
                            </Select>
                          </div>
                          {(selectedStep.config as { level_source?: string })?.level_source === 'fixed' && (
                            <div>
                              <Label>Fixed level</Label>
                              <Input
                                type="number"
                                min={0}
                                value={
                                  (selectedStep.config as { fixed_level?: number })?.fixed_level ?? ''
                                }
                                onChange={(e) => {
                                  const raw = e.target.value;
                                  const n = raw === '' ? undefined : parseInt(raw, 10);
                                  updateStep(selectedStep.step_id, {
                                    config: {
                                      ...selectedStep.config,
                                      fixed_level:
                                        n != null && !Number.isNaN(n) ? n : undefined,
                                    },
                                  });
                                }}
                                placeholder="e.g. 1"
                              />
                            </div>
                          )}
                        </>
                      )}
                      {((selectedStep.config as { action?: string })?.action || '') === 'publish' && (
                        <>
                          <div>
                            <Label>Publication scope source</Label>
                            <Select
                              value={
                                (selectedStep.config as { scope_source?: string })?.scope_source ||
                                'from_request'
                              }
                              onValueChange={(v) =>
                                updateStep(selectedStep.step_id, {
                                  config: { ...selectedStep.config, scope_source: v },
                                })
                              }
                            >
                              <SelectTrigger>
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="from_request">From request</SelectItem>
                                <SelectItem value="fixed">Fixed scope</SelectItem>
                                <SelectItem value="from_approval">From approval</SelectItem>
                              </SelectContent>
                            </Select>
                          </div>
                          {(selectedStep.config as { scope_source?: string })?.scope_source ===
                            'fixed' && (
                            <div>
                              <Label>Fixed scope</Label>
                              <Select
                                value={
                                  (selectedStep.config as { fixed_scope?: string })?.fixed_scope ||
                                  'domain'
                                }
                                onValueChange={(v) =>
                                  updateStep(selectedStep.step_id, {
                                    config: { ...selectedStep.config, fixed_scope: v },
                                  })
                                }
                              >
                                <SelectTrigger>
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  <SelectItem value="domain">Domain</SelectItem>
                                  <SelectItem value="organization">Organization</SelectItem>
                                  <SelectItem value="external">External</SelectItem>
                                </SelectContent>
                              </Select>
                            </div>
                          )}
                        </>
                      )}
                      <p className="text-xs text-muted-foreground">
                        Runs a lifecycle action on the entity that triggered this workflow (after
                        approval when used with request triggers).
                      </p>
                    </>
                  )}

                  {selectedStep.step_type === 'user_action' && (
                    <>
                      <div>
                        <Label>Title</Label>
                        <Input
                          value={(selectedStep.config as { title?: string })?.title || ''}
                          onChange={(e) => updateStep(selectedStep.step_id, {
                            config: { ...selectedStep.config, title: e.target.value },
                          })}
                          placeholder="e.g. Enter a reason"
                        />
                      </div>
                      <div>
                        <Label>Description</Label>
                        <Textarea
                          value={(selectedStep.config as { description?: string })?.description || ''}
                          onChange={(e) => updateStep(selectedStep.step_id, {
                            config: { ...selectedStep.config, description: e.target.value },
                          })}
                          placeholder="Optional description for the wizard step"
                          rows={2}
                        />
                      </div>
                      <div className="flex items-center gap-2">
                        <Switch
                          id="user-action-requires-input"
                          checked={(selectedStep.config as { requires_input?: boolean })?.requires_input ?? false}
                          onCheckedChange={(checked) => updateStep(selectedStep.step_id, {
                            config: { ...selectedStep.config, requires_input: checked },
                          })}
                        />
                        <Label htmlFor="user-action-requires-input" className="cursor-pointer">
                          Requires input
                        </Label>
                      </div>
                      <p className="text-xs text-muted-foreground -mt-2">
                        When on, user must enter something in the primary field before continuing.
                      </p>
                      <div>
                        <Label>Minimum input length</Label>
                        <Input
                          type="number"
                          min={0}
                          value={(selectedStep.config as { minimum_input_length?: number })?.minimum_input_length ?? ''}
                          onChange={(e) => {
                            const v = e.target.value === '' ? undefined : parseInt(e.target.value, 10);
                            updateStep(selectedStep.step_id, {
                              config: { ...selectedStep.config, minimum_input_length: v != null && !Number.isNaN(v) ? v : undefined },
                            });
                          }}
                          placeholder="e.g. 10"
                        />
                        <p className="text-xs text-muted-foreground mt-1">
                          Minimum characters for the primary field (leave empty for no minimum).
                        </p>
                      </div>
                      <div>
                        <Label>Primary field ID</Label>
                        <Input
                          value={(selectedStep.config as { primary_field_id?: string })?.primary_field_id || ''}
                          onChange={(e) => updateStep(selectedStep.step_id, {
                            config: { ...selectedStep.config, primary_field_id: e.target.value || undefined },
                          })}
                          placeholder="e.g. reason (default)"
                        />
                        <p className="text-xs text-muted-foreground mt-1">
                          Field checked for &quot;Requires input&quot; and minimum length. Default: first required field or &quot;reason&quot;.
                        </p>
                      </div>
                      <p className="text-xs text-muted-foreground">
                        User Action steps collect input in approval workflows (e.g. reason, acceptances). Use required_fields in YAML for custom field definitions.
                      </p>
                    </>
                  )}

                  {selectedStep.step_type === 'policy_check' && (
                    <div>
                      <Label>Compliance Policy</Label>
                      <Select 
                        value={(selectedStep.config as { policy_id?: string })?.policy_id || ''}
                        onValueChange={(v) => {
                          const policy = compliancePolicies.find(p => p.id === v);
                          updateStep(selectedStep.step_id, { 
                            config: { 
                              ...selectedStep.config, 
                              policy_id: v,
                              policy_name: policy?.name || '',
                            }
                          });
                        }}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="Select a compliance policy" />
                        </SelectTrigger>
                        <SelectContent>
                          {compliancePolicies.length === 0 ? (
                            <div className="px-2 py-3 text-sm text-muted-foreground">
                              No active policies found
                            </div>
                          ) : (
                            compliancePolicies.map((policy) => (
                              <SelectItem key={policy.id} value={policy.id}>
                                {policy.name}
                              </SelectItem>
                            ))
                          )}
                        </SelectContent>
                      </Select>
                      <p className="text-xs text-muted-foreground mt-2">
                        This step will evaluate the selected compliance policy's DSL rule at runtime.
                      </p>
                    </div>
                  )}
                  
                  {selectedStep.step_type === 'validation' && (
                    <div>
                      <Label>DSL Rule</Label>
                      <Textarea
                        value={(selectedStep.config as { rule?: string })?.rule || ''}
                        onChange={(e) => updateStep(selectedStep.step_id, { 
                          config: { ...selectedStep.config, rule: e.target.value }
                        })}
                        placeholder="MATCH (obj:Object)&#10;ASSERT obj.name MATCHES '^[a-z_]+$'"
                        rows={6}
                        className="font-mono text-sm"
                      />
                    </div>
                  )}
                  
                  {selectedStep.step_type === 'notification' && (
                    <>
                      <div>
                        <Label>Recipients</Label>
                        <Select 
                          value={(selectedStep.config as { recipients?: string })?.recipients || ''}
                          onValueChange={(v) => updateStep(selectedStep.step_id, { 
                            config: { ...selectedStep.config, recipients: v }
                          })}
                        >
                          <SelectTrigger>
                            <SelectValue placeholder="Select recipients" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="requester">Requester (Original User)</SelectItem>
                            <SelectItem value="owner">Owner (Entity Owner)</SelectItem>
                            {availableRoles.map((role) => (
                              <SelectItem key={role.id} value={role.id}>
                                <div className="flex items-center gap-2">
                                  <span>{role.name}</span>
                                  {!role.has_groups && (
                                    <Badge variant="outline" className="text-xs text-amber-600">
                                      No groups
                                    </Badge>
                                  )}
                                </div>
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div>
                        <Label>Template</Label>
                        <Select 
                          value={(selectedStep.config as { template?: string })?.template || ''}
                          onValueChange={(v) => updateStep(selectedStep.step_id, { 
                            config: { ...selectedStep.config, template: v }
                          })}
                        >
                          <SelectTrigger>
                            <SelectValue placeholder="Select template" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="request_submitted">Request Submitted</SelectItem>
                            <SelectItem value="request_approved">Request Approved</SelectItem>
                            <SelectItem value="request_rejected">Request Denied</SelectItem>
                            <SelectItem value="validation_failed">Validation Failed</SelectItem>
                            <SelectItem value="validation_passed">Validation Passed</SelectItem>
                            <SelectItem value="product_approved">Product Approved</SelectItem>
                            <SelectItem value="product_rejected">Product Rejected</SelectItem>
                            <SelectItem value="pii_detected">PII Detected</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div>
                        <Label>Custom Message</Label>
                        <Textarea
                          value={(selectedStep.config as { custom_message?: string })?.custom_message || ''}
                          onChange={(e) => updateStep(selectedStep.step_id, {
                            config: { ...selectedStep.config, custom_message: e.target.value }
                          })}
                          placeholder="Override template message. Supports ${entity_name}, ${entity_type}, ${user_email}, ${entity.field}..."
                          rows={3}
                        />
                        <p className="text-xs text-muted-foreground mt-1">
                          Variables: <code className="text-xs">{'${entity_name}'}</code>, <code className="text-xs">{'${entity_type}'}</code>, <code className="text-xs">{'${user_email}'}</code>, <code className="text-xs">{'${entity.field}'}</code>, <code className="text-xs">{'${step_results.step_id.field}'}</code>
                        </p>
                      </div>
                      <div>
                        <Label className="mb-2 block">Channels</Label>
                        <div className="flex flex-col gap-2">
                          {(['in_app', 'email', 'webhook'] as const).map((ch) => (
                            <div key={ch} className="flex items-center gap-2">
                              <Checkbox
                                id={`channel-${ch}`}
                                checked={((selectedStep.config as { channels?: string[] })?.channels || ['in_app']).includes(ch)}
                                onCheckedChange={(checked) => {
                                  const current = (selectedStep.config as { channels?: string[] })?.channels || ['in_app'];
                                  const next = checked
                                    ? [...current, ch]
                                    : current.filter((c: string) => c !== ch);
                                  updateStep(selectedStep.step_id, {
                                    config: { ...selectedStep.config, channels: next.length > 0 ? next : ['in_app'] }
                                  });
                                }}
                              />
                              <label htmlFor={`channel-${ch}`} className="text-sm capitalize">{ch.replace('_', ' ')}</label>
                            </div>
                          ))}
                        </div>
                        <p className="text-xs text-muted-foreground mt-1">Defaults to global setting if none selected.</p>
                      </div>
                    </>
                  )}
                  
                  {selectedStep.step_type === 'assign_tag' && (
                    <>
                      <div>
                        <Label>Tag Key</Label>
                        <Input
                          value={(selectedStep.config as { key?: string })?.key || ''}
                          onChange={(e) => updateStep(selectedStep.step_id, { 
                            config: { ...selectedStep.config, key: e.target.value }
                          })}
                          placeholder="e.g., owner"
                        />
                      </div>
                      <div>
                        <Label>Value Source</Label>
                        <Select 
                          value={(selectedStep.config as { value_source?: string })?.value_source || ''}
                          onValueChange={(v) => updateStep(selectedStep.step_id, { 
                            config: { ...selectedStep.config, value_source: v }
                          })}
                        >
                          <SelectTrigger>
                            <SelectValue placeholder="Select source" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="current_user">Current User</SelectItem>
                            <SelectItem value="project_name">Project Name</SelectItem>
                            <SelectItem value="timestamp">Timestamp</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                    </>
                  )}
                  
                  {selectedStep.step_type === 'approval' && (
                    <>
                      <div>
                        <Label>Approvers (Role)</Label>
                        <Select 
                          value={(selectedStep.config as { approvers?: string })?.approvers || ''}
                          onValueChange={(v) => updateStep(selectedStep.step_id, { 
                            config: { ...selectedStep.config, approvers: v }
                          })}
                        >
                          <SelectTrigger>
                            <SelectValue placeholder="Select role" />
                          </SelectTrigger>
                          <SelectContent>
                            {availableRoles.map((role) => (
                              <SelectItem key={role.id} value={role.id}>
                                <div className="flex items-center gap-2">
                                  <span>{role.name}</span>
                                  {!role.has_groups && (
                                    <Badge variant="outline" className="text-xs text-amber-600">
                                      No groups
                                    </Badge>
                                  )}
                                </div>
                              </SelectItem>
                            ))}
                            <SelectItem value="requester">Requester (Original User)</SelectItem>
                          </SelectContent>
                        </Select>
                        <p className="text-xs text-muted-foreground mt-1">
                          Role UUIDs ensure referential integrity if roles are renamed.
                        </p>
                      </div>
                      <div>
                        <Label>Timeout (days)</Label>
                        <Input
                          type="number"
                          value={(selectedStep.config as { timeout_days?: number })?.timeout_days || 7}
                          onChange={(e) => updateStep(selectedStep.step_id, { 
                            config: { ...selectedStep.config, timeout_days: parseInt(e.target.value) }
                          })}
                        />
                      </div>
                    </>
                  )}

                  {selectedStep.step_type === 'create_asset_review' && (
                    <>
                      <div>
                        <Label>Reviewer Role</Label>
                        <Select 
                          value={(selectedStep.config as { reviewer_role?: string })?.reviewer_role || ''}
                          onValueChange={(v) => updateStep(selectedStep.step_id, { 
                            config: { ...selectedStep.config, reviewer_role: v }
                          })}
                        >
                          <SelectTrigger>
                            <SelectValue placeholder="Select reviewer role" />
                          </SelectTrigger>
                          <SelectContent>
                            {availableRoles.map((role) => (
                              <SelectItem key={role.id} value={role.id}>
                                <div className="flex items-center gap-2">
                                  <span>{role.name}</span>
                                  {!role.has_groups && (
                                    <Badge variant="outline" className="text-xs text-amber-600">
                                      No groups
                                    </Badge>
                                  )}
                                </div>
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <p className="text-xs text-muted-foreground mt-1">
                          The role whose members can review the asset.
                        </p>
                      </div>
                      <div>
                        <Label>Review Type</Label>
                        <Select 
                          value={(selectedStep.config as { review_type?: string })?.review_type || 'standard'}
                          onValueChange={(v) => updateStep(selectedStep.step_id, { 
                            config: { ...selectedStep.config, review_type: v }
                          })}
                        >
                          <SelectTrigger>
                            <SelectValue placeholder="Select review type" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="standard">Standard Review</SelectItem>
                            <SelectItem value="expedited">Expedited Review</SelectItem>
                            <SelectItem value="compliance">Compliance Review</SelectItem>
                            <SelectItem value="security">Security Review</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div>
                        <Label>Notes</Label>
                        <Textarea
                          value={(selectedStep.config as { notes?: string })?.notes || ''}
                          onChange={(e) => updateStep(selectedStep.step_id, { 
                            config: { ...selectedStep.config, notes: e.target.value }
                          })}
                          placeholder="Additional notes for the reviewer..."
                          rows={2}
                        />
                      </div>
                    </>
                  )}

                  {selectedStep.step_type === 'webhook' && (
                    <>
                      <div>
                        <Label>Mode</Label>
                        <Select 
                          value={(selectedStep.config as { connection_name?: string })?.connection_name ? 'connection' : 'inline'}
                          onValueChange={(v) => {
                            if (v === 'connection') {
                              updateStep(selectedStep.step_id, { 
                                config: { 
                                  ...selectedStep.config, 
                                  url: undefined,
                                  connection_name: '' 
                                }
                              });
                            } else {
                              updateStep(selectedStep.step_id, { 
                                config: { 
                                  ...selectedStep.config, 
                                  connection_name: undefined,
                                  url: '' 
                                }
                              });
                            }
                          }}
                        >
                          <SelectTrigger>
                            <SelectValue placeholder="Select mode" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="connection">UC Connection (Recommended)</SelectItem>
                            <SelectItem value="inline">Inline URL</SelectItem>
                          </SelectContent>
                        </Select>
                        <p className="text-xs text-muted-foreground mt-1">
                          UC Connections store credentials securely in Unity Catalog.
                        </p>
                      </div>
                      
                      {(selectedStep.config as { connection_name?: string })?.connection_name !== undefined && (
                        <>
                          <div>
                            <Label>HTTP Connection</Label>
                            <Select 
                              value={(selectedStep.config as { connection_name?: string })?.connection_name || ''}
                              onValueChange={(v) => updateStep(selectedStep.step_id, { 
                                config: { ...selectedStep.config, connection_name: v }
                              })}
                            >
                              <SelectTrigger>
                                <SelectValue placeholder="Select a UC HTTP Connection" />
                              </SelectTrigger>
                              <SelectContent>
                                {httpConnections.length === 0 ? (
                                  <div className="px-2 py-3 text-sm text-muted-foreground">
                                    No HTTP connections found
                                  </div>
                                ) : (
                                  httpConnections.map((conn) => (
                                    <SelectItem key={conn.name} value={conn.name}>
                                      {conn.name}
                                    </SelectItem>
                                  ))
                                )}
                              </SelectContent>
                            </Select>
                          </div>
                          <div>
                            <Label>Path</Label>
                            <Input
                              value={(selectedStep.config as { path?: string })?.path || ''}
                              onChange={(e) => updateStep(selectedStep.step_id, { 
                                config: { ...selectedStep.config, path: e.target.value }
                              })}
                              placeholder="/api/now/table/incident"
                            />
                            <p className="text-xs text-muted-foreground mt-1">
                              Path appended to the connection's base URL.
                            </p>
                          </div>
                        </>
                      )}
                      
                      {(selectedStep.config as { url?: string })?.url !== undefined && (
                        <div>
                          <Label>URL</Label>
                          <Input
                            value={(selectedStep.config as { url?: string })?.url || ''}
                            onChange={(e) => updateStep(selectedStep.step_id, { 
                              config: { ...selectedStep.config, url: e.target.value }
                            })}
                            placeholder="https://api.example.com/webhook"
                          />
                          <p className="text-xs text-amber-600 mt-1">
                            Warning: Inline credentials are stored in workflow config.
                          </p>
                        </div>
                      )}
                      
                      <div>
                        <Label>HTTP Method</Label>
                        <Select 
                          value={(selectedStep.config as { method?: string })?.method || 'POST'}
                          onValueChange={(v) => updateStep(selectedStep.step_id, { 
                            config: { ...selectedStep.config, method: v }
                          })}
                        >
                          <SelectTrigger>
                            <SelectValue placeholder="Select method" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="GET">GET</SelectItem>
                            <SelectItem value="POST">POST</SelectItem>
                            <SelectItem value="PUT">PUT</SelectItem>
                            <SelectItem value="PATCH">PATCH</SelectItem>
                            <SelectItem value="DELETE">DELETE</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      
                      <div>
                        <Label>Body Template</Label>
                        <Textarea
                          value={(selectedStep.config as { body_template?: string })?.body_template || ''}
                          onChange={(e) => updateStep(selectedStep.step_id, { 
                            config: { ...selectedStep.config, body_template: e.target.value }
                          })}
                          placeholder={'{\n  "description": "Alert for ${entity_name}",\n  "entity_type": "${entity_type}"\n}'}
                          rows={5}
                          className="font-mono text-sm"
                        />
                        <p className="text-xs text-muted-foreground mt-1">
                          Use {'${variable}'} for substitution: entity_type, entity_id, entity_name, user_email, workflow_name
                        </p>
                      </div>
                      
                      <div>
                        <Label>Timeout (seconds)</Label>
                        <Input
                          type="number"
                          value={(selectedStep.config as { timeout_seconds?: number })?.timeout_seconds || 30}
                          onChange={(e) => updateStep(selectedStep.step_id, { 
                            config: { ...selectedStep.config, timeout_seconds: parseInt(e.target.value) || 30 }
                          })}
                        />
                      </div>
                      
                      <div>
                        <Label>Retry Count</Label>
                        <Input
                          type="number"
                          min={0}
                          max={5}
                          value={(selectedStep.config as { retry_count?: number })?.retry_count || 0}
                          onChange={(e) => updateStep(selectedStep.step_id, { 
                            config: { ...selectedStep.config, retry_count: parseInt(e.target.value) || 0 }
                          })}
                        />
                        <p className="text-xs text-muted-foreground mt-1">
                          Number of retries on failure (0-5).
                        </p>
                      </div>
                    </>
                  )}

                  <Separator />
                  
                  <div className="flex gap-2">
                    <Button 
                      className="flex-1"
                      onClick={() => setSelectedNodeId(null)}
                    >
                      Done
                    </Button>
                    <Button 
                      variant="destructive" 
                      size="icon"
                      onClick={() => deleteStep(selectedStep.step_id)}
                      title="Delete Step"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </>
              ) : null}
            </div>
          </SheetContent>
        </Sheet>
      </div>
    </div>
  );
}

