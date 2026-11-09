import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import {
  Play,
  // Code - unused
  CheckCircle,
  XCircle,
  Zap,
  Clock,
  Pause,
  AlertCircle,
  User,
} from 'lucide-react';

import type { TFunction } from 'i18next';
import type {
  WorkflowExecution,
  ProcessWorkflow,
  WorkflowStep,
  WorkflowStepExecutionResult,
  ExecutionStatus,
  EntityType,
} from '@/types/process-workflow';
import { 
  getTriggerTypeLabel, 
  getEntityTypeLabel,
  getStepTypeLabel,
  getStepIcon,
  getStepColor,
} from '@/lib/workflow-labels';
import { useApi } from '@/hooks/use-api';
import { useDefaultWorkflowText } from '@/lib/workflow-default-texts';

interface WorkflowExecutionDialogProps {
  execution: WorkflowExecution | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

// Execution step status
type StepExecutionState = 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped' | 'current';

// Step execution results reference the step's row id; a step that ran twice
// (an approval: paused, then resumed) counts by its last run.
function isRunOf(
  se: WorkflowStepExecutionResult,
  step: Pick<WorkflowStep, 'id' | 'step_id'>
): boolean {
  if (se.step_id) return se.step_id === step.id || se.step_id === step.step_id;
  // The step was removed (no row id): a step added back with its step_id
  return !!se.step_key && se.step_key === step.step_id;
}

export function getLastStepRun(
  step: Pick<WorkflowStep, 'id' | 'step_id'>,
  execution: WorkflowExecution
): WorkflowStepExecutionResult | undefined {
  const runs = (execution.step_executions || []).filter(se => isRunOf(se, step));
  return runs[runs.length - 1];
}

// The last run of each step that ran in the execution and is no longer in the
// workflow, in the order they ran.
export function getRemovedStepRuns(
  steps: Pick<WorkflowStep, 'id' | 'step_id'>[],
  execution: WorkflowExecution
): WorkflowStepExecutionResult[] {
  const last = new Map<string, WorkflowStepExecutionResult>();
  for (const se of execution.step_executions || []) {
    if (steps.some(step => isRunOf(se, step))) continue;
    const key = se.step_key || se.step_id || se.id;
    last.delete(key);
    last.set(key, se);
  }
  return Array.from(last.values());
}

// Progress over the workflow's current steps: how many of them completed, and
// how many steps that ran were removed from the workflow later. The
// execution's success_count counts the runs of the execution, including steps
// removed since, so it can't be shown against the current number of steps.
export function getStepsProgress(
  steps: Pick<WorkflowStep, 'id' | 'step_id'>[],
  execution: WorkflowExecution
): { done: number; total: number; removed: number } {
  return {
    done: steps.filter(step => getStepExecutionState(step, execution) === 'succeeded').length,
    total: steps.length,
    removed: getRemovedStepRuns(steps, execution).length,
  };
}

// A failed step's error, translated when the backend sent a code
// (result_data.error_code / error_params), else as stored.
export function getStepErrorText(
  run: Pick<WorkflowStepExecutionResult, 'error_message' | 'result_data'>,
  t: TFunction
): string | undefined {
  const data = run.result_data || {};
  const code = typeof data.error_code === 'string' ? data.error_code : undefined;
  if (!code) return run.error_message || undefined;
  const params = (data.error_params && typeof data.error_params === 'object')
    ? data.error_params as Record<string, unknown>
    : {};
  return t(`workflows:execution.stepErrors.${code}`, {
    ...params,
    defaultValue: run.error_message || code,
  });
}

export function getStepExecutionState(
  step: Pick<WorkflowStep, 'id' | 'step_id'>,
  execution: WorkflowExecution
): StepExecutionState {
  const stepId = step.step_id;
  // Check if this is the current (paused) step
  if (execution.current_step_id === stepId && execution.status === 'paused') {
    return 'current';
  }
  
  // If workflow is running and we haven't reached this step yet
  if (execution.status === 'running' && execution.current_step_id === stepId) {
    return 'running';
  }
  
  const stepExecution = getLastStepRun(step, execution);
  if (stepExecution) {
    if (stepExecution.passed) return 'succeeded';
    if (stepExecution.status === 'failed') return 'failed';
    if (stepExecution.status === 'running') return 'running';
  }
  
  return 'pending';
}

// Custom node component for execution view (kept for future graph-based visualization)
// interface ExecutionStepNodeProps {
//   data: { step: WorkflowStep; state: StepExecutionState; };
// }
// function ExecutionStepNode({ data }: { data: ExecutionStepNodeProps['data'] }) { ... }

// Simple vertical flow layout
function SimpleWorkflowFlow({
  workflow,
  execution,
}: {
  workflow: ProcessWorkflow;
  execution: WorkflowExecution;
}) {
  const { t } = useTranslation(['workflows', 'common']);

  if (!workflow.steps?.length) {
    return (
      <div className="text-center text-muted-foreground py-8">
        {t('workflows:execution.noSteps')}
      </div>
    );
  }
  
  // Build execution path - which steps were actually executed (for future use)
  // const executedStepIds = new Set(execution.step_executions?.map(se => se.step_id) || []);
  
  return (
    <div className="space-y-4 p-4">
      {/* Trigger */}
      {workflow.trigger && (
        <div className="flex items-center gap-3 p-3 rounded-lg bg-purple-50 dark:bg-purple-950/30 border-2 border-purple-500">
          <Zap className="h-5 w-5 text-purple-500" />
          <div>
            <div className="font-medium text-sm">{t('workflows:execution.trigger')}</div>
            <div className="text-xs text-muted-foreground">
              {getTriggerTypeLabel(workflow.trigger.type, t)} → {workflow.trigger.entity_types.map(et => getEntityTypeLabel(et, t)).join(', ')}
            </div>
          </div>
          <CheckCircle className="h-4 w-4 text-emerald-500 ml-auto" />
        </div>
      )}
      
      {/* Arrow */}
      <div className="flex justify-center">
        <div className="h-6 w-0.5 bg-border" />
      </div>
      
      {/* Steps */}
      {workflow.steps.map((step, index) => {
        const state = getStepExecutionState(step, execution);
        const run = state === 'failed' ? getLastStepRun(step, execution) : undefined;
        const errorText = run ? getStepErrorText(run, t) : undefined;
        const Icon = getStepIcon(step.step_type);
        const color = getStepColor(step.step_type);
        
        const stateStyles: Record<StepExecutionState, string> = {
          pending: 'opacity-50 border-muted',
          running: 'ring-2 ring-blue-500 animate-pulse',
          succeeded: 'border-emerald-500 bg-emerald-50 dark:bg-emerald-950/20',
          failed: 'border-red-500 bg-red-50 dark:bg-red-950/20',
          skipped: 'opacity-30 border-muted',
          current: 'ring-4 ring-amber-500 border-amber-500 bg-amber-50 dark:bg-amber-950/30',
        };
        
        const stateLabels: Record<StepExecutionState, { label: string; icon: React.ReactNode }> = {
          pending: { label: t('workflows:execution.states.pending'), icon: <Clock className="h-4 w-4 text-muted-foreground" /> },
          running: { label: t('workflows:execution.states.running'), icon: <Play className="h-4 w-4 text-blue-500" /> },
          succeeded: { label: t('workflows:execution.states.completed'), icon: <CheckCircle className="h-4 w-4 text-emerald-500" /> },
          failed: { label: t('workflows:execution.states.failed'), icon: <XCircle className="h-4 w-4 text-red-500" /> },
          skipped: { label: t('workflows:execution.states.skipped'), icon: <Clock className="h-4 w-4 text-muted-foreground" /> },
          current: { label: t('workflows:execution.states.waiting'), icon: <Pause className="h-4 w-4 text-amber-500" /> },
        };
        
        return (
          <div key={step.step_id}>
            <div className={`flex items-center gap-3 p-3 rounded-lg border-2 ${stateStyles[state]}`}>
              <div className={`p-2 rounded-md bg-${color}-100 dark:bg-${color}-900/30`}>
                <Icon className={`h-5 w-5 text-${color}-500`} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-medium text-sm truncate">{step.name}</div>
                <div className="text-xs text-muted-foreground">
                  {getStepTypeLabel(step.step_type, t)}
                </div>
                {errorText && (
                  <div className="text-xs text-destructive mt-1 break-words">{errorText}</div>
                )}
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">{stateLabels[state].label}</span>
                {stateLabels[state].icon}
              </div>
            </div>
            
            {/* Arrow to next step */}
            {index < workflow.steps.length - 1 && (
              <div className="flex justify-center">
                <div className="h-6 w-0.5 bg-border" />
              </div>
            )}
          </div>
        );
      })}

      <RemovedStepRuns steps={workflow.steps} execution={execution} />
    </div>
  );
}

// Steps that ran in the execution and were removed from the workflow later
function RemovedStepRuns({
  steps,
  execution,
}: {
  steps: WorkflowStep[];
  execution: WorkflowExecution;
}) {
  const { t } = useTranslation(['workflows', 'common']);
  const runs = getRemovedStepRuns(steps, execution);
  if (!runs.length) return null;

  return (
    <div className="pt-2" data-testid="removed-step-runs">
      <div className="font-medium text-sm">{t('workflows:execution.removedSteps')}</div>
      <div className="text-xs text-muted-foreground mb-2">
        {t('workflows:execution.removedStepsHint')}
      </div>
      <div className="space-y-2">
        {runs.map(run => {
          const failed = run.status === 'failed' || run.passed === false;
          const errorText = failed ? getStepErrorText(run, t) : undefined;
          return (
            <div
              key={run.id}
              className={`flex items-center gap-3 p-3 rounded-lg border-2 border-dashed ${
                failed ? 'border-red-500/60' : 'border-emerald-500/60'
              }`}
            >
              <div className="flex-1 min-w-0">
                <div className="font-medium text-sm truncate">
                  {run.step_name || run.step_key || run.step_id}
                </div>
                {errorText && (
                  <div className="text-xs text-destructive mt-1 break-words">{errorText}</div>
                )}
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">
                  {failed
                    ? t('workflows:execution.states.failed')
                    : t('workflows:execution.states.completed')}
                </span>
                {failed
                  ? <XCircle className="h-4 w-4 text-red-500" />
                  : <CheckCircle className="h-4 w-4 text-emerald-500" />}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function WorkflowExecutionDialog({
  execution,
  open,
  onOpenChange,
}: WorkflowExecutionDialogProps) {
  const { t } = useTranslation(['workflows', 'common']);
  const defaultWorkflowText = useDefaultWorkflowText();
  const { get } = useApi();
  const [workflow, setWorkflow] = useState<ProcessWorkflow | null>(null);
  const [stepResults, setStepResults] = useState<WorkflowExecution['step_executions'] | null>(null);
  const [loading, setLoading] = useState(false);
  
  // The executions list doesn't carry step results; load them for this execution
  useEffect(() => {
    setStepResults(null);
    if (open && execution?.id) {
      get<WorkflowExecution>(`/api/workflows/executions/${execution.id}`)
        .then(response => {
          if (response.data?.step_executions) {
            setStepResults(response.data.step_executions);
          }
        })
        .catch(err => {
          console.error('Failed to fetch execution steps:', err);
        });
    }
  }, [open, execution?.id, get]);
  
  // Fetch workflow definition when dialog opens
  useEffect(() => {
    if (open && execution?.workflow_id) {
      setLoading(true);
      get<ProcessWorkflow>(`/api/workflows/${execution.workflow_id}`)
        .then(response => {
          if (response.data) {
            setWorkflow(response.data);
          }
        })
        .catch(err => {
          console.error('Failed to fetch workflow:', err);
        })
        .finally(() => {
          setLoading(false);
        });
    }
  }, [open, execution?.workflow_id, get]);
  
  if (!execution) return null;
  
  const statusBadges: Record<ExecutionStatus, { variant: 'default' | 'secondary' | 'destructive' | 'outline'; className: string }> = {
    pending: { variant: 'secondary', className: '' },
    running: { variant: 'default', className: 'bg-blue-500' },
    paused: { variant: 'outline', className: 'border-amber-500 text-amber-600' },
    succeeded: { variant: 'default', className: 'bg-emerald-500' },
    failed: { variant: 'destructive', className: '' },
    cancelled: { variant: 'outline', className: 'border-gray-500 text-gray-600' },
  };
  
  const statusConfig = statusBadges[execution.status] || statusBadges.pending;

  const shownExecution = stepResults ? { ...execution, step_executions: stepResults } : execution;
  const progress = workflow?.steps ? getStepsProgress(workflow.steps, shownExecution) : null;
  // A finished execution has no current step: the backend still reports the last one it stopped at
  const isActive = execution.status === 'paused' || execution.status === 'running';
  const progressText = !progress
    ? t('workflows:execution.stepsProgress', { done: execution.success_count, total: '?' })
    : progress.removed
      ? t('workflows:execution.stepsProgressWithRemoved', { ...progress, count: progress.removed })
      : t('workflows:execution.stepsProgress', progress);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[85vh]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Zap className="h-5 w-5" />
            {defaultWorkflowText(execution.workflow_name) || t('workflows:execution.titleFallback')}
          </DialogTitle>
          <DialogDescription>
            {t('workflows:execution.executionId', { id: execution.id.slice(0, 8) })}
          </DialogDescription>
        </DialogHeader>
        
        <div className="space-y-4">
          {/* Execution Summary */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Card className="p-3">
              <div className="text-xs text-muted-foreground mb-1">{t('common:labels.status')}</div>
              <Badge variant={statusConfig.variant} className={statusConfig.className}>
                {t(`workflows:execution.executionStates.${execution.status}`, { defaultValue: execution.status })}
              </Badge>
            </Card>

            <Card className="p-3">
              <div className="text-xs text-muted-foreground mb-1">{t('workflows:execution.summary.entity')}</div>
              <div className="font-medium text-sm truncate">
                {execution.entity_name || execution.entity_id || '-'}
              </div>
              {execution.entity_type && (
                <div className="text-xs text-muted-foreground">
                  {getEntityTypeLabel(execution.entity_type as EntityType, t)}
                </div>
              )}
            </Card>
            
            <Card className="p-3">
              <div className="text-xs text-muted-foreground mb-1">{t('workflows:execution.summary.started')}</div>
              <div className="text-sm">
                {execution.started_at 
                  ? new Date(execution.started_at).toLocaleString()
                  : '-'}
              </div>
            </Card>
            
            <Card className="p-3">
              <div className="text-xs text-muted-foreground mb-1">
                {execution.status === 'paused' ? t('workflows:execution.summary.waitingAt') : t('workflows:execution.summary.progress')}
              </div>
              <div className="font-medium text-sm truncate">
                {isActive ? (execution.current_step_name || progressText) : progressText}
              </div>
            </Card>
          </div>
          
          {/* Triggered By */}
          {execution.triggered_by && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <User className="h-4 w-4" />
              <span>{t('workflows:execution.triggeredBy', { user: execution.triggered_by })}</span>
            </div>
          )}
          
          <Separator />
          
          {/* Workflow Visualization */}
          <div className="border rounded-lg bg-muted/30">
            <div className="p-3 border-b bg-muted/50">
              <h4 className="font-medium text-sm">{t('workflows:execution.workflowSteps')}</h4>
            </div>
            <ScrollArea className="h-[350px]">
              {loading ? (
                <div className="flex items-center justify-center h-full">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
                </div>
              ) : workflow ? (
                <SimpleWorkflowFlow
                  workflow={workflow}
                  execution={shownExecution}
                />
              ) : (
                <div className="text-center text-muted-foreground py-8">
                  {t('workflows:execution.loadDefinitionFailed')}
                </div>
              )}
            </ScrollArea>
          </div>
          
          {/* Error Message */}
          {execution.error_message && (
            <div className="flex items-start gap-2 p-3 rounded-lg bg-destructive/10 border border-destructive/30">
              <AlertCircle className="h-4 w-4 text-destructive mt-0.5" />
              <div className="text-sm text-destructive">
                <ExecutionErrorText execution={stepResults ? { ...execution, step_executions: stepResults } : execution} t={t} />
              </div>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

// The execution's error. When it is the failed step's error and that step sent a
// code, the step's translated text; otherwise a shipped fail step's message in
// the user's language.
export function getExecutionErrorText(
  execution: Pick<WorkflowExecution, 'error_message' | 'step_executions'>,
  t: TFunction
): string | undefined {
  const message = execution.error_message || undefined;
  if (!message) return undefined;
  const codedRun = [...(execution.step_executions || [])].reverse().find(
    run => run.error_message === message && typeof run.result_data?.error_code === 'string'
  );
  return codedRun ? getStepErrorText(codedRun, t) : undefined;
}

function ExecutionErrorText({ execution, t }: { execution: WorkflowExecution; t: TFunction }) {
  const defaultWorkflowText = useDefaultWorkflowText();
  const message = execution.error_message || '';
  return <>{getExecutionErrorText(execution, t) ?? defaultWorkflowText(message)}</>;
}
