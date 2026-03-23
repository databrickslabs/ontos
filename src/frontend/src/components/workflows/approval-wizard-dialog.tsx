/**
 * Approval wizard dialog: run an approval workflow (multi-step) for an entity.
 * Creates session, shows steps (user_action: fields, acceptances), submits until complete or abort.
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { Loader2, Check, XCircle, ChevronRight } from 'lucide-react';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';

interface ApprovalWorkflowRef {
  id: string;
  name: string;
  description?: string;
  steps: Array<{ step_id: string; name: string; step_type: string; config: Record<string, unknown> }>;
}

interface WizardStep {
  step_id: string;
  name: string;
  step_type: string;
  config: Record<string, unknown>;
  order?: number;
  index?: number;
}

export interface ApprovalWizardDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  entityType: string;
  entityId: string;
  preselectedWorkflowId?: string;
  /** When set (e.g. 'subscribe'), session is created with completion_action; backend runs that after wizard complete. */
  completionAction?: string;
  /** When true and preselectedWorkflowId is set, start session immediately without showing workflow list. */
  autoStartWithPreselected?: boolean;
  onComplete?: (agreementId: string | null, pdfStoragePath: string | null) => void;
}

export default function ApprovalWizardDialog({
  isOpen,
  onOpenChange,
  entityType,
  entityId,
  preselectedWorkflowId,
  completionAction,
  autoStartWithPreselected,
  onComplete,
}: ApprovalWizardDialogProps) {
  const { get, post } = useApi();
  const { toast } = useToast();
  const [workflows, setWorkflows] = useState<ApprovalWorkflowRef[]>([]);
  const [, setSelectedWorkflowId] = useState<string | null>(preselectedWorkflowId ?? null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [currentStep, setCurrentStep] = useState<WizardStep | null>(null);
  const [, setStepResults] = useState<Array<{ step_id: string; payload: Record<string, unknown> }>>([]);
  const [payload, setPayload] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [completeResult, setCompleteResult] = useState<{ agreement_id: string | null; pdf_storage_path: string | null } | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    setSessionId(null);
    setCurrentStep(null);
    setStepResults([]);
    setPayload({});
    setCompleteResult(null);
    setSelectedWorkflowId(preselectedWorkflowId ?? null);
    let cancelled = false;
    get<{ workflows: ApprovalWorkflowRef[]; total: number }>('/api/workflows?workflow_type=approval')
      .then((res) => {
        if (cancelled || !res.data) return;
        setWorkflows(Array.isArray(res.data?.workflows) ? res.data.workflows : []);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [isOpen, preselectedWorkflowId, get]);

  const startSession = useCallback(
    async (workflowId: string) => {
      setLoading(true);
      try {
        const body: Record<string, string> = {
          workflow_id: workflowId,
          entity_type: entityType,
          entity_id: entityId,
        };
        if (completionAction) body.completion_action = completionAction;
        const res = await post<{ session_id: string; current_step: WizardStep; step_results: unknown[] }>(
          '/api/approvals/sessions',
          body,
        );
        if (res.error || !res.data) {
          toast({ title: 'Error', description: res.error || 'Failed to start session', variant: 'destructive' });
          return;
        }
        setSessionId((res.data as { session_id: string }).session_id);
        setCurrentStep((res.data as { current_step: WizardStep }).current_step);
        setStepResults(((res.data as { step_results?: unknown[] }).step_results ?? []) as Array<{ step_id: string; payload: Record<string, unknown> }>);
        setPayload({});
      } catch (e) {
        toast({ title: 'Error', description: 'Failed to start session', variant: 'destructive' });
      } finally {
        setLoading(false);
      }
    },
    [entityType, entityId, completionAction, post, toast],
  );

  useEffect(() => {
    if (
      isOpen &&
      autoStartWithPreselected &&
      preselectedWorkflowId &&
      workflows.length > 0 &&
      !sessionId &&
      !loading &&
      workflows.some((w) => w.id === preselectedWorkflowId)
    ) {
      startSession(preselectedWorkflowId);
    }
  }, [isOpen, autoStartWithPreselected, preselectedWorkflowId, workflows, sessionId, loading, startSession]);

  const submitStep = async () => {
    if (!sessionId || !currentStep) return;
    setLoading(true);
    try {
      const res = await post<{ complete?: boolean; agreement_id?: string; pdf_storage_path?: string; current_step?: WizardStep; step_results?: unknown[] }>(
        `/api/approvals/sessions/${sessionId}/steps`,
        { step_id: currentStep.step_id, payload },
      );
      if (res.error || !res.data) {
        toast({ title: 'Error', description: (res as { error?: string }).error || 'Failed to submit step', variant: 'destructive' });
        return;
      }
      const data = res.data as { complete?: boolean; agreement_id?: string; pdf_storage_path?: string; current_step?: WizardStep; step_results?: unknown[] };
      if (data.complete) {
        setCompleteResult({ agreement_id: data.agreement_id ?? null, pdf_storage_path: data.pdf_storage_path ?? null });
        setCurrentStep(null);
        onComplete?.(data.agreement_id ?? null, data.pdf_storage_path ?? null);
      } else {
        setCurrentStep(data.current_step ?? null);
        setStepResults((data.step_results as Array<{ step_id: string; payload: Record<string, unknown> }>) ?? []);
        setPayload({});
      }
    } catch (e) {
      toast({ title: 'Error', description: 'Failed to submit step', variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  };

  const abortSession = async () => {
    if (!sessionId) {
      onOpenChange(false);
      return;
    }
    setLoading(true);
    try {
      await post(`/api/approvals/sessions/${sessionId}/abort`, {});
    } catch {
      // ignore
    }
    setLoading(false);
    onOpenChange(false);
  };

  const requiredFields = (currentStep?.config?.required_fields as Array<{ id: string; label: string; type: string; required?: boolean }>) ?? [];
  const config = (currentStep?.config ?? {}) as {
    requires_input?: boolean;
    minimum_input_length?: number;
    primary_field_id?: string;
  };
  const primaryFieldId =
    config.primary_field_id ||
    requiredFields.find((f) => f.required)?.id ||
    requiredFields[0]?.id ||
    'reason';
  const primaryValue = payload[primaryFieldId]?.trim() ?? '';
  const requiredFieldsValid = requiredFields.filter((f) => f.required).every((f) => (payload[f.id]?.trim() ?? '').length > 0);
  const requiresInputValid = !config.requires_input || primaryValue.length > 0;
  const minLengthValid =
    config.minimum_input_length == null || primaryValue.length >= config.minimum_input_length;
  const isStepValid = requiredFieldsValid && requiresInputValid && minLengthValid;

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Approval wizard</DialogTitle>
          <DialogDescription>
            {!sessionId ? 'Choose an approval workflow to run for this entity.' : currentStep ? `Step: ${currentStep.name}` : completeResult ? 'Completed.' : 'Loading…'}
          </DialogDescription>
        </DialogHeader>

        {completeResult && (
          <div className="space-y-2 py-4">
            <p className="text-sm text-muted-foreground">Agreement recorded.</p>
            {completeResult.agreement_id && (
              <p className="text-xs text-muted-foreground">Agreement ID: {completeResult.agreement_id}</p>
            )}
            {completeResult.pdf_storage_path && (
              <p className="text-xs text-muted-foreground">PDF: {completeResult.pdf_storage_path}</p>
            )}
            <DialogFooter>
              <Button onClick={() => onOpenChange(false)}>Close</Button>
            </DialogFooter>
          </div>
        )}

        {!sessionId && (
          <div className="space-y-2 py-4">
            {workflows.length === 0 && !loading && (
              <p className="text-sm text-muted-foreground">No approval workflows available. Add them in Settings → Workflows (Approval workflows).</p>
            )}
            {workflows.map((wf) => (
              <Button
                key={wf.id}
                variant="outline"
                className="w-full justify-between"
                disabled={loading}
                onClick={() => startSession(wf.id)}
              >
                <span>{wf.name}</span>
                <ChevronRight className="h-4 w-4" />
              </Button>
            ))}
            <DialogFooter>
              <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
            </DialogFooter>
          </div>
        )}

        {sessionId && currentStep && (
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              {(currentStep.config?.title as string) && (
                <Label className="text-base">{(currentStep.config.title as string)}</Label>
              )}
              {(currentStep.config?.description as string) && (
                <p className="text-sm text-muted-foreground">{(currentStep.config.description as string)}</p>
              )}
              {requiredFields.map((f) => (
                <div key={f.id} className="space-y-1">
                  <Label htmlFor={f.id}>{f.label}{f.required ? ' *' : ''}</Label>
                  {f.type === 'text' && (
                    <Textarea
                      id={f.id}
                      value={payload[f.id] ?? ''}
                      onChange={(e) => setPayload((p) => ({ ...p, [f.id]: e.target.value }))}
                      placeholder={f.label}
                      rows={2}
                      disabled={loading}
                    />
                  )}
                  {f.type !== 'text' && (
                    <Input
                      id={f.id}
                      value={payload[f.id] ?? ''}
                      onChange={(e) => setPayload((p) => ({ ...p, [f.id]: e.target.value }))}
                      placeholder={f.label}
                      disabled={loading}
                    />
                  )}
                </div>
              ))}
            </div>
            {!isStepValid && (config.requires_input || (config.minimum_input_length != null && config.minimum_input_length > 0)) && (
              <p className="text-xs text-amber-600 dark:text-amber-400">
                {!requiresInputValid && config.requires_input && 'This step requires input.'}
                {requiresInputValid && !minLengthValid && config.minimum_input_length != null && config.minimum_input_length > 0 &&
                  `Minimum length: ${config.minimum_input_length} characters (${primaryValue.length} entered).`}
              </p>
            )}
            <DialogFooter>
              <Button variant="ghost" onClick={abortSession} disabled={loading}>
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <XCircle className="h-4 w-4" />}
                Abort
              </Button>
              <Button onClick={submitStep} disabled={loading || !isStepValid}>
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                Next
              </Button>
            </DialogFooter>
          </div>
        )}

        {sessionId && !currentStep && !completeResult && loading && (
          <div className="flex justify-center py-8">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
