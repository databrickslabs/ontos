import { useState, useCallback, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
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
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from '@/components/ui/select';
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
  Plus,
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
  FileText,
  ListChecks,
  Users,
  Database,
  Send,
  KeyRound,
  Eye,
  Edit2,
  Check,
  X,
} from 'lucide-react';
import ApprovalWizardDialog from './approval-wizard-dialog';

import RequiredFieldsEditor, {
  type RequiredField,
  isPrimaryFieldValid,
} from './required-fields-editor';
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
  LegalDocumentNode,
  AcknowledgementChecklistNode,
  CoSignersNode,
  PersistAgreementNode,
  GeneratePdfNode,
  DeliverNode,
  GrantPermissionsNode,
  OnBehalfOfNode,
} from './workflow-nodes';
import TemplateVarsInspector from './template-vars-inspector';

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
  WorkflowTypeValue,
} from '@/types/process-workflow';
import {
  ALL_ENTITY_TYPES,
  isTriggerEntitySupported,
  ENTITY_TYPE_TO_APPROVAL_ENTITY,
} from '@/lib/workflow-labels';
import { TriggerPicker, type TriggerTypeOption } from './trigger-picker';
import { EntityTypeMultiselect } from './entity-type-multiselect';
import { PrincipalPicker } from '@/components/common/principal-picker';
import { WorkflowCanvasSkeleton } from '@/components/common/list-view-skeleton';
import {
  joinRoleAndPrincipals,
  splitRoleAndPrincipals,
} from '@/lib/workflow-principals';

// -------------------------------------------------------------------------
// KeyValueEditor — explicit add/edit editor for Record<string, string>
// config fields. Used by the webhook step config panel for
// `additional_headers` and `additional_query_params` (issue #401 follow-up).
// Kept inline because it is only used here; if a second caller needs it,
// lift to a shared file.
//
// UX contract:
//   • "Add entry" row at the top — explicit Add button, validated on click.
//   • Saved entries render read-only below with Edit (pencil) + Remove (trash).
//   • Clicking Edit enters per-row edit mode: Save (check) + Cancel (X).
//   • Validation: empty key blocked; duplicate key blocked (both Add + Edit).
//   • Template warning: if a value contains an unclosed ${ show amber badge.
//   • Empty state: muted italic "No entries." text.
// -------------------------------------------------------------------------

/** Returns true when a value string has an unclosed ${ template expression. */
function hasUnclosedTemplate(val: string): boolean {
  const opens = (val.match(/\$\{/g) || []).length;
  const closes = (val.match(/\}/g) || []).length;
  return opens > closes;
}

interface KeyValueEditorProps {
  label: string;
  helpText?: string;
  keyPlaceholder?: string;
  valuePlaceholder?: string;
  value: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
}

function KeyValueEditor({
  label,
  helpText,
  keyPlaceholder,
  valuePlaceholder,
  value,
  onChange,
}: KeyValueEditorProps) {
  const { t } = useTranslation(['workflows', 'common']);
  // Entries derived from the controlled prop — insertion-order preserved.
  const entries = useMemo(() => Object.entries(value || {}), [value]);

  // ---- Add-row state ----
  const [addKey, setAddKey] = useState('');
  const [addValue, setAddValue] = useState('');
  const [addKeyError, setAddKeyError] = useState<string | null>(null);

  // ---- Per-row edit state ----
  // editIdx: which saved row is currently being edited (null = none)
  const [editIdx, setEditIdx] = useState<number | null>(null);
  const [editKey, setEditKey] = useState('');
  const [editValue, setEditValue] = useState('');
  const [editKeyError, setEditKeyError] = useState<string | null>(null);

  const commitEntries = (next: Array<[string, string]>) => {
    const out: Record<string, string> = {};
    for (const [k, v] of next) {
      if (k.length > 0) out[k] = v;
    }
    onChange(out);
  };

  // ---- Add handlers ----
  const handleAdd = () => {
    const trimmedKey = addKey.trim();
    if (!trimmedKey) {
      setAddKeyError(t('workflows:designer.keyValue.keyRequired'));
      return;
    }
    if (Object.prototype.hasOwnProperty.call(value || {}, trimmedKey)) {
      setAddKeyError(t('workflows:designer.keyValue.keyExistsAdd'));
      return;
    }
    commitEntries([...entries, [trimmedKey, addValue]]);
    setAddKey('');
    setAddValue('');
    setAddKeyError(null);
  };

  // ---- Edit handlers ----
  const startEdit = (idx: number) => {
    setEditIdx(idx);
    setEditKey(entries[idx][0]);
    setEditValue(entries[idx][1]);
    setEditKeyError(null);
  };

  const cancelEdit = () => {
    setEditIdx(null);
    setEditKeyError(null);
  };

  const commitEdit = () => {
    const trimmedKey = editKey.trim();
    if (!trimmedKey) {
      setEditKeyError(t('workflows:designer.keyValue.keyRequired'));
      return;
    }
    // Duplicate check: allow the same key if it's the row being edited.
    const isDuplicate = entries.some(
      ([k], i) => k === trimmedKey && i !== editIdx,
    );
    if (isDuplicate) {
      setEditKeyError(t('workflows:designer.keyValue.keyExistsEdit'));
      return;
    }
    const next = entries.map((e, i) =>
      i === editIdx ? ([trimmedKey, editValue] as [string, string]) : (e as [string, string]),
    );
    commitEntries(next);
    setEditIdx(null);
    setEditKeyError(null);
  };

  const removeRow = (idx: number) => {
    if (editIdx === idx) cancelEdit();
    commitEntries(entries.filter((_, i) => i !== idx));
  };

  return (
    <div>
      <Label>{label}</Label>

      {/* Add-entry row */}
      <div className="mt-2 p-2 rounded-md border border-dashed bg-muted/30 space-y-1">
        <p className="text-xs text-muted-foreground font-medium">{t('workflows:designer.keyValue.addEntry')}</p>
        <div className="flex gap-2 items-start">
          <div className="flex-1 space-y-1">
            <Input
              value={addKey}
              onChange={(e) => {
                setAddKey(e.target.value);
                if (addKeyError) setAddKeyError(null);
              }}
              onKeyDown={(e) => { if (e.key === 'Enter') handleAdd(); }}
              placeholder={keyPlaceholder || t('workflows:designer.keyValue.keyPlaceholder')}
              className="font-mono text-sm"
              aria-label={t('workflows:designer.keyValue.newEntryKeyAria')}
            />
            {addKeyError && (
              <p className="text-xs text-destructive">{addKeyError}</p>
            )}
          </div>
          <div className="flex-1">
            <Input
              value={addValue}
              onChange={(e) => setAddValue(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleAdd(); }}
              placeholder={valuePlaceholder || t('workflows:designer.keyValue.valuePlaceholder')}
              className="font-mono text-sm"
              aria-label={t('workflows:designer.keyValue.newEntryValueAria')}
            />
          </div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={handleAdd}
            aria-label={t('workflows:designer.keyValue.addEntry')}
          >
            <Plus className="w-3 h-3 mr-1" />
            {t('common:actions.add')}
          </Button>
        </div>
      </div>

      {/* Saved entries list */}
      <div className="space-y-1 mt-2">
        {entries.length === 0 && (
          <p className="text-xs text-muted-foreground italic">{t('workflows:designer.keyValue.noEntries')}</p>
        )}
        {entries.map(([k, v], idx) => {
          const isEditing = editIdx === idx;
          return (
            <div
              key={k}
              className={`flex gap-2 items-start rounded-md px-2 py-1 ${
                isEditing ? 'ring-1 ring-primary/40 bg-primary/5' : 'bg-background'
              }`}
            >
              {isEditing ? (
                <>
                  <div className="flex-1 space-y-1">
                    <Input
                      value={editKey}
                      onChange={(e) => {
                        setEditKey(e.target.value);
                        if (editKeyError) setEditKeyError(null);
                      }}
                      onKeyDown={(e) => { if (e.key === 'Enter') commitEdit(); else if (e.key === 'Escape') cancelEdit(); }}
                      placeholder={keyPlaceholder || t('workflows:designer.keyValue.keyPlaceholder')}
                      className="font-mono text-sm"
                      aria-label={t('workflows:designer.keyValue.editEntryKeyAria')}
                      autoFocus
                    />
                    {editKeyError && (
                      <p className="text-xs text-destructive">{editKeyError}</p>
                    )}
                  </div>
                  <div className="flex-1">
                    <Input
                      value={editValue}
                      onChange={(e) => setEditValue(e.target.value)}
                      onKeyDown={(e) => { if (e.key === 'Enter') commitEdit(); else if (e.key === 'Escape') cancelEdit(); }}
                      placeholder={valuePlaceholder || t('workflows:designer.keyValue.valuePlaceholder')}
                      className="font-mono text-sm"
                      aria-label={t('workflows:designer.keyValue.editEntryValueAria')}
                    />
                  </div>
                  <div className="flex gap-1">
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      onClick={commitEdit}
                      aria-label={t('workflows:designer.keyValue.saveEditAria')}
                      className="text-green-600 hover:text-green-700"
                    >
                      <Check className="w-4 h-4" />
                    </Button>
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      onClick={cancelEdit}
                      aria-label={t('workflows:designer.keyValue.cancelEditAria')}
                    >
                      <X className="w-4 h-4" />
                    </Button>
                  </div>
                </>
              ) : (
                <>
                  <span className="flex-1 font-mono text-sm py-1 truncate">{k}</span>
                  <div className="flex-1 flex items-center gap-1 min-w-0">
                    <span className="font-mono text-sm py-1 truncate">{v}</span>
                    {hasUnclosedTemplate(v) && (
                      <Badge
                        variant="outline"
                        className="shrink-0 text-amber-700 border-amber-400 bg-amber-100 text-xs px-1 py-0"
                      >
                        {t('workflows:designer.keyValue.checkTemplate')}
                      </Badge>
                    )}
                  </div>
                  <div className="flex gap-1">
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      onClick={() => startEdit(idx)}
                      aria-label={t('workflows:designer.keyValue.editRowAria')}
                    >
                      <Edit2 className="w-4 h-4" />
                    </Button>
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      onClick={() => removeRow(idx)}
                      aria-label={t('workflows:designer.keyValue.removeRowAria')}
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </div>
                </>
              )}
            </div>
          );
        })}
      </div>

      {helpText && (
        <p className="text-xs text-muted-foreground mt-1">{helpText}</p>
      )}
    </div>
  );
}

