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

import type {
  WorkflowExecution,
  ProcessWorkflow,
  // WorkflowStep, // Available for future graph-based visualization
  ExecutionStatus,
} from '@/types/process-workflow';
import { 
  getTriggerTypeLabel, 
  getEntityTypeLabel,
  getStepIcon,
  getStepColor,
} from '@/lib/workflow-labels';
import { useApi } from '@/hooks/use-api';

interface WorkflowExecutionDialogProps {
  execution: WorkflowExecution | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

// Execution step status
type StepExecutionState = 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped' | 'current';

function getStepExecutionState(
  stepId: string,
  execution: WorkflowExecution
): StepExecutionState {
  // Check if this is the current (paused) step
  if (execution.current_step_id === stepId && execution.status === 'paused') {
    return 'current';
  }
  
  // If workflow is running and we haven't reached this step yet
  if (execution.status === 'running' && execution.current_step_id === stepId) {
    return 'running';
  }
  
  // Check step execution results
  const stepExecution = execution.step_executions?.find(se => se.step_id === stepId);
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
  const { t } = useTranslation(['common']);
  
  if (!workflow.steps?.length) {
    return (
      <div className="text-center text-muted-foreground py-8">
        No steps defined
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
            <div className="font-medium text-sm">Trigger</div>
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
        const state = getStepExecutionState(step.step_id, execution);
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
          pending: { label: 'Pending', icon: <Clock className="h-4 w-4 text-muted-foreground" /> },
          running: { label: 'Running', icon: <Play className="h-4 w-4 text-blue-500" /> },
          succeeded: { label: 'Completed', icon: <CheckCircle className="h-4 w-4 text-emerald-500" /> },
          failed: { label: 'Failed', icon: <XCircle className="h-4 w-4 text-red-500" /> },
          skipped: { label: 'Skipped', icon: <Clock className="h-4 w-4 text-muted-foreground" /> },
          current: { label: 'Waiting', icon: <Pause className="h-4 w-4 text-amber-500" /> },
        };
        
        return (
          <div key={step.step_id}>
            <div className={`flex items-center gap-3 p-3 rounded-lg border-2 ${stateStyles[state]}`}>
              <div className={`p-2 rounded-md bg-${color}-100 dark:bg-${color}-900/30`}>
                <Icon className={`h-5 w-5 text-${color}-500`} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-medium text-sm truncate">{step.name}</div>
                <div className="text-xs text-muted-foreground capitalize">
                  {step.step_type.replace('_', ' ')}
                </div>
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
    </div>
  );
}

export function WorkflowExecutionDialog({
  execution,
  open,
  onOpenChange,
}: WorkflowExecutionDialogProps) {
  const { t: _t } = useTranslation(['common']);
  const { get } = useApi();
  const [workflow, setWorkflow] = useState<ProcessWorkflow | null>(null);
  const [loading, setLoading] = useState(false);
  
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
  
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[85vh]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Zap className="h-5 w-5" />
            {execution.workflow_name || 'Workflow Execution'}
          </DialogTitle>
          <DialogDescription>
            Execution ID: {execution.id.slice(0, 8)}...
          </DialogDescription>
        </DialogHeader>
        
        <div className="space-y-4">
          {/* Execution Summary */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Card className="p-3">
              <div className="text-xs text-muted-foreground mb-1">Status</div>
              <Badge variant={statusConfig.variant} className={statusConfig.className}>
                {execution.status}
              </Badge>
            </Card>
            
            <Card className="p-3">
              <div className="text-xs text-muted-foreground mb-1">Entity</div>
              <div className="font-medium text-sm truncate">
                {execution.entity_name || execution.entity_id || '-'}
              </div>
              {execution.entity_type && (
                <div className="text-xs text-muted-foreground capitalize">
                  {execution.entity_type}
                </div>
              )}
            </Card>
            
            <Card className="p-3">
              <div className="text-xs text-muted-foreground mb-1">Started</div>
              <div className="text-sm">
                {execution.started_at 
                  ? new Date(execution.started_at).toLocaleString()
                  : '-'}
              </div>
            </Card>
            
            <Card className="p-3">
              <div className="text-xs text-muted-foreground mb-1">
                {execution.status === 'paused' ? 'Waiting At' : 'Progress'}
              </div>
              <div className="font-medium text-sm truncate">
                {execution.current_step_name || `${execution.success_count}/${workflow?.steps?.length || '?'} steps`}
              </div>
            </Card>
          </div>
          
          {/* Triggered By */}
          {execution.triggered_by && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <User className="h-4 w-4" />
              <span>Triggered by: {execution.triggered_by}</span>
            </div>
          )}
          
          <Separator />
          
          {/* Workflow Visualization */}
          <div className="border rounded-lg bg-muted/30">
            <div className="p-3 border-b bg-muted/50">
              <h4 className="font-medium text-sm">Workflow Steps</h4>
            </div>
            <ScrollArea className="h-[350px]">
              {loading ? (
                <div className="flex items-center justify-center h-full">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
                </div>
              ) : workflow ? (
                <SimpleWorkflowFlow workflow={workflow} execution={execution} />
              ) : (
                <div className="text-center text-muted-foreground py-8">
                  Failed to load workflow definition
                </div>
              )}
            </ScrollArea>
          </div>
          
          {/* Error Message */}
          {execution.error_message && (
            <div className="flex items-start gap-2 p-3 rounded-lg bg-destructive/10 border border-destructive/30">
              <AlertCircle className="h-4 w-4 text-destructive mt-0.5" />
              <div className="text-sm text-destructive">{execution.error_message}</div>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

