/**
 * Approval wizard dialog: run an approval workflow (multi-step) for an entity.
 * Creates session, shows steps (user_action: fields, acceptances), submits until complete or abort.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
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

/** Step types that require no user interaction and should auto-advance. */
const NON_VISUAL_STEP_TYPES = new Set(['persist_agreement', 'generate_pdf', 'deliver']);

export interface ApprovalWizardDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  entityType: string;
  entityId: string;
  /** Human-readable name of the entity (shown in the contextual header). */
  entityName?: string;
  preselectedWorkflowId?: string;
  /** When set (e.g. 'subscribe'), session is created with completion_action; backend runs that after wizard complete. */
  completionAction?: string;
  /** When true and preselectedWorkflowId is set, start session immediately without showing workflow list. */
  autoStartWithPreselected?: boolean;
  onComplete?: (agreementId: string | null, pdfStoragePath: string | null) => void;
  /** Called when no workflow is available so the caller can proceed directly. */
  onNoWorkflow?: () => void;
}

export default function ApprovalWizardDialog({
  isOpen,
  onOpenChange,
  entityType,
  entityId,
  entityName,
  preselectedWorkflowId,
  completionAction,
  autoStartWithPreselected,
  onComplete,
  onNoWorkflow,
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
  /** Total steps and current index (0-based) for the progress indicator. */
  const [totalSteps, setTotalSteps] = useState(0);
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  /** Step names for displaying in the progress indicator. */
  const [stepNames, setStepNames] = useState<string[]>([]);
  /** Track whether workflows have been loaded (to distinguish empty from not-yet-loaded). */
  const [workflowsLoaded, setWorkflowsLoaded] = useState(false);
  /** Ref to prevent duplicate auto-submit for non-visual steps. */
  const autoSubmitRef = useRef<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    setSessionId(null);
    setCurrentStep(null);
    setStepResults([]);
    setPayload({});
    setCompleteResult(null);
    setSelectedWorkflowId(preselectedWorkflowId ?? null);
    setTotalSteps(0);
    setCurrentStepIndex(0);
    setStepNames([]);
    setWorkflowsLoaded(false);
    autoSubmitRef.current = null;
    let cancelled = false;
    get<{ workflows: ApprovalWorkflowRef[]; total: number }>('/api/workflows?workflow_type=approval')
      .then((res) => {
        if (cancelled || !res.data) return;
        const wfs = Array.isArray(res.data?.workflows) ? res.data.workflows : [];
        setWorkflows(wfs);
        setWorkflowsLoaded(true);
        // No-workflow fallback: if no workflows exist, close dialog and notify caller
        if (wfs.length === 0 && onNoWorkflow) {
          onOpenChange(false);
          onNoWorkflow();
        }
      })
      .catch(() => {
        setWorkflowsLoaded(true);
        // Also trigger fallback on fetch error
        if (onNoWorkflow) {
          onOpenChange(false);
          onNoWorkflow();
        }
      });
    return () => { cancelled = true; };
  }, [isOpen, preselectedWorkflowId, get]);

  const startSession = useCallback(
    async (workflowId: string) => {
      setLoading(true);
      try {
        // Capture step metadata from the selected workflow for progress tracking
        const wf = workflows.find((w) => w.id === workflowId);
        if (wf?.steps) {
          setTotalSteps(wf.steps.length);
          setStepNames(wf.steps.map((s) => s.name));
          setCurrentStepIndex(0);
        }
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
    [entityType, entityId, completionAction, post, toast, workflows],
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

  const submitStep = useCallback(async () => {
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
        toast({ title: 'Completed', description: 'Approval workflow completed successfully.' });
        onComplete?.(data.agreement_id ?? null, data.pdf_storage_path ?? null);
        // Auto-close after a brief delay so the user sees the success state
        setTimeout(() => onOpenChange(false), 800);
      } else {
        setCurrentStep(data.current_step ?? null);
        setCurrentStepIndex((idx) => idx + 1);
        setStepResults((data.step_results as Array<{ step_id: string; payload: Record<string, unknown> }>) ?? []);
        setPayload({});
      }
    } catch (e) {
      toast({ title: 'Error', description: 'Failed to submit step', variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  }, [sessionId, currentStep, payload, post, toast, onComplete, onOpenChange]);

  /** Auto-advance non-visual steps (persist_agreement, generate_pdf, deliver). */
  useEffect(() => {
    if (
      sessionId &&
      currentStep &&
      !loading &&
      NON_VISUAL_STEP_TYPES.has(currentStep.step_type) &&
      autoSubmitRef.current !== currentStep.step_id
    ) {
      autoSubmitRef.current = currentStep.step_id;
      submitStep();
    }
  }, [sessionId, currentStep, loading, submitStep]);

  const abortSession = async () => {
    if (!sessionId) {
      toast({ title: 'Cancelled', variant: 'default' });
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
    toast({ title: 'Cancelled', variant: 'default' });
    onOpenChange(false);
  };

  const handleDialogOpenChange = (open: boolean) => {
    if (!open && !completeResult) {
      // User closed via X or escape — treat as cancel
      toast({ title: 'Cancelled', variant: 'default' });
    }
    onOpenChange(open);
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

  /** Whether the current step is non-visual (auto-advancing). */
  const isNonVisualStep = currentStep && NON_VISUAL_STEP_TYPES.has(currentStep.step_type);

  /** Determine if the current step is the last visual step. */
  const isLastVisualStep = (() => {
    if (!currentStep || totalSteps === 0) return false;
    // Check if all remaining steps after the current one are non-visual
    const remainingSteps = stepNames.slice(currentStepIndex + 1);
    if (remainingSteps.length === 0) return true;
    // Look at the workflow to check remaining step types
    const wf = workflows.find((w) => w.steps?.some((s) => s.step_id === currentStep.step_id));
    if (!wf?.steps) return currentStepIndex >= totalSteps - 1;
    const stepsAfterCurrent = wf.steps.slice(currentStepIndex + 1);
    return stepsAfterCurrent.every((s) => NON_VISUAL_STEP_TYPES.has(s.step_type));
  })();

  /** Human-readable action name derived from completionAction. */
  const actionLabel = completionAction
    ? completionAction.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
    : 'proceed';

  return (
    <Dialog open={isOpen} onOpenChange={handleDialogOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Approval wizard</DialogTitle>
          <DialogDescription>
            {!sessionId ? 'Choose an approval workflow to run for this entity.' : currentStep ? `Step: ${currentStep.name}` : completeResult ? 'Completed.' : 'Loading\u2026'}
          </DialogDescription>
        </DialogHeader>

        {/* Progress indicator — shown when a session is active and we know the step count */}
        {sessionId && totalSteps > 0 && (
          <div className="flex items-center gap-2 px-1">
            <div className="flex items-center gap-1.5">
              {Array.from({ length: totalSteps }, (_, i) => (
                <div
                  key={i}
                  className={`w-2.5 h-2.5 rounded-full transition-colors ${
                    i < currentStepIndex
                      ? 'bg-primary'
                      : i === currentStepIndex
                        ? 'bg-primary ring-2 ring-primary ring-offset-2 ring-offset-background'
                        : 'bg-muted'
                  }`}
                />
              ))}
            </div>
            <span className="text-xs text-muted-foreground ml-1">
              Step {currentStepIndex + 1}: {stepNames[currentStepIndex] ?? currentStep?.name ?? ''}
            </span>
          </div>
        )}

        {/* Contextual header — shown when session is active */}
        {sessionId && !completeResult && entityName && (
          <p className="text-sm text-muted-foreground px-1">
            Complete the following before {actionLabel.toLowerCase()} to <strong>{entityName}</strong>
          </p>
        )}

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
            {workflows.length === 0 && !loading && workflowsLoaded && (
              <p className="text-sm text-muted-foreground">No approval workflows available. Add them in Settings &rarr; Workflows (Approval workflows).</p>
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
              <Button variant="ghost" onClick={() => { toast({ title: 'Cancelled', variant: 'default' }); onOpenChange(false); }}>Cancel</Button>
            </DialogFooter>
          </div>
        )}

        {/* Non-visual step: spinner with auto-advancing message */}
        {sessionId && currentStep && isNonVisualStep && (
          <div className="flex flex-col items-center justify-center gap-3 py-8">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            <p className="text-sm text-muted-foreground">Finalizing...</p>
          </div>
        )}

        {/* Visual step: show form fields */}
        {sessionId && currentStep && !isNonVisualStep && (
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
                Cancel
              </Button>
              <Button onClick={submitStep} disabled={loading || !isStepValid}>
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                {isLastVisualStep ? 'Complete' : 'Next'}
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
