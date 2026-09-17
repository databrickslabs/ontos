import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Link as RouterLink } from 'react-router-dom';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Loader2, Check, XCircle, ExternalLink } from 'lucide-react';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { getUnderlyingEntityDetailPath } from '@/lib/entity-detail-path';

/** Built from GET /api/workflows/for-trigger/for_approval_response (first step used for dialog). */
interface DefaultResponseWorkflowStep {
  workflow_id: string;
  workflow_name: string;
  step_id: string;
  step_name: string;
  step_type: string;
  config: {
    title?: string;
    description?: string;
    required_fields?: Array<{ id: string; label: string; type: string; required?: boolean }>;
  };
}

export interface WorkflowApprovalResponseDialogPayload {
  execution_id: string;
  entity_name?: string;
  // Structured request context populated by the backend approval step
  // (see ApprovalStepHandler in workflow_executor.py). All optional — only
  // access-grant triggers populate the underlying_* / permission / duration
  // / reason fields today, but the dialog renders whatever is present.
  requester_email?: string;
  entity_type?: string;
  entity_id?: string;
  underlying_entity_type?: string;
  underlying_entity_id?: string;
  underlying_entity_name?: string;
  permission_level?: string;
  requested_duration_days?: number;
  reason?: string;
  request_id?: string;
  workflow_name?: string;
  workflow_message?: string;
  on_behalf_of?: { type: string; value: string };
  full_payload?: Record<string, unknown>;
}

interface WorkflowApprovalResponseDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  payload: WorkflowApprovalResponseDialogPayload | null;
  notificationId?: string;
  onDecisionMade?: () => void;
}

const ENTITY_TYPE_LABELS: Record<string, string> = {
  data_product: 'Data Product',
  data_contract: 'Data Contract',
  data_domain: 'Data Domain',
  data_asset_review: 'Data Asset Review',
  access_grant: 'Access Grant',
  asset: 'Asset',
};

function humanizeEntityType(entityType: string | undefined | null): string {
  if (!entityType) return 'Entity';
  const key = entityType.toLowerCase();
  if (ENTITY_TYPE_LABELS[key]) return ENTITY_TYPE_LABELS[key];
  return entityType
    .replace(/_/g, ' ')
    .split(' ')
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(' ');
}

const SKIP_KEYS = new Set([
  'entity_id', 'entity_type', 'underlying_entity_id', 'underlying_entity_type',
  'request_id', 'workspace_id', 'execution_id', 'workflow_id',
]);

function renderPayloadValue(val: unknown): string {
  if (Array.isArray(val)) return val.join(', ');
  if (typeof val === 'object' && val !== null) return JSON.stringify(val);
  return String(val);
}