// Node types registry (default = fallback for unknown step_type)
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
  legal_document: LegalDocumentNode,
  acknowledgement_checklist: AcknowledgementChecklistNode,
  co_signers: CoSignersNode,
  persist_agreement: PersistAgreementNode,
  generate_pdf: GeneratePdfNode,
  deliver: DeliverNode,
  grant_permissions: GrantPermissionsNode,
  on_behalf_of: OnBehalfOfNode,
  default: DefaultStepNode,
};

// Schema-driven configuration panel for new step types.
// Reads the JSON schema from the backend step-types API and generates form fields automatically.
const SCHEMA_DRIVEN_STEP_TYPES = ['legal_document', 'acknowledgement_checklist', 'co_signers', 'persist_agreement', 'generate_pdf', 'deliver', 'grant_permissions', 'on_behalf_of'];

function SchemaConfigPanel({
  schema,
  config,
  onUpdate,
}: {
  schema: Record<string, unknown>;
  config: Record<string, unknown>;
  onUpdate: (newConfig: Record<string, unknown>) => void;
}) {
  const { t } = useTranslation(['workflows', 'common']);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const properties = (schema as any)?.properties || {};
  const propertyEntries = Object.entries(properties);

  if (propertyEntries.length === 0) {
    const schemaDesc = (schema as any)?.description;
    return (
      <p className="text-xs text-muted-foreground">
        {schemaDesc || t('workflows:designer.schema.noProperties')}
      </p>
    );
  }

  return (
    <>
      {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
      {propertyEntries.map(([key, propSchema]: [string, any]) => {
        // Conditional visibility: hide field when x-visible-when condition not met
        const visibleWhen = propSchema['x-visible-when'];
        if (visibleWhen && config[visibleWhen.field] !== visibleWhen.value) {
          return null;
        }

        const value = config[key];
        const title: string =
          propSchema.title ||
          key
            .replace(/_/g, ' ')
            .replace(/\b\w/g, (c: string) => c.toUpperCase());
        const description: string | undefined = propSchema.description;

        // Enum → Select dropdown
        if (propSchema.enum) {
          return (
            <div key={key}>
              <Label>{title}</Label>
              <Select
                value={String(value ?? propSchema.default ?? '')}
                onValueChange={(v) => onUpdate({ ...config, [key]: v })}
              >
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {propSchema.enum.map((opt: string) => (
                    <SelectItem key={opt} value={opt}>{opt}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {description && (
                <p className="text-xs text-muted-foreground mt-1">{description}</p>
              )}
            </div>
          );
        }

        // Boolean → Switch
        if (propSchema.type === 'boolean') {
          return (
            <div key={key} className="flex items-center gap-2">
              <Switch
                id={`schema-${key}`}
                checked={!!value}
                onCheckedChange={(checked) => onUpdate({ ...config, [key]: checked })}
              />
              <Label htmlFor={`schema-${key}`} className="cursor-pointer">{title}</Label>
              {description && (
                <p className="text-xs text-muted-foreground">{description}</p>
              )}
            </div>
          );
        }

        // Number/integer → numeric Input
        if (propSchema.type === 'integer' || propSchema.type === 'number') {
          return (
            <div key={key}>
              <Label>{title}</Label>
              <Input
                type="number"
                value={value ?? propSchema.default ?? ''}
                onChange={(e) =>
                  onUpdate({
                    ...config,
                    [key]: propSchema.type === 'integer'
                      ? parseInt(e.target.value) || 0
                      : parseFloat(e.target.value) || 0,
                  })
                }
              />
              {description && (
                <p className="text-xs text-muted-foreground mt-1">{description}</p>
              )}
            </div>
          );
        }

        // Array → JSON Textarea
        if (propSchema.type === 'array') {
          return (
            <div key={key}>
              <Label>{title}</Label>
              <Textarea
                value={JSON.stringify(value || propSchema.default || [], null, 2)}
                onChange={(e) => {
                  try {
                    onUpdate({ ...config, [key]: JSON.parse(e.target.value) });
                  } catch {
                    /* ignore parse errors while typing */
                  }
                }}
                rows={4}
                className="font-mono text-sm"
              />
              {description && (
                <p className="text-xs text-muted-foreground mt-1">{description}</p>
              )}
            </div>
          );
        }

        // Default: string — use Textarea for long fields (markdown, template, body), Input otherwise
        const isLong =
          key.includes('markdown') ||
          key.includes('template') ||
          key.includes('body');
        return (
          <div key={key}>
            <Label>{title}</Label>
            {isLong ? (
              <Textarea
                value={String(value || '')}
                onChange={(e) => onUpdate({ ...config, [key]: e.target.value })}
                rows={4}
                className={key.includes('markdown') ? 'font-mono text-sm' : ''}
              />
            ) : (
              <Input
                value={String(value || '')}
                onChange={(e) => onUpdate({ ...config, [key]: e.target.value })}
              />
            )}
            {description && (
              <p className="text-xs text-muted-foreground mt-1">{description}</p>
            )}
          </div>
        );
      })}
    </>
  );
}

// Custom edge with visible delete button when selected
function DeletableEdge({
  id, sourceX, sourceY, targetX, targetY,
  sourcePosition, targetPosition, style, label, labelStyle, markerEnd, selected, data,
}: EdgeProps) {
  const { t } = useTranslation(['workflows', 'common']);
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
              title={t('workflows:designer.deleteConnection')}
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

// Palette steps filtered by workflow type
const PROCESS_PALETTE_STEPS: { type: StepType; label: string; icon: typeof Shield; disabled?: boolean }[] = [
  { type: 'policy_check', label: 'Policy Check', icon: ClipboardCheck },
  { type: 'validation', label: 'Validation', icon: Shield },
  { type: 'approval', label: 'Request Approval', icon: UserCheck },
  { type: 'entity_action', label: 'Entity Action', icon: Zap },
  { type: 'notification', label: 'Notification', icon: Bell },
  { type: 'assign_tag', label: 'Assign Tag', icon: Tag },
  { type: 'conditional', label: 'Conditional', icon: GitBranch },
  { type: 'script', label: 'Script', icon: Code },
  { type: 'create_asset_review', label: 'Asset Review', icon: FileSearch },
  { type: 'webhook', label: 'Webhook', icon: Globe },
  { type: 'grant_permissions', label: 'Grant Permissions', icon: KeyRound },
];

const APPROVAL_PALETTE_STEPS: { type: StepType; label: string; icon: typeof Shield; disabled?: boolean }[] = [
  { type: 'on_behalf_of', label: 'On Behalf Of', icon: Users },
  { type: 'legal_document', label: 'Legal Document', icon: FileText },
  { type: 'acknowledgement_checklist', label: 'Acknowledgement Checklist', icon: ListChecks },
  { type: 'user_action', label: 'User Action', icon: MessageSquare },
  { type: 'co_signers', label: 'Co-Signers', icon: Users },
  { type: 'persist_agreement', label: 'Persist Agreement', icon: Database },
  { type: 'generate_pdf', label: 'Generate PDF', icon: FileText },
  { type: 'deliver', label: 'Deliver', icon: Send },
];

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
  const [searchParams] = useSearchParams();
  const id = workflowId || params.workflowId;
  const isNew = !id || id === 'new';
  const initialType = (searchParams.get('type') as WorkflowTypeValue) || undefined;

  const { t } = useTranslation(['workflows', 'common']);
  const { get, post, put } = useApi();
  const { toast } = useToast();

  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((state) => state.setDynamicTitle);

  const [workflow, setWorkflow] = useState<ProcessWorkflow | null>(null);
  const [isLoading, setIsLoading] = useState(!isNew);
  const [isSaving, setIsSaving] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [_stepTypes, setStepTypes] = useState<StepTypeSchema[]>([]);
  const [compliancePolicies, setCompliancePolicies] = useState<CompliancePolicyRef[]>([]);
  const [availableRoles, setAvailableRoles] = useState<{ id: string; name: string; source: 'app' | 'business'; has_groups?: boolean; category?: string; description?: string }[]>([]);
  // approverRoles is the approval-entity-filtered subset of availableRoles used
  // specifically in the Approvers (Role) picker. It is re-computed whenever
  // entityTypes changes so the dropdown tracks the trigger configuration.
  const [approverRoles, setApproverRoles] = useState<typeof availableRoles>([]);
  const [httpConnections, setHttpConnections] = useState<HttpConnectionRef[]>([]);
  const [triggerTypeOptions, setTriggerTypeOptions] = useState<TriggerTypeOption[]>([]);
  const [showDiscardDialog, setShowDiscardDialog] = useState(false);
  // Preview wizard (issue #405) — design-time dry-run. Only meaningful once
  // the workflow has been persisted (we need its id to fetch the snapshot),
  // and only for approval-type workflows.
  const [previewOpen, setPreviewOpen] = useState(false);
  
  // Form state
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [triggerType, setTriggerType] = useState<TriggerType>('on_create');
  const [entityTypes, setEntityTypes] = useState<EntityType[]>(['table']);
  const [triggerFromStatus, setTriggerFromStatus] = useState('');
  const [triggerToStatus, setTriggerToStatus] = useState('');
  const [isActive, setIsActive] = useState(true);
  const [steps, setSteps] = useState<WorkflowStepCreate[]>([]);
  const [workflowType, setWorkflowType] = useState<WorkflowTypeValue | null>(isNew ? (initialType || null) : null);

  // Helper to render roles grouped by source type
  const renderGroupedRoles = (roles: typeof availableRoles, includeSpecialItems?: { requester?: boolean; owner?: boolean }) => {
    const appRoles = roles.filter(r => r.source === 'app');
    const businessRoles = roles.filter(r => r.source === 'business');

    return (
      <>
        {includeSpecialItems?.requester && (
          <SelectGroup>
            <SelectLabel>{t('workflows:designer.roles.special')}</SelectLabel>
            <SelectItem value="requester">{t('workflows:designer.roles.requesterOriginalUser')}</SelectItem>
            {includeSpecialItems?.owner && (
              <SelectItem value="owner">{t('workflows:designer.roles.ownerEntityOwner')}</SelectItem>
            )}
          </SelectGroup>
        )}
        {appRoles.length > 0 && (
          <SelectGroup>
            <SelectLabel>{t('workflows:designer.roles.appRoles')}</SelectLabel>
            {appRoles.map((role) => (
              <SelectItem key={role.id} value={role.id}>
                <div className="flex items-center gap-2">
                  <span>{role.name}</span>
                  {!role.has_groups && (
                    <Badge variant="outline" className="text-xs text-amber-600">
                      {t('workflows:designer.roles.noGroups')}
                    </Badge>
                  )}
                </div>
              </SelectItem>
            ))}
          </SelectGroup>
        )}
        {businessRoles.length > 0 && (
          <SelectGroup>
            <SelectLabel>{t('workflows:designer.roles.businessRoles')}</SelectLabel>
            {businessRoles.map((role) => (
              <SelectItem key={role.id} value={role.id}>
                <div className="flex items-center gap-2">
                  <span>{role.name}</span>
                  {role.category && (
                    <Badge variant="outline" className="text-xs text-muted-foreground">
                      {role.category}
                    </Badge>
                  )}
                </div>
              </SelectItem>
            ))}
          </SelectGroup>
        )}
      </>
    );
  };

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
      { label: t('common:labels.workflows'), path: '/workflows' },
    ]);
    setDynamicTitle(isNew ? t('workflows:designer.newWorkflow') : t('common:states.loading'));
    
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

      // Load trigger-type catalog (powers the grouped picker + entity-type
      // multiselect — single source of truth, mirrors the backend enum).
      try {
        const triggerTypesResponse = await get<TriggerTypeOption[]>('/api/workflows/trigger-types');
        if (triggerTypesResponse.data && Array.isArray(triggerTypesResponse.data)) {
          setTriggerTypeOptions(triggerTypesResponse.data);
        }
      } catch (error) {
        console.error('Failed to load trigger types:', error);
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
        const rolesResponse = await get<{ id: string; name: string; source: 'app' | 'business'; has_groups?: boolean; category?: string; description?: string }[]>('/api/workflows/roles');
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
            setWorkflowType((response.data.workflow_type as WorkflowTypeValue) || 'process');
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
            title: t('common:toast.error'),
            description: t('workflows:designer.messages.loadWorkflowFailed'),
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

  // Re-compute approverRoles whenever entityTypes or the base role list changes.
  // For each entity type that has an ApprovalEntity mapping we fetch the
  // backend-filtered list, then intersect across all mapped types so only roles
  // eligible to approve EVERY entity type are shown. Entity types without a
  // mapping (e.g. 'table', 'catalog') are ignored for filtering purposes —
  // if ALL entity types are unmapped the full role list is used.
  useEffect(() => {
    const requiredKeys = entityTypes
      .map(et => ENTITY_TYPE_TO_APPROVAL_ENTITY[et])
      .filter((k): k is string => k !== undefined);

    if (requiredKeys.length === 0) {
      // No approval-mapped entity types: show all roles (backward compat)
      setApproverRoles(availableRoles);
      return;
    }

    let cancelled = false;

    const fetchIntersection = async () => {
      try {
        const perKeyRoles = await Promise.all(
          requiredKeys.map(key =>
            get<typeof availableRoles>(`/api/workflows/roles?approval_entity=${encodeURIComponent(key)}`)
              .then(r => r.data ?? [])
          )
        );

        if (cancelled) return;

        if (perKeyRoles.length === 0) {
          setApproverRoles([]);
          return;
        }

        // Intersect: keep roles present in all per-key result sets
        const firstSet = perKeyRoles[0];
        const idSets = perKeyRoles.slice(1).map(arr => new Set(arr.map(r => r.id)));
        const intersected = firstSet.filter(role =>
          idSets.every(s => s.has(role.id))
        );

        setApproverRoles(intersected);
      } catch {
        if (!cancelled) {
          // Fall back to unfiltered list on error
          setApproverRoles(availableRoles);
        }
      }
    };

    fetchIntersection();
    return () => { cancelled = true; };
  }, [entityTypes, availableRoles, get]);

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

  // Keep the canvas trigger node in sync with the trigger picker state.
  // Without this the node renders only the initial default (on_create / table)
  // and never reflects changes the user makes in the Trigger Configuration panel.
  useEffect(() => {
    setNodes(prevNodes => prevNodes.map(node => {
      if (node.type !== 'trigger') return node;
      return {
        ...node,
        data: { ...node.data, trigger: { type: triggerType, entity_types: entityTypes } },
      };
    }));
  }, [triggerType, entityTypes, setNodes]);

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
      name: t('workflows:designer.newStepName', { type }),
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
    if (!workflowType) {
      toast({
        title: t('workflows:designer.messages.validationError'),
        description: t('workflows:designer.messages.selectWorkflowType'),
        variant: 'destructive',
      });
      return;
    }

    if (!name.trim()) {
      toast({
        title: t('workflows:designer.messages.validationError'),
        description: t('workflows:designer.messages.nameRequired'),
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
        workflow_type: workflowType || 'process',
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
          title: t('workflows:designer.messages.validationError'),
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
          title: t('common:toast.success'),
          description: isNew
            ? t('workflows:designer.messages.createdSuccess')
            : t('workflows:designer.messages.updatedSuccess'),
        });
        navigate('/workflows');
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : t('common:errors.unknownError');
      toast({
        title: t('common:toast.error'),
        description: isNew
          ? t('workflows:designer.messages.createFailed', { error: errorMessage })
          : t('workflows:designer.messages.updateFailed', { error: errorMessage }),
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
      <div className="py-6 space-y-4 h-[calc(100vh-120px)] flex flex-col">
        <WorkflowCanvasSkeleton showSidebar height="flex-1" />
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
            {t('common:actions.back')}
          </Button>
          {workflow?.is_default && (
            <Badge variant="secondary">{t('workflows:designer.badges.default')}</Badge>
          )}
          {workflowType && (
            <Badge variant="outline" className={workflowType === 'approval' ? 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-800' : 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950 dark:text-blue-300 dark:border-blue-800'}>
              {workflowType === 'approval' ? t('workflows:designer.badges.approval') : t('workflows:designer.badges.process')}
            </Badge>
          )}
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('workflows:designer.placeholders.workflowName')}
            className="text-lg font-semibold border-none shadow-none px-2 h-8 min-w-[200px]"
            style={{ width: `${Math.max(200, name.length * 12 + 20)}px` }}
          />
          {isDirty && (
            <Badge variant="outline" className="text-amber-600 border-amber-500 dark:text-amber-400 dark:border-amber-400/50">
              {t('workflows:designer.badges.unsavedChanges')}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
          {workflowType === 'approval' && !isNew && workflow?.id && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPreviewOpen(true)}
              // Disabled while dirty so the preview reflects the persisted
              // workflow — otherwise designers would chase phantom diffs
              // between the saved snapshot and unsaved edits.
              disabled={isDirty || isSaving}
              title={isDirty ? t('workflows:designer.preview.saveToPreview') : t('workflows:designer.preview.dryRunTitle')}
            >
              <Eye className="h-4 w-4 mr-2" />
              {t('workflows:designer.preview.previewWizard')}
            </Button>
          )}
          <div className="flex items-center gap-2 mr-2">
            <Switch checked={isActive} onCheckedChange={setIsActive} />
            <span className="text-sm">{isActive ? t('common:labels.active') : t('common:labels.inactive')}</span>
          </div>
          <Button onClick={handleSave} disabled={isSaving} size="sm" className={isDirty ? 'ring-2 ring-amber-500/50' : ''}>
            {isSaving ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Save className="h-4 w-4 mr-2" />}
            {t('common:actions.save')}{isDirty ? ' *' : ''}
          </Button>
        </div>
      </div>

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Workflow type chooser for new workflows without ?type= param */}
        {isNew && workflowType === null && (
          <div className="flex-1 flex items-center justify-center">
            <div className="max-w-lg w-full space-y-4">
              <h2 className="text-lg font-semibold text-center">{t('workflows:designer.typeChooser.title')}</h2>
              <p className="text-sm text-muted-foreground text-center">{t('workflows:designer.typeChooser.subtitle')}</p>
              <div className="grid grid-cols-2 gap-4">
                <button
                  className="border rounded-lg p-6 text-left hover:border-primary hover:bg-accent transition-colors"
                  onClick={() => setWorkflowType('process')}
                >
                  <div className="font-medium mb-1">{t('workflows:designer.typeChooser.processTitle')}</div>
                  <div className="text-sm text-muted-foreground">{t('workflows:designer.typeChooser.processDescription')}</div>
                </button>
                <button
                  className="border rounded-lg p-6 text-left hover:border-primary hover:bg-accent transition-colors"
                  onClick={() => setWorkflowType('approval')}
                >
                  <div className="font-medium mb-1">{t('workflows:designer.typeChooser.approvalTitle')}</div>
                  <div className="text-sm text-muted-foreground">{t('workflows:designer.typeChooser.approvalDescription')}</div>
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Flow canvas - shown only when workflow type is selected */}
        {workflowType !== null && (
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
                <span className="text-xs font-medium text-muted-foreground dark:text-slate-300 px-2 mb-1">{t('workflows:designer.palette.addStep')}</span>
                {(workflowType === 'approval' ? APPROVAL_PALETTE_STEPS : PROCESS_PALETTE_STEPS).map(({ type, label, icon: Icon, disabled }) => (
                  <Button key={type} variant="ghost" size="sm" className={`justify-start ${disabled ? 'opacity-50' : ''}`} onClick={() => !disabled && addStep(type)} disabled={disabled}>
                    <Icon className="h-4 w-4 mr-2" /> {t(`workflows:designer.palette.${type}`, label)}{disabled ? t('workflows:designer.palette.soonSuffix') : ''}
                  </Button>
                ))}
                <Separator className="my-1" />
                <Button variant="ghost" size="sm" className="justify-start" onClick={() => addStep('pass')}>
                  <CheckCircle className="h-4 w-4 mr-2 text-green-500" /> {t('common:workflows.stepTypes.pass')}
                </Button>
                <Button variant="ghost" size="sm" className="justify-start" onClick={() => addStep('fail')}>
                  <XCircle className="h-4 w-4 mr-2 text-red-500" /> {t('common:workflows.stepTypes.fail')}
                </Button>
              </div>
            </Panel>
          </ReactFlow>
        </div>
        )}

        {/* Approval Wizard Preview (issue #405) — design-time dry-run launched
            from the header. Pure FE walk through the persisted workflow; no
            session, no agreement, no notifications. */}
        {workflow?.id && workflowType === 'approval' && previewOpen && (
          <ApprovalWizardDialog
            isOpen={previewOpen}
            onOpenChange={setPreviewOpen}
            entityType="preview"
            entityId="preview"
            entityName={name || workflow.name}
            preselectedWorkflowId={workflow.id}
            autoStartWithPreselected
            previewMode
          />
        )}

        {/* Discard changes confirmation dialog */}
        <AlertDialog open={showDiscardDialog} onOpenChange={setShowDiscardDialog}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>{t('common:confirmations.discardChanges')}</AlertDialogTitle>
              <AlertDialogDescription>
                {t('workflows:designer.discard.description')}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>{t('workflows:designer.discard.stay')}</AlertDialogCancel>
              <AlertDialogAction
                onClick={() => navigate('/workflows')}
                className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              >
                {t('workflows:designer.discard.confirm')}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        {/* Properties panel */}
        <Sheet open={!!selectedNodeId} onOpenChange={() => setSelectedNodeId(null)}>
          <SheetContent className="w-[480px] sm:max-w-[560px] flex flex-col p-0">
            <SheetHeader className="px-6 pt-6 pb-2 shrink-0">
              <SheetTitle>
                {selectedNodeId === 'trigger' ? t('workflows:designer.triggerConfig.title') : t('workflows:designer.stepConfig.title')}
              </SheetTitle>
            </SheetHeader>

            <div className="mt-2 space-y-4 px-6 pb-6 overflow-y-auto flex-1 min-h-0">
              {selectedNodeId === 'trigger' ? (
                // Trigger configuration
                <>
                  <div>
                    <TriggerPicker
                      value={triggerType}
                      onChange={(v) => {
                        setTriggerType(v as TriggerType);
                        // Reset entity_types when trigger changes so the
                        // multiselect re-prefills against the new
                        // supported set instead of carrying over a stale
                        // (and possibly unsupported) selection.
                        setEntityTypes([]);
                      }}
                      workflowType={workflowType === 'approval' ? 'approval' : 'process'}
                      options={triggerTypeOptions.length > 0 ? triggerTypeOptions : undefined}
                    />
                  </div>
                  <div>
                    <EntityTypeMultiselect
                      triggerType={triggerType}
                      value={entityTypes as string[]}
                      onChange={(next) => setEntityTypes(next as EntityType[])}
                      supportedEntityTypes={
                        triggerTypeOptions.find((o) => o.value === triggerType)?.entity_types
                        // Fallback to the static FE map when the catalog
                        // is still loading or unavailable. Keeps the
                        // multiselect non-empty so saved configs are
                        // visible during the first render.
                        ?? ALL_ENTITY_TYPES.filter((et) => isTriggerEntitySupported(triggerType, et))
                      }
                    />
                  </div>
                  {(triggerType === 'on_status_change' || triggerType === 'before_status_change' || triggerType === 'on_request_status_change') && (
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <Label>{t('workflows:designer.triggerConfig.fromStatus')}</Label>
                        <Input
                          value={triggerFromStatus}
                          onChange={(e) => setTriggerFromStatus(e.target.value)}
                          placeholder={t('workflows:designer.triggerConfig.fromStatusPlaceholder')}
                        />
                      </div>
                      <div>
                        <Label>{t('workflows:designer.triggerConfig.toStatus')}</Label>
                        <Input
                          value={triggerToStatus}
                          onChange={(e) => setTriggerToStatus(e.target.value)}
                          placeholder={t('workflows:designer.triggerConfig.toStatusPlaceholder')}
                        />
                      </div>
                    </div>
                  )}

                  <div>
                    <Label>{t('common:labels.description')}</Label>
                    <Textarea
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                      placeholder={t('workflows:designer.triggerConfig.descriptionPlaceholder')}
                      rows={3}
                    />
                  </div>

                  <Separator />

                  <Button
                    className="w-full"
                    onClick={() => setSelectedNodeId(null)}
                  >
                    {t('workflows:designer.actions.done')}
                  </Button>
                </>
              ) : selectedStep ? (
                // Step configuration
                <>
                  <div>
                    <Label>{t('workflows:designer.stepConfig.stepName')}</Label>
                    <Input
                      value={selectedStep.name || ''}
                      onChange={(e) => updateStep(selectedStep.step_id, { name: e.target.value })}
                    />
                  </div>
                  <div>
                    <Label>{t('workflows:designer.stepConfig.stepType')}</Label>
                    <Input value={selectedStep.step_type} disabled />
                  </div>
                  
                  {/* Type-specific config */}
                  {selectedStep.step_type === 'entity_action' && (
                    <>
                      <div>
                        <Label>{t('workflows:designer.entityAction.action')}</Label>
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
                            <SelectItem value="certify">{t('workflows:designer.entityAction.certify')}</SelectItem>
                            <SelectItem value="decertify">{t('workflows:designer.entityAction.decertify')}</SelectItem>
                            <SelectItem value="publish">{t('workflows:designer.entityAction.publish')}</SelectItem>
                            <SelectItem value="unpublish">{t('workflows:designer.entityAction.unpublish')}</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      {((selectedStep.config as { action?: string })?.action || 'certify') === 'certify' && (
                        <>
                          <div>
                            <Label>{t('workflows:designer.entityAction.certLevelSource')}</Label>
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
                                <SelectItem value="from_request">{t('workflows:designer.entityAction.levelFromRequest')}</SelectItem>
                                <SelectItem value="fixed">{t('workflows:designer.entityAction.levelFixed')}</SelectItem>
                                <SelectItem value="from_approval">{t('workflows:designer.entityAction.levelFromApproval')}</SelectItem>
                              </SelectContent>
                            </Select>
                          </div>
                          {(selectedStep.config as { level_source?: string })?.level_source === 'fixed' && (
                            <div>
                              <Label>{t('workflows:designer.entityAction.fixedLevel')}</Label>
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
                                placeholder={t('workflows:designer.entityAction.fixedLevelPlaceholder')}
                              />
                            </div>
                          )}
                        </>
                      )}
                      {((selectedStep.config as { action?: string })?.action || '') === 'publish' && (
                        <>
                          <div>
                            <Label>{t('workflows:designer.entityAction.scopeSource')}</Label>
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
                                <SelectItem value="from_request">{t('workflows:designer.entityAction.scopeFromRequest')}</SelectItem>
                                <SelectItem value="fixed">{t('workflows:designer.entityAction.scopeFixed')}</SelectItem>
                                <SelectItem value="from_approval">{t('workflows:designer.entityAction.scopeFromApproval')}</SelectItem>
                              </SelectContent>
                            </Select>
                          </div>
                          {(selectedStep.config as { scope_source?: string })?.scope_source ===
                            'fixed' && (
                            <div>
                              <Label>{t('workflows:designer.entityAction.fixedScope')}</Label>
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
                                  <SelectItem value="domain">{t('workflows:designer.entityAction.scopeDomain')}</SelectItem>
                                  <SelectItem value="organization">{t('workflows:designer.entityAction.scopeOrganization')}</SelectItem>
                                  <SelectItem value="external">{t('workflows:designer.entityAction.scopeExternal')}</SelectItem>
                                </SelectContent>
                              </Select>
                            </div>
                          )}
                        </>
                      )}
                      <p className="text-xs text-muted-foreground">
                        {t('workflows:designer.entityAction.help')}
                      </p>
                    </>
                  )}

                  {selectedStep.step_type === 'user_action' && (
                    <>
                      <div>
                        <Label>{t('workflows:designer.userAction.title')}</Label>
                        <Input
                          value={(selectedStep.config as { title?: string })?.title || ''}
                          onChange={(e) => updateStep(selectedStep.step_id, {
                            config: { ...selectedStep.config, title: e.target.value },
                          })}
                          placeholder={t('workflows:designer.userAction.titlePlaceholder')}
                        />
                      </div>
                      <div>
                        <Label>{t('common:labels.description')}</Label>
                        <Textarea
                          value={(selectedStep.config as { description?: string })?.description || ''}
                          onChange={(e) => updateStep(selectedStep.step_id, {
                            config: { ...selectedStep.config, description: e.target.value },
                          })}
                          placeholder={t('workflows:designer.userAction.descriptionPlaceholder')}
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
                          {t('workflows:designer.userAction.requiresInput')}
                        </Label>
                      </div>
                      <p className="text-xs text-muted-foreground -mt-2">
                        {t('workflows:designer.userAction.requiresInputHelp')}
                      </p>
                      <div>
                        <Label>{t('workflows:designer.userAction.minInputLength')}</Label>
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
                          placeholder={t('workflows:designer.userAction.minInputPlaceholder')}
                        />
                        <p className="text-xs text-muted-foreground mt-1">
                          {t('workflows:designer.userAction.minInputHelp')}
                        </p>
                      </div>
                      <RequiredFieldsEditor
                        value={
                          ((selectedStep.config as { required_fields?: RequiredField[] })
                            ?.required_fields ?? []) as RequiredField[]
                        }
                        onChange={(next) =>
                          updateStep(selectedStep.step_id, {
                            config: {
                              ...selectedStep.config,
                              required_fields: next,
                            },
                          })
                        }
                        primaryFieldId={
                          (selectedStep.config as { primary_field_id?: string })?.primary_field_id
                        }
                        onPrimaryFieldIdChange={(nextId) =>
                          updateStep(selectedStep.step_id, {
                            config: {
                              ...selectedStep.config,
                              primary_field_id: nextId,
                            },
                          })
                        }
                        requiresInput={
                          (selectedStep.config as { requires_input?: boolean })?.requires_input ?? false
                        }
                        idPrefix={`rfe-${selectedStep.step_id}`}
                      />
                      <p className="text-xs text-muted-foreground">
                        {t('workflows:designer.userAction.fieldsHelp')}
                      </p>
                    </>
                  )}

                  {selectedStep.step_type === 'policy_check' && (
                    <div>
                      <Label>{t('workflows:designer.policyCheck.label')}</Label>
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
                          <SelectValue placeholder={t('workflows:designer.policyCheck.placeholder')} />
                        </SelectTrigger>
                        <SelectContent>
                          {compliancePolicies.length === 0 ? (
                            <div className="px-2 py-3 text-sm text-muted-foreground">
                              {t('workflows:designer.policyCheck.noPolicies')}
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
                        {t('workflows:designer.policyCheck.help')}
                      </p>
                    </div>
                  )}
                  
                  {selectedStep.step_type === 'validation' && (
                    <div>
                      <Label>{t('workflows:designer.validation.dslRule')}</Label>
                      <Textarea
                        value={(selectedStep.config as { rule?: string })?.rule || ''}
                        onChange={(e) => updateStep(selectedStep.step_id, {
                          config: { ...selectedStep.config, rule: e.target.value }
                        })}
                        placeholder={t('workflows:designer.validation.dslPlaceholder')}
                        rows={6}
                        className="font-mono text-sm"
                      />
                    </div>
                  )}
                  
                  {selectedStep.step_type === 'notification' && (
                    <>
                      {(() => {
                        const raw = (selectedStep.config as { recipients?: string })?.recipients || '';
                        const split = splitRoleAndPrincipals(raw);
                        const customOn =
                          (selectedStep.config as { recipients_custom?: boolean })?.recipients_custom
                            ?? split.principals.length > 0;
                        const setRole = (role: string) => {
                          const next = joinRoleAndPrincipals(role, split.principals);
                          updateStep(selectedStep.step_id, {
                            config: { ...selectedStep.config, recipients: next },
                          });
                        };
                        const setPrincipals = (principals: string[]) => {
                          const next = joinRoleAndPrincipals(split.roleToken, principals);
                          updateStep(selectedStep.step_id, {
                            config: { ...selectedStep.config, recipients: next },
                          });
                        };
                        const toggleCustom = (on: boolean) => {
                          // Persist the flag on the step config so the
                          // toggle state survives reloads. Clearing the
                          // picks when turning off keeps the wire shape
                          // unsurprising.
                          if (!on) {
                            updateStep(selectedStep.step_id, {
                              config: {
                                ...selectedStep.config,
                                recipients_custom: false,
                                recipients: joinRoleAndPrincipals(split.roleToken, []),
                              },
                            });
                          } else {
                            updateStep(selectedStep.step_id, {
                              config: { ...selectedStep.config, recipients_custom: true },
                            });
                          }
                        };
                        return (
                          <>
                            <div>
                              <Label>{t('workflows:designer.notification.recipientsRole')}</Label>
                              <Select value={split.roleToken} onValueChange={setRole}>
                                <SelectTrigger>
                                  <SelectValue placeholder={t('workflows:designer.notification.recipientsPlaceholder')} />
                                </SelectTrigger>
                                <SelectContent>
                                  {renderGroupedRoles(availableRoles, { requester: true, owner: true })}
                                </SelectContent>
                              </Select>
                            </div>
                            <div className="flex items-center justify-between rounded-md border p-3">
                              <div className="flex flex-col">
                                <Label className="text-sm">{t('workflows:designer.customPrincipals.label')}</Label>
                                <p className="text-xs text-muted-foreground">
                                  {t('workflows:designer.customPrincipals.help')}
                                </p>
                              </div>
                              <Switch checked={customOn} onCheckedChange={toggleCustom} />
                            </div>
                            {customOn && (
                              <div>
                                <Label>{t('workflows:designer.customPrincipals.usersGroups')}</Label>
                                <PrincipalPicker
                                  multiple
                                  accepts={['user', 'group']}
                                  value={split.principals}
                                  onChange={setPrincipals}
                                  placeholder={t('workflows:designer.customPrincipals.addPlaceholder')}
                                  aria-label={t('workflows:designer.notification.additionalRecipientsAria')}
                                />
                              </div>
                            )}
                          </>
                        );
                      })()}
                      <div>
                        <Label>{t('workflows:designer.notification.template')}</Label>
                        <Select
                          value={(selectedStep.config as { template?: string })?.template || ''}
                          onValueChange={(v) => updateStep(selectedStep.step_id, {
                            config: { ...selectedStep.config, template: v }
                          })}
                        >
                          <SelectTrigger>
                            <SelectValue placeholder={t('workflows:designer.notification.selectTemplate')} />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="request_submitted">{t('workflows:designer.notification.templates.requestSubmitted')}</SelectItem>
                            <SelectItem value="request_approved">{t('workflows:designer.notification.templates.requestApproved')}</SelectItem>
                            <SelectItem value="request_rejected">{t('workflows:designer.notification.templates.requestDenied')}</SelectItem>
                            <SelectItem value="validation_failed">{t('workflows:designer.notification.templates.validationFailed')}</SelectItem>
                            <SelectItem value="validation_passed">{t('workflows:designer.notification.templates.validationPassed')}</SelectItem>
                            <SelectItem value="product_approved">{t('workflows:designer.notification.templates.productApproved')}</SelectItem>
                            <SelectItem value="product_rejected">{t('workflows:designer.notification.templates.productRejected')}</SelectItem>
                            <SelectItem value="pii_detected">{t('workflows:designer.notification.templates.piiDetected')}</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div>
                        <Label>{t('workflows:designer.notification.customMessage')}</Label>
                        <Textarea
                          value={(selectedStep.config as { custom_message?: string })?.custom_message || ''}
                          onChange={(e) => updateStep(selectedStep.step_id, {
                            config: { ...selectedStep.config, custom_message: e.target.value }
                          })}
                          placeholder={t('workflows:designer.notification.customMessagePlaceholder')}
                          rows={3}
                        />
                        <p className="text-xs text-muted-foreground mt-1">
                          {t('workflows:designer.notification.variablesLabel')} <code className="text-xs">{'${entity_name}'}</code>, <code className="text-xs">{'${entity_type}'}</code>, <code className="text-xs">{'${user_email}'}</code>, <code className="text-xs">{'${entity.field}'}</code>, <code className="text-xs">{'${step_results.step_id.field}'}</code>
                        </p>
                      </div>
                      <div>
                        <Label className="mb-2 block">{t('workflows:designer.notification.channels')}</Label>
                        <div className="flex flex-col gap-2">
                          {(['in_app', 'webhook'] as const).map((ch) => (
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
                        <p className="text-xs text-muted-foreground mt-1">{t('workflows:designer.notification.channelsHelp')}</p>
                      </div>
                    </>
                  )}
                  
                  {selectedStep.step_type === 'assign_tag' && (
                    <>
                      <div>
                        <Label>{t('workflows:designer.assignTag.tagKey')}</Label>
                        <Input
                          value={(selectedStep.config as { key?: string })?.key || ''}
                          onChange={(e) => updateStep(selectedStep.step_id, {
                            config: { ...selectedStep.config, key: e.target.value }
                          })}
                          placeholder={t('workflows:designer.assignTag.tagKeyPlaceholder')}
                        />
                      </div>
                      <div>
                        <Label>{t('workflows:designer.assignTag.valueSource')}</Label>
                        <Select
                          value={(selectedStep.config as { value_source?: string })?.value_source || ''}
                          onValueChange={(v) => updateStep(selectedStep.step_id, {
                            config: { ...selectedStep.config, value_source: v }
                          })}
                        >
                          <SelectTrigger>
                            <SelectValue placeholder={t('workflows:designer.assignTag.selectSource')} />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="current_user">{t('workflows:designer.assignTag.sourceCurrentUser')}</SelectItem>
                            <SelectItem value="project_name">{t('workflows:designer.assignTag.sourceProjectName')}</SelectItem>
                            <SelectItem value="timestamp">{t('workflows:designer.assignTag.sourceTimestamp')}</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                    </>
                  )}
                  
                  {selectedStep.step_type === 'approval' && (
                    <>
                      {(() => {
                        const raw = (selectedStep.config as { approvers?: string })?.approvers || '';
                        const split = splitRoleAndPrincipals(raw);
                        const customOn =
                          (selectedStep.config as { approvers_custom?: boolean })?.approvers_custom
                            ?? split.principals.length > 0;
                        const setRole = (role: string) => {
                          const next = joinRoleAndPrincipals(role, split.principals);
                          updateStep(selectedStep.step_id, {
                            config: { ...selectedStep.config, approvers: next },
                          });
                        };
                        const setPrincipals = (principals: string[]) => {
                          const next = joinRoleAndPrincipals(split.roleToken, principals);
                          updateStep(selectedStep.step_id, {
                            config: { ...selectedStep.config, approvers: next },
                          });
                        };
                        const toggleCustom = (on: boolean) => {
                          if (!on) {
                            updateStep(selectedStep.step_id, {
                              config: {
                                ...selectedStep.config,
                                approvers_custom: false,
                                approvers: joinRoleAndPrincipals(split.roleToken, []),
                              },
                            });
                          } else {
                            updateStep(selectedStep.step_id, {
                              config: { ...selectedStep.config, approvers_custom: true },
                            });
                          }
                        };
                        return (
                          <>
                            <div>
                              <Label>{t('workflows:designer.approval.approversRole')}</Label>
                              <Select value={split.roleToken} onValueChange={setRole}>
                                <SelectTrigger>
                                  <SelectValue placeholder={t('workflows:designer.approval.selectRole')} />
                                </SelectTrigger>
                                <SelectContent>
                                  {renderGroupedRoles(approverRoles, { requester: true })}
                                </SelectContent>
                              </Select>
                            </div>
                            <div className="flex items-center justify-between rounded-md border p-3">
                              <div className="flex flex-col">
                                <Label className="text-sm">{t('workflows:designer.customPrincipals.label')}</Label>
                                <p className="text-xs text-muted-foreground">
                                  {t('workflows:designer.customPrincipals.help')}
                                </p>
                              </div>
                              <Switch checked={customOn} onCheckedChange={toggleCustom} />
                            </div>
                            {customOn && (
                              <div>
                                <Label>{t('workflows:designer.customPrincipals.usersGroups')}</Label>
                                <PrincipalPicker
                                  multiple
                                  accepts={['user', 'group']}
                                  value={split.principals}
                                  onChange={setPrincipals}
                                  placeholder={t('workflows:designer.customPrincipals.addPlaceholder')}
                                  aria-label={t('workflows:designer.approval.additionalApproversAria')}
                                />
                              </div>
                            )}
                          </>
                        );
                      })()}
                      <div>
                        <Label>{t('workflows:designer.approval.timeoutDays')}</Label>
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
                        <Label>{t('workflows:designer.assetReview.reviewerRole')}</Label>
                        <Select
                          value={(selectedStep.config as { reviewer_role?: string })?.reviewer_role || ''}
                          onValueChange={(v) => updateStep(selectedStep.step_id, {
                            config: { ...selectedStep.config, reviewer_role: v }
                          })}
                        >
                          <SelectTrigger>
                            <SelectValue placeholder={t('workflows:designer.assetReview.selectReviewerRole')} />
                          </SelectTrigger>
                          <SelectContent>
                            {renderGroupedRoles(availableRoles)}
                          </SelectContent>
                        </Select>
                        <p className="text-xs text-muted-foreground mt-1">
                          {t('workflows:designer.assetReview.reviewerRoleHelp')}
                        </p>
                      </div>
                      <div>
                        <Label>{t('workflows:designer.assetReview.reviewType')}</Label>
                        <Select
                          value={(selectedStep.config as { review_type?: string })?.review_type || 'standard'}
                          onValueChange={(v) => updateStep(selectedStep.step_id, {
                            config: { ...selectedStep.config, review_type: v }
                          })}
                        >
                          <SelectTrigger>
                            <SelectValue placeholder={t('workflows:designer.assetReview.selectReviewType')} />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="standard">{t('workflows:designer.assetReview.typeStandard')}</SelectItem>
                            <SelectItem value="expedited">{t('workflows:designer.assetReview.typeExpedited')}</SelectItem>
                            <SelectItem value="compliance">{t('workflows:designer.assetReview.typeCompliance')}</SelectItem>
                            <SelectItem value="security">{t('workflows:designer.assetReview.typeSecurity')}</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div>
                        <Label>{t('common:labels.notes')}</Label>
                        <Textarea
                          value={(selectedStep.config as { notes?: string })?.notes || ''}
                          onChange={(e) => updateStep(selectedStep.step_id, {
                            config: { ...selectedStep.config, notes: e.target.value }
                          })}
                          placeholder={t('workflows:designer.assetReview.notesPlaceholder')}
                          rows={2}
                        />
                      </div>
                    </>
                  )}

                  {selectedStep.step_type === 'webhook' && (
                    <>
                      <div>
                        <Label>{t('workflows:designer.webhook.mode')}</Label>
                        <Select
                          value={(selectedStep.config as { connection_name?: string })?.connection_name !== undefined ? 'connection' : 'inline'}
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
                            <SelectValue placeholder={t('workflows:designer.webhook.selectMode')} />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="connection">{t('workflows:designer.webhook.modeConnection')}</SelectItem>
                            <SelectItem value="inline">{t('workflows:designer.webhook.modeInline')}</SelectItem>
                          </SelectContent>
                        </Select>
                        <p className="text-xs text-muted-foreground mt-1">
                          {t('workflows:designer.webhook.modeHelp')}
                        </p>
                      </div>
                      
                      {(selectedStep.config as { connection_name?: string })?.connection_name !== undefined && (
                        <>
                          <div>
                            <Label>{t('workflows:designer.webhook.httpConnection')}</Label>
                            <Select
                              value={(selectedStep.config as { connection_name?: string })?.connection_name || ''}
                              onValueChange={(v) => updateStep(selectedStep.step_id, {
                                config: { ...selectedStep.config, connection_name: v }
                              })}
                            >
                              <SelectTrigger>
                                <SelectValue placeholder={t('workflows:designer.webhook.selectConnection')} />
                              </SelectTrigger>
                              <SelectContent>
                                {httpConnections.length === 0 ? (
                                  <div className="px-2 py-3 text-sm text-muted-foreground">
                                    {t('workflows:designer.webhook.noConnections')}
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
                            <Label>{t('common:labels.path')}</Label>
                            <Input
                              value={(selectedStep.config as { path?: string })?.path || ''}
                              onChange={(e) => updateStep(selectedStep.step_id, {
                                config: { ...selectedStep.config, path: e.target.value }
                              })}
                              placeholder={t('workflows:designer.webhook.pathPlaceholder')}
                            />
                            <p className="text-xs text-muted-foreground mt-1">
                              {t('workflows:designer.webhook.pathHelp')}
                            </p>
                          </div>
                        </>
                      )}
                      
                      {(selectedStep.config as { url?: string })?.url !== undefined && (
                        <div>
                          <Label>{t('workflows:designer.webhook.url')}</Label>
                          <Input
                            value={(selectedStep.config as { url?: string })?.url || ''}
                            onChange={(e) => updateStep(selectedStep.step_id, {
                              config: { ...selectedStep.config, url: e.target.value }
                            })}
                            placeholder={t('workflows:designer.webhook.urlPlaceholder')}
                          />
                          <p className="text-xs text-amber-600 mt-1">
                            {t('workflows:designer.webhook.inlineWarning')}
                          </p>
                        </div>
                      )}
                      
                      <div>
                        <Label>{t('workflows:designer.webhook.httpMethod')}</Label>
                        <Select
                          value={(selectedStep.config as { method?: string })?.method || 'POST'}
                          onValueChange={(v) => updateStep(selectedStep.step_id, {
                            config: { ...selectedStep.config, method: v }
                          })}
                        >
                          <SelectTrigger>
                            <SelectValue placeholder={t('workflows:designer.webhook.selectMethod')} />
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
                        <Label>{t('workflows:designer.webhook.bodyTemplate')}</Label>
                        {/* Two-column layout: textarea on the left, the
                            variable inspector on the right. The inspector
                            stacks below the textarea on narrow screens via
                            the responsive ``md:`` breakpoint. */}
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-1">
                          <div>
                            <Textarea
                              value={(selectedStep.config as { body_template?: string })?.body_template || ''}
                              onChange={(e) => updateStep(selectedStep.step_id, {
                                config: { ...selectedStep.config, body_template: e.target.value }
                              })}
                              placeholder={t('workflows:designer.webhook.bodyPlaceholder')}
                              rows={8}
                              className="font-mono text-sm"
                            />
                            <p className="text-xs text-muted-foreground mt-1">
                              {t('workflows:designer.webhook.bodyHelp')}
                            </p>
                          </div>
                          <TemplateVarsInspector
                            triggerType={triggerType}
                            entityType={entityTypes[0]}
                          />
                        </div>
                      </div>

                      {/* Extra parameters forwarded into the UC HTTPConnection call (issue #401).
                          These augment what the connection's static config provides — useful when
                          the downstream service needs context-derived headers, query string params,
                          or path segments computed from ${entity.*} / ${trigger.*}. */}
                      <KeyValueEditor
                        label={t('workflows:designer.webhook.additionalHeaders')}
                        helpText={t('workflows:designer.webhook.additionalHeadersHelp')}
                        keyPlaceholder={t('workflows:designer.webhook.headerKeyPlaceholder')}
                        valuePlaceholder={t('workflows:designer.webhook.headerValuePlaceholder')}
                        value={(selectedStep.config as { additional_headers?: Record<string, string> })?.additional_headers || {}}
                        onChange={(next) => updateStep(selectedStep.step_id, {
                          config: { ...selectedStep.config, additional_headers: next },
                        })}
                      />

                      <KeyValueEditor
                        label={t('workflows:designer.webhook.additionalQueryParams')}
                        helpText={t('workflows:designer.webhook.additionalQueryParamsHelp')}
                        keyPlaceholder={t('workflows:designer.webhook.queryKeyPlaceholder')}
                        valuePlaceholder={t('workflows:designer.webhook.queryValuePlaceholder')}
                        value={(selectedStep.config as { additional_query_params?: Record<string, string> })?.additional_query_params || {}}
                        onChange={(next) => updateStep(selectedStep.step_id, {
                          config: { ...selectedStep.config, additional_query_params: next },
                        })}
                      />

                      <div>
                        <Label>{t('workflows:designer.webhook.pathSuffix')}</Label>
                        <Input
                          value={(selectedStep.config as { path_suffix?: string })?.path_suffix || ''}
                          onChange={(e) => updateStep(selectedStep.step_id, {
                            config: { ...selectedStep.config, path_suffix: e.target.value },
                          })}
                          placeholder={t('workflows:designer.webhook.pathSuffixPlaceholder')}
                        />
                        <p className="text-xs text-muted-foreground mt-1">
                          {t('workflows:designer.webhook.pathSuffixHelp')}
                        </p>
                      </div>

                      <div>
                        <Label>{t('workflows:designer.webhook.timeoutSeconds')}</Label>
                        <Input
                          type="number"
                          value={(selectedStep.config as { timeout_seconds?: number })?.timeout_seconds || 30}
                          onChange={(e) => updateStep(selectedStep.step_id, { 
                            config: { ...selectedStep.config, timeout_seconds: parseInt(e.target.value) || 30 }
                          })}
                        />
                      </div>
                      
                      <div>
                        <Label>{t('workflows:designer.webhook.retryCount')}</Label>
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
                          {t('workflows:designer.webhook.retryHelp')}
                        </p>
                      </div>
                    </>
                  )}

                  {/* Schema-driven config for new step types */}
                  {SCHEMA_DRIVEN_STEP_TYPES.includes(selectedStep.step_type) && (
                    <SchemaConfigPanel
                      schema={_stepTypes.find(s => s.type === selectedStep.step_type)?.config_schema || {}}
                      config={selectedStep.config as Record<string, unknown>}
                      onUpdate={(newConfig) => updateStep(selectedStep.step_id, { config: newConfig })}
                    />
                  )}

                  <Separator />

                  {(() => {
                    // Gate Done on the missing-primary rule for user_action steps.
                    // For other step types the gate is always satisfied (true).
                    const userActionInvalid =
                      selectedStep.step_type === 'user_action' &&
                      !isPrimaryFieldValid(
                        ((selectedStep.config as { required_fields?: RequiredField[] })
                          ?.required_fields ?? []) as RequiredField[],
                        (selectedStep.config as { primary_field_id?: string })?.primary_field_id,
                        (selectedStep.config as { requires_input?: boolean })?.requires_input ?? false,
                      );
                    return (
                      <div className="flex gap-2">
                        <Button
                          className="flex-1"
                          onClick={() => setSelectedNodeId(null)}
                          disabled={userActionInvalid}
                          title={
                            userActionInvalid
                              ? t('workflows:designer.userAction.primaryRequiredTooltip')
                              : undefined
                          }
                          data-testid="step-config-done"
                        >
                          {t('workflows:designer.actions.done')}
                        </Button>
                        <Button
                          variant="destructive"
                          size="icon"
                          onClick={() => deleteStep(selectedStep.step_id)}
                          title={t('workflows:designer.stepConfig.deleteStep')}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    );
                  })()}
                </>
              ) : null}
            </div>
          </SheetContent>
        </Sheet>
      </div>
    </div>
  );
}

