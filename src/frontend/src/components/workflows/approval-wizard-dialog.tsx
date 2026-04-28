/**
 * Approval wizard dialog: run an approval workflow (multi-step) for an entity.
 * Creates session, shows steps (user_action: fields, acceptances), submits until complete or abort.
 */

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
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
import { Checkbox } from '@/components/ui/checkbox';
import { Loader2, Check, XCircle, ChevronRight, FileText } from 'lucide-react';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';

/** Lightweight markdown to HTML — handles headers, bold, lists, paragraphs. */
function simpleMarkdown(text: string): string {
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')  // escape HTML
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>.*<\/li>\n?)+/g, (match) => `<ul>${match}</ul>`)
    .replace(/^\d+\. (.+)$/gm, '<li>$1</li>')
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br/>')
    .replace(/^/, '<p>').replace(/$/, '</p>');
}

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
  const [completeResult, setCompleteResult] = useState<{ agreement_id: string | null; pdf_storage_path: string | null; pdf_url: string | null } | null>(null);
  /** Total steps and current index (0-based) for the progress indicator. */
  const [totalSteps, setTotalSteps] = useState(0);
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  /** Step names for displaying in the progress indicator. */
  const [stepNames, setStepNames] = useState<string[]>([]);
  /** Track whether workflows have been loaded (to distinguish empty from not-yet-loaded). */
  const [workflowsLoaded, setWorkflowsLoaded] = useState(false);
  /** Ref to prevent duplicate auto-submit for non-visual steps. */
  const autoSubmitRef = useRef<string | null>(null);
  /** Legal document: tracks whether user scrolled to bottom. */
  const [scrolledToEnd, setScrolledToEnd] = useState(false);
  /** Legal document: tracks acknowledgement checkbox state. */
  const [acknowledged, setAcknowledged] = useState(false);
  /** Acknowledgement checklist: tracks which items are checked. */
  const [checklistState, setChecklistState] = useState<Record<string, boolean>>({});
  /** Co-signers: list of entered principals. */
  const [coSigners, setCoSigners] = useState<string[]>([]);
  /** Co-signers: current input value. */
  const [coSignerInput, setCoSignerInput] = useState('');

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
    setScrolledToEnd(false);
    setAcknowledged(false);
    setChecklistState({});
    setCoSigners([]);
    setCoSignerInput('');
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
        // Capture step metadata — only count visual steps for the progress indicator
        const wf = workflows.find((w) => w.id === workflowId);
        if (wf?.steps) {
          const visualSteps = wf.steps.filter((s) => !NON_VISUAL_STEP_TYPES.has(s.step_type) && s.step_type !== 'pass' && s.step_type !== 'fail');
          setTotalSteps(visualSteps.length);
          setStepNames(visualSteps.map((s) => s.name));
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

  const requiredFields = (currentStep?.config?.required_fields as Array<{ id: string; label: string; type: string; required?: boolean }>) ?? [];

  // --- Per-step-type validation ---
  const stepValidation = useMemo(() => {
    if (!currentStep) return { valid: false, payload: {} as Record<string, unknown> };
    const cfg = (currentStep.config ?? {}) as Record<string, unknown>;
    const stepType = currentStep.step_type;

    if (stepType === 'user_action') {
      const rFields = (cfg.required_fields as Array<{ id: string; label: string; type: string; required?: boolean }>) ?? [];
      const primaryFieldId = (cfg.primary_field_id as string) || rFields.find((f) => f.required)?.id || rFields[0]?.id || 'reason';
      const primaryValue = payload[primaryFieldId]?.trim() ?? '';
      const requiredFieldsValid = rFields.filter((f) => f.required).every((f) => (payload[f.id]?.trim() ?? '').length > 0);
      const requiresInputValid = !cfg.requires_input || primaryValue.length > 0;
      const minLen = cfg.minimum_input_length as number | undefined;
      const minLengthValid = minLen == null || primaryValue.length >= minLen;
      return { valid: requiredFieldsValid && requiresInputValid && minLengthValid, payload: payload as Record<string, unknown> };
    }

    if (stepType === 'legal_document') {
      const needScroll = (cfg.require_scroll_to_end as boolean) ?? false;
      const needAck = (cfg.require_acknowledgement_checkbox as boolean) ?? false;
      const scrollOk = !needScroll || scrolledToEnd;
      const ackOk = !needAck || acknowledged;
      return {
        valid: scrollOk && ackOk,
        payload: { scrolled_to_end: scrolledToEnd, acknowledged } as Record<string, unknown>,
      };
    }

    if (stepType === 'acknowledgement_checklist') {
      const items = (cfg.items as Array<{ id: string; label: string; required?: boolean }>) ?? [];
      const allRequiredChecked = items.filter((i) => i.required !== false).every((i) => checklistState[i.id]);
      return {
        valid: allRequiredChecked,
        payload: { items: checklistState } as Record<string, unknown>,
      };
    }

    if (stepType === 'co_signers') {
      const minCount = (cfg.min_count as number) ?? 0;
      const maxCount = (cfg.max_count as number) ?? 5;
      return {
        valid: coSigners.length >= minCount && coSigners.length <= maxCount,
        payload: { co_signers: coSigners } as Record<string, unknown>,
      };
    }

    // Default: valid (non-visual steps auto-advance anyway)
    return { valid: true, payload: {} as Record<string, unknown> };
  }, [currentStep, payload, scrolledToEnd, acknowledged, checklistState, coSigners]);

  const isStepValid = stepValidation.valid;

  const submitStep = useCallback(async () => {
    if (!sessionId || !currentStep) return;
    setLoading(true);
    try {
      const submissionPayload = currentStep.step_type === 'user_action' ? payload : stepValidation.payload;
      const res = await post<{ complete?: boolean; agreement_id?: string; pdf_storage_path?: string; pdf_url?: string; current_step?: WizardStep; step_results?: unknown[] }>(
        `/api/approvals/sessions/${sessionId}/steps`,
        { step_id: currentStep.step_id, payload: submissionPayload },
      );
      if (res.error || !res.data) {
        toast({ title: 'Error', description: (res as { error?: string }).error || 'Failed to submit step', variant: 'destructive' });
        return;
      }
      const data = res.data as { complete?: boolean; agreement_id?: string; pdf_storage_path?: string; pdf_url?: string; current_step?: WizardStep; step_results?: unknown[] };
      if (data.complete) {
        setCompleteResult({ agreement_id: data.agreement_id ?? null, pdf_storage_path: data.pdf_storage_path ?? null, pdf_url: data.pdf_url ?? null });
        setCurrentStep(null);
        toast({ title: 'Completed', description: 'Approval workflow completed successfully.' });
        // Defer onComplete — let user see the completion screen and download PDF first.
        // onComplete fires when they click Close (see handleCloseAfterComplete below).
      } else {
        const nextStep = data.current_step ?? null;
        setCurrentStep(nextStep);
        // Only increment progress for visual steps (non-visual auto-advance without progress change)
        if (nextStep && !NON_VISUAL_STEP_TYPES.has(nextStep.step_type) && nextStep.step_type !== 'pass' && nextStep.step_type !== 'fail') {
          setCurrentStepIndex((idx) => idx + 1);
        }
        setStepResults((data.step_results as Array<{ step_id: string; payload: Record<string, unknown> }>) ?? []);
        setPayload({});
        setScrolledToEnd(false);
        setAcknowledged(false);
        setChecklistState({});
        setCoSigners([]);
        setCoSignerInput('');
      }
    } catch (e) {
      toast({ title: 'Error', description: 'Failed to submit step', variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  }, [sessionId, currentStep, payload, stepValidation, post, toast, onComplete, onOpenChange]);

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
    if (!open && completeResult) {
      // Closing after completion — fire onComplete
      onComplete?.(completeResult.agreement_id, completeResult.pdf_storage_path);
    } else if (!open && !completeResult) {
      // User closed via X or escape mid-flow — treat as cancel
      toast({ title: 'Cancelled', variant: 'default' });
    }
    onOpenChange(open);
  };

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
    return stepsAfterCurrent.every((s) => NON_VISUAL_STEP_TYPES.has(s.step_type) || s.step_type === 'pass' || s.step_type === 'fail');
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
            {completeResult.pdf_url && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => window.open(completeResult.pdf_url!, '_blank')}
              >
                <FileText className="h-4 w-4 mr-2" />
                Download Agreement
              </Button>
            )}
            <DialogFooter>
              <Button onClick={() => {
                onComplete?.(completeResult.agreement_id, completeResult.pdf_storage_path);
                onOpenChange(false);
              }}>Close</Button>
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

        {/* Visual step: show form fields (dispatched by step_type) */}
        {sessionId && currentStep && !isNonVisualStep && (
          <div className="space-y-4 py-4">
            {/* Step header (title + description) — shown for all visual step types */}
            {(currentStep.config?.title as string) && (
              <div className="space-y-1">
                <Label className="text-base">{(currentStep.config.title as string)}</Label>
                {(currentStep.config?.description as string) && (
                  <p className="text-sm text-muted-foreground">{(currentStep.config.description as string)}</p>
                )}
              </div>
            )}

            {/* === user_action renderer === */}
            {currentStep.step_type === 'user_action' && (
              <div className="space-y-2">
                {requiredFields.map((f) => (
                  <div key={f.id} className="space-y-1">
                    <Label htmlFor={f.id}>{f.label}{f.required ? ' *' : ''}</Label>
                    {f.type === 'text' ? (
                      <Textarea
                        id={f.id}
                        value={payload[f.id] ?? ''}
                        onChange={(e) => setPayload((p) => ({ ...p, [f.id]: e.target.value }))}
                        placeholder={f.label}
                        rows={2}
                        disabled={loading}
                      />
                    ) : (
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
            )}

            {/* === legal_document renderer === */}
            {currentStep.step_type === 'legal_document' && (
              <div className="space-y-3">
                <div
                  className="max-h-64 overflow-y-auto border rounded-md p-4 text-sm prose prose-sm dark:prose-invert"
                  ref={(el) => {
                    // If content fits without scrolling, mark as scrolled immediately
                    if (el && !scrolledToEnd && el.scrollHeight <= el.clientHeight + 10) {
                      setScrolledToEnd(true);
                    }
                  }}
                  onScroll={(e) => {
                    const el = e.currentTarget;
                    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 10) {
                      setScrolledToEnd(true);
                    }
                  }}
                >
                  <div dangerouslySetInnerHTML={{
                    __html: simpleMarkdown(currentStep.config?.body_markdown as string || '*No document content provided.*')
                  }} />
                </div>
                {(currentStep.config?.require_scroll_to_end as boolean) && !scrolledToEnd && (
                  <p className="text-xs text-amber-600 dark:text-amber-400">
                    Please scroll to the bottom of the document to continue.
                  </p>
                )}
                {(currentStep.config?.require_acknowledgement_checkbox as boolean) && (
                  <div className="flex items-start gap-2">
                    <Checkbox
                      id="legal-ack"
                      checked={acknowledged}
                      onCheckedChange={(checked) => setAcknowledged(checked === true)}
                      disabled={loading}
                    />
                    <Label htmlFor="legal-ack" className="text-sm cursor-pointer leading-tight">
                      {(currentStep.config?.acknowledgement_label as string) || 'I have read and understood the above'}
                    </Label>
                  </div>
                )}
              </div>
            )}

            {/* === acknowledgement_checklist renderer === */}
            {currentStep.step_type === 'acknowledgement_checklist' && (
              <div className="space-y-3">
                {((currentStep.config?.items as Array<{ id: string; label: string; required?: boolean }>) ?? []).map((item) => (
                  <div key={item.id} className="flex items-start gap-2">
                    <Checkbox
                      id={`checklist-${item.id}`}
                      checked={checklistState[item.id] ?? false}
                      onCheckedChange={(checked) =>
                        setChecklistState((prev) => ({ ...prev, [item.id]: checked === true }))
                      }
                      disabled={loading}
                    />
                    <Label htmlFor={`checklist-${item.id}`} className="text-sm cursor-pointer leading-tight">
                      {item.label}
                      {item.required !== false && <span className="text-destructive ml-1">*</span>}
                    </Label>
                  </div>
                ))}
              </div>
            )}

            {/* === co_signers renderer === */}
            {currentStep.step_type === 'co_signers' && (
              <div className="space-y-3">
                <div className="flex gap-2">
                  <Input
                    value={coSignerInput}
                    onChange={(e) => setCoSignerInput(e.target.value)}
                    placeholder={(currentStep.config?.label as string) || 'Enter email or group name'}
                    disabled={loading}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && coSignerInput.trim()) {
                        e.preventDefault();
                        const maxCount = (currentStep.config?.max_count as number) ?? 5;
                        if (coSigners.length < maxCount) {
                          setCoSigners((prev) => [...prev, coSignerInput.trim()]);
                          setCoSignerInput('');
                        }
                      }
                    }}
                  />
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={loading || !coSignerInput.trim() || coSigners.length >= ((currentStep.config?.max_count as number) ?? 5)}
                    onClick={() => {
                      if (coSignerInput.trim()) {
                        setCoSigners((prev) => [...prev, coSignerInput.trim()]);
                        setCoSignerInput('');
                      }
                    }}
                  >
                    Add
                  </Button>
                </div>
                {coSigners.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {coSigners.map((s, i) => (
                      <span key={i} className="inline-flex items-center gap-1 bg-muted text-sm px-2 py-1 rounded-md">
                        {s}
                        <button
                          className="text-muted-foreground hover:text-foreground"
                          onClick={() => setCoSigners((prev) => prev.filter((_, j) => j !== i))}
                        >
                          <XCircle className="h-3 w-3" />
                        </button>
                      </span>
                    ))}
                  </div>
                )}
                <p className="text-xs text-muted-foreground">
                  {((currentStep.config?.min_count as number) ?? 0) > 0
                    ? `Minimum ${(currentStep.config?.min_count as number)} co-signer(s) required.`
                    : 'Co-signers are optional for this step.'}
                  {' '}Maximum: {(currentStep.config?.max_count as number) ?? 5}.
                  {' '}Co-signers are recorded on the agreement for audit purposes.
                </p>
              </div>
            )}

            {/* Validation hints for user_action */}
            {currentStep.step_type === 'user_action' && !isStepValid && (
              <p className="text-xs text-amber-600 dark:text-amber-400">
                {(() => {
                  const cfg2 = (currentStep.config ?? {}) as { requires_input?: boolean; minimum_input_length?: number; primary_field_id?: string };
                  const rfs = (currentStep.config?.required_fields as Array<{ id: string; label: string; type: string; required?: boolean }>) ?? [];
                  const pfid = cfg2.primary_field_id || rfs.find((f) => f.required)?.id || rfs[0]?.id || 'reason';
                  const pv = payload[pfid]?.trim() ?? '';
                  if (cfg2.requires_input && !pv) return 'This step requires input.';
                  if (cfg2.minimum_input_length != null && cfg2.minimum_input_length > 0 && pv.length < cfg2.minimum_input_length)
                    return `Minimum length: ${cfg2.minimum_input_length} characters (${pv.length} entered).`;
                  return null;
                })()}
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