function humanizeKey(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

interface DetailRow {
  label: string;
  value: React.ReactNode;
}

function buildDetailRows(
  payload: WorkflowApprovalResponseDialogPayload,
  onNavigate: () => void,
  t: (key: string, options?: Record<string, unknown>) => string,
): DetailRow[] {
  const rows: DetailRow[] = [];

  if (payload.requester_email) {
    rows.push({ label: t('common:labels.requester'), value: payload.requester_email });
  }

  if (payload.on_behalf_of) {
    rows.push({
      label: t('workflows:approvalResponse.rows.onBehalfOf'),
      value: `${payload.on_behalf_of.type} ${payload.on_behalf_of.value}`,
    });
  }

  const resourceType = payload.underlying_entity_type ?? payload.entity_type;
  const resourceName =
    payload.underlying_entity_name ??
    (resourceType && resourceType.toLowerCase() !== 'access_grant'
      ? payload.entity_name
      : undefined);
  const resourceId = payload.underlying_entity_id ?? payload.entity_id;
  if (resourceType || resourceName || resourceId) {
    const typeLabel = humanizeEntityType(resourceType);
    const displayName = resourceName || resourceId || '—';
    const detailPath = getUnderlyingEntityDetailPath(
      payload as unknown as Record<string, unknown>,
    );
    const resourceText = `${typeLabel} · ${displayName}`;
    rows.push({
      label: t('workflows:approvalResponse.rows.resource'),
      value: detailPath ? (
        <RouterLink
          to={detailPath}
          onClick={onNavigate}
          className="inline-flex items-center gap-1 text-primary hover:underline"
        >
          {resourceText}
          <ExternalLink className="h-3 w-3" />
        </RouterLink>
      ) : (
        resourceText
      ),
    });
  }

  if (payload.permission_level) {
    rows.push({ label: t('common:labels.permission'), value: payload.permission_level });
  }

  if (typeof payload.requested_duration_days === 'number') {
    const d = payload.requested_duration_days;
    rows.push({ label: t('workflows:approvalResponse.rows.duration'), value: t('workflows:approvalResponse.days', { count: d }) });
  }

  if (payload.reason) {
    rows.push({ label: t('workflows:approvalResponse.rows.reason'), value: payload.reason });
  }

  if (payload.workflow_message) {
    rows.push({ label: t('common:labels.message'), value: payload.workflow_message });
  }

  if (payload.workflow_name) {
    rows.push({ label: t('workflows:approvalResponse.rows.workflow'), value: payload.workflow_name });
  }

  if (payload.full_payload) {
    const alreadySurfaced = new Set([
      'requester_email', 'on_behalf_of', 'entity_type', 'entity_id', 'entity_name',
      'underlying_entity_type', 'underlying_entity_id', 'underlying_entity_name',
      'permission_level', 'requested_duration_days', 'reason',
      'message', 'workflow_name', 'workflow_id', 'execution_id', 'request_id',
      'workspace_id', 'step_results', 'required_fields_answers', 'data_product_name',
    ]);
    for (const [key, val] of Object.entries(payload.full_payload)) {
      if (key.startsWith('_')) continue;
      if (SKIP_KEYS.has(key)) continue;
      if (alreadySurfaced.has(key)) continue;
      if (val === null || val === undefined || val === '') continue;
      rows.push({ label: humanizeKey(key), value: renderPayloadValue(val) });
    }
  }

  return rows;
}

export default function WorkflowApprovalResponseDialog({
  isOpen,
  onOpenChange,
  payload,
  notificationId: _notificationId,
  onDecisionMade,
}: WorkflowApprovalResponseDialogProps) {
  const { t } = useTranslation(['workflows', 'common']);
  const { get, post } = useApi();
  const { toast } = useToast();
  const [stepConfig, setStepConfig] = useState<DefaultResponseWorkflowStep | null>(null);
  const [loadingConfig, setLoadingConfig] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [reason, setReason] = useState('');
  const [grantedDays, setGrantedDays] = useState<number | ''>(payload?.requested_duration_days ?? '');
  const [grantedPermission, setGrantedPermission] = useState<string>(payload?.permission_level ?? '');

  useEffect(() => {
    if (isOpen) {
      setGrantedDays(payload?.requested_duration_days ?? '');
      setGrantedPermission(payload?.permission_level ?? '');
    }
  }, [isOpen, payload]);

  useEffect(() => {
    if (!isOpen) {
      setStepConfig(null);
      setReason('');
      return;
    }
    let cancelled = false;
    setLoadingConfig(true);
    get<{ id: string; name: string; steps: Array<{ step_id: string; name: string | null; step_type: string; config: Record<string, unknown> }> }>(
      '/api/workflows/for-trigger/for_approval_response',
    )
      .then((res) => {
        if (cancelled) return;
        const w = res.data;
        if (w?.steps?.length) {
          const first = w.steps[0];
          setStepConfig({
            workflow_id: w.id,
            workflow_name: w.name,
            step_id: first.step_id,
            step_name: first.name ?? first.step_id,
            step_type: first.step_type,
            config: (first.config ?? {}) as DefaultResponseWorkflowStep['config'],
          });
        } else setStepConfig(null);
      })
      .catch(() => {
        if (!cancelled) setStepConfig(null);
      })
      .finally(() => {
        if (!cancelled) setLoadingConfig(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen, get]);

  const config = stepConfig?.config ?? {};
  const requiredFields = config.required_fields ?? [];
  const reasonField = requiredFields.find((f) => f.id === 'reason' || f.type === 'text');
  const isReasonRequired = reasonField?.required ?? false;

  const handleSubmit = async (approved: boolean) => {
    if (!payload?.execution_id) return;
    if (isReasonRequired && !reason.trim()) {
      toast({
        title: t('workflows:approvalResponse.messages.reasonRequiredTitle'),
        description: t('workflows:approvalResponse.messages.reasonRequiredDesc'),
        variant: 'destructive',
      });
      return;
    }
    setSubmitting(true);
    try {
      const body: Record<string, unknown> = {
        execution_id: payload.execution_id,
        approved,
        message: reason.trim() || (approved ? t('workflows:approvalResponse.approved') : t('workflows:approvalResponse.rejected')),
      };
      if (grantedDays !== '') body.granted_duration_days = Number(grantedDays);
      if (grantedPermission) body.permission_level = grantedPermission;
      const response = await post('/api/workflows/handle-approval', body);
      if (response.error) {
        toast({
          title: t('common:toast.error'),
          description: response.error || t('workflows:approvalResponse.messages.processFailed'),
          variant: 'destructive',
        });
        return;
      }
      toast({
        title: approved ? t('workflows:approvalResponse.approved') : t('workflows:approvalResponse.rejected'),
        description: approved
          ? t('workflows:approvalResponse.messages.entityApproved', { name: payload.entity_name || t('workflows:approvalResponse.requestFallback') })
          : t('workflows:approvalResponse.messages.entityRejected', { name: payload.entity_name || t('workflows:approvalResponse.requestFallback') }),
        variant: approved ? 'default' : 'destructive',
      });
      onOpenChange(false);
      onDecisionMade?.();
    } catch (e) {
      console.error('Workflow approval failed:', e);
      toast({
        title: t('common:toast.error'),
        description: t('workflows:approvalResponse.messages.processFailedRetry'),
        variant: 'destructive',
      });
    } finally {
      setSubmitting(false);
    }
  };

  const title = config.title ?? stepConfig?.step_name ?? t('workflows:approvalResponse.titleFallback');
  const description =
    config.description ?? t('workflows:approvalResponse.descriptionFallback');

  const detailRows = payload ? buildDetailRows(payload, () => onOpenChange(false), t) : [];

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md flex flex-col max-h-[85vh] overflow-hidden">
        <DialogHeader className="shrink-0">
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        {loadingConfig ? (
          <div className="flex flex-1 items-center justify-center py-8">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <>
            <div className="flex-1 overflow-y-auto space-y-4 px-1 -mx-1">
            {detailRows.length > 0 && (
              <div className="rounded-md border bg-muted/30 p-3 space-y-1.5">
                <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                  {t('workflows:approvalResponse.requestDetails')}
                </div>
                <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 text-sm">
                  {detailRows.map((row) => (
                    <div key={row.label} className="contents">
                      <dt className="text-muted-foreground">{row.label}</dt>
                      <dd className="break-words">{row.value}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            )}
            {(payload?.requested_duration_days != null || payload?.permission_level) && (
              <div className="rounded-md border p-3 space-y-3">
                <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                  {t('workflows:approvalResponse.adjustTerms')}
                </div>
                {payload.requested_duration_days != null && (
                  <div className="space-y-1">
                    <Label htmlFor="granted-days" className="text-sm">{t('workflows:approvalResponse.durationDays')}</Label>
                    <Input
                      id="granted-days"
                      type="number"
                      min={1}
                      value={grantedDays}
                      onChange={(e) => setGrantedDays(e.target.value === '' ? '' : Number(e.target.value))}
                      disabled={submitting}
                      className="w-32"
                    />
                  </div>
                )}
                {payload.permission_level && (
                  <div className="space-y-1">
                    <Label className="text-sm">{t('workflows:approvalResponse.permissionLevel')}</Label>
                    <Select value={grantedPermission} onValueChange={setGrantedPermission} disabled={submitting}>
                      <SelectTrigger className="w-48">
                        <SelectValue placeholder={t('common:placeholders.selectPermission')} />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="CAN_READ">CAN_READ</SelectItem>
                        <SelectItem value="CAN_USE">CAN_USE</SelectItem>
                        <SelectItem value="CAN_EDIT">CAN_EDIT</SelectItem>
                        <SelectItem value="CAN_MANAGE">CAN_MANAGE</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                )}
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="approval-reason">
                {reasonField?.label ?? t('workflows:approvalResponse.reasonLabel')}
                {isReasonRequired && ' *'}
              </Label>
              <Textarea
                id="approval-reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder={t('workflows:approvalResponse.reasonPlaceholder')}
                rows={3}
                className="resize-none"
                disabled={submitting}
              />
            </div>
            </div>
            <DialogFooter className="gap-2 sm:gap-0 shrink-0">
              <Button
                variant="destructive"
                disabled={submitting}
                onClick={() => handleSubmit(false)}
              >
                {submitting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <XCircle className="h-4 w-4" />
                )}
                {t('common:actions.reject')}
              </Button>
              <Button
                variant="default"
                className="bg-green-600 hover:bg-green-700"
                disabled={submitting}
                onClick={() => handleSubmit(true)}
              >
                {submitting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Check className="h-4 w-4" />
                )}
                {t('common:actions.approve')}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
