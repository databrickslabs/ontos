import { useState, useEffect, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { useToast } from '@/hooks/use-toast';
import { 
  Plus, 
  MoreHorizontal, 
  GitBranch,
  Shield,
  Bell,
  Tag,
  Code,
  CheckCircle,
  Clock,
  Loader2,
  Pencil,
  Copy,
  Trash2,
  ClipboardCheck,
  Play,
  Pause,
  AlertCircle,
  ChevronDown,
  XCircle,
  RotateCcw,
  Power,
  PowerOff,
  HelpCircle,
  Eye,
} from 'lucide-react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { ColumnDef, Column } from "@tanstack/react-table";
import { useApi } from '@/hooks/use-api';
import SettingsPageWrapper from '@/components/settings/settings-page-wrapper';
import { DataTable } from '@/components/ui/data-table';
import { TableSkeleton } from '@/components/common/list-view-skeleton';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import type { 
  ProcessWorkflow, 
  WorkflowListResponse,
  WorkflowExecution,
  ExecutionStatus,
} from '@/types/process-workflow';
import { getTriggerDisplay } from '@/lib/workflow-labels';
import { WorkflowExecutionDialog } from '@/components/workflows/workflow-execution-dialog';
import ApprovalWizardDialog from '@/components/workflows/approval-wizard-dialog';
import { RelativeDate } from '@/components/common/relative-date';

interface WorkflowExecutionsResponse {
  executions: WorkflowExecution[];
  total: number;
}

// Helper to get step type icon
const getStepTypeIcon = (stepType: string) => {
  switch (stepType) {
    case 'validation': return <Shield className="h-4 w-4" />;
    case 'approval': return <CheckCircle className="h-4 w-4" />;
    case 'notification': return <Bell className="h-4 w-4" />;
    case 'assign_tag': return <Tag className="h-4 w-4" />;
    case 'conditional': return <GitBranch className="h-4 w-4" />;
    case 'script': return <Code className="h-4 w-4" />;
    case 'policy_check': return <ClipboardCheck className="h-4 w-4" />;
    default: return <GitBranch className="h-4 w-4" />;
  }
};

// Helper to get execution status badge
const getStatusBadge = (status: ExecutionStatus) => {
  const variants: Record<ExecutionStatus, { variant: 'default' | 'secondary' | 'destructive' | 'outline'; icon: React.ReactNode }> = {
    pending: { variant: 'secondary', icon: <Clock className="h-3 w-3 mr-1" /> },
    running: { variant: 'default', icon: <Play className="h-3 w-3 mr-1 animate-pulse" /> },
    paused: { variant: 'outline', icon: <Pause className="h-3 w-3 mr-1" /> },
    succeeded: { variant: 'default', icon: <CheckCircle className="h-3 w-3 mr-1" /> },
    failed: { variant: 'destructive', icon: <AlertCircle className="h-3 w-3 mr-1" /> },
    cancelled: { variant: 'secondary', icon: <AlertCircle className="h-3 w-3 mr-1" /> },
  };
  const config = variants[status] || variants.pending;
  return (
    <Badge variant={config.variant} className="flex items-center">
      {config.icon}
      {status}
    </Badge>
  );
};

export default function Workflows() {
  const { t } = useTranslation(['workflows', 'common']);
  const { toast } = useToast();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { get: apiGet, post: apiPost, delete: apiDeleteApi } = useApi();
  const { hasPermission } = usePermissions();
  
  // Check if user has admin access
  const canEdit = hasPermission('process-workflows', FeatureAccessLevel.ADMIN);
  
  // Workflow type filter: process (event-driven) | approval (wizard-driven)
  const [workflowTypeFilter, setWorkflowTypeFilter] = useState<'all' | 'process' | 'approval'>('all');
  // Stats card filter
  const [statsFilter, setStatsFilter] = useState<'all' | 'active' | 'inactive' | 'default' | 'running' | 'failed'>('all');
  // Workflow state
  const [workflows, setWorkflows] = useState<ProcessWorkflow[]>([]);
  const [isLoadingWorkflows, setIsLoadingWorkflows] = useState(true);
  const [duplicateDialogOpen, setDuplicateDialogOpen] = useState(false);
  const [duplicatingWorkflow, setDuplicatingWorkflow] = useState<ProcessWorkflow | null>(null);
  const [duplicateName, setDuplicateName] = useState('');
  const [isDuplicating, setIsDuplicating] = useState(false);
  
  // Executions state
  const [executions, setExecutions] = useState<WorkflowExecution[]>([]);
  const [isLoadingExecutions, setIsLoadingExecutions] = useState(true);

  // Approval sessions state
  const [approvalSessions, setApprovalSessions] = useState<any[]>([]);
  const [, setIsLoadingApprovalSessions] = useState(true);
  
  // Execution detail dialog state
  const [selectedExecution, setSelectedExecution] = useState<WorkflowExecution | null>(null);
  const [executionDialogOpen, setExecutionDialogOpen] = useState(false);
  
  // Execution action states
  const [deleteExecutionDialogOpen, setDeleteExecutionDialogOpen] = useState(false);
  const [executionToDelete, setExecutionToDelete] = useState<WorkflowExecution | null>(null);
  const [isActionInProgress, setIsActionInProgress] = useState(false);
  // Preview wizard (issue #405): launched from the row-action menu on any
  // approval workflow. Pure FE dry-run — no API session, no audit.
  const [previewingWorkflow, setPreviewingWorkflow] = useState<ProcessWorkflow | null>(null);

  const loadWorkflows = useCallback(async () => {
    setIsLoadingWorkflows(true);
    try {
      // Always fetch all workflows — type filtering is done client-side for instant tab switching
      const response = await apiGet<WorkflowListResponse>('/api/workflows');
      if (response.data) {
        setWorkflows(response.data.workflows || []);
      }
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: t('workflows:view.messages.loadFailed'),
        variant: 'destructive',
      });
    } finally {
      setIsLoadingWorkflows(false);
    }
  }, [apiGet, toast, t]);

  const loadExecutions = useCallback(async () => {
    setIsLoadingExecutions(true);
    try {
      const response = await apiGet<WorkflowExecutionsResponse>('/api/workflows/executions?limit=50');
      if (response.data) {
        setExecutions(response.data.executions || []);
      }
    } catch (error) {
      // Executions endpoint might not exist yet, silently fail
      console.warn('Failed to load workflow executions:', error);
    } finally {
      setIsLoadingExecutions(false);
    }
  }, [apiGet]);

  const loadApprovalSessions = useCallback(async () => {
    setIsLoadingApprovalSessions(true);
    try {
      const response = await apiGet<{ sessions: any[]; total: number }>('/api/approvals/sessions');
      if (response.data) {
        setApprovalSessions(response.data.sessions || []);
      }
    } catch {
      // Silently handle — endpoint may not exist on older deployments
    } finally {
      setIsLoadingApprovalSessions(false);
    }
  }, [apiGet]);

  useEffect(() => {
    loadWorkflows();
    loadExecutions();
    loadApprovalSessions();
  }, [loadWorkflows, loadExecutions, loadApprovalSessions]);

  // Workflow handlers
  const handleToggleWorkflowActive = async (workflow: ProcessWorkflow) => {
    if (!canEdit) {
      toast({
        title: t('workflows:view.permission.denied'),
        description: t('workflows:view.permission.modifyWorkflows'),
        variant: 'destructive',
      });
      return;
    }
    
    try {
      const response = await apiPost<ProcessWorkflow>(
        `/api/workflows/${workflow.id}/toggle-active?is_active=${!workflow.is_active}`,
        {}
      );
      if (response.data) {
        setWorkflows(prev => 
          prev.map(w => w.id === workflow.id ? response.data! : w)
        );
        toast({
          title: t('common:toast.success'),
          description: response.data.is_active
            ? t('workflows:view.messages.workflowEnabled')
            : t('workflows:view.messages.workflowDisabled'),
        });
      }
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: t('workflows:view.messages.updateStatusFailed'),
        variant: 'destructive',
      });
    }
  };

  const handleDuplicateWorkflow = async () => {
    if (!duplicatingWorkflow || !duplicateName.trim()) return;
    
    setIsDuplicating(true);
    try {
      const response = await apiPost<ProcessWorkflow>(
        `/api/workflows/${duplicatingWorkflow.id}/duplicate?new_name=${encodeURIComponent(duplicateName)}`,
        {}
      );
      if (response.data) {
        setWorkflows(prev => [...prev, response.data!]);
        toast({
          title: t('common:toast.success'),
          description: t('workflows:view.messages.duplicateSuccess'),
        });
        setDuplicateDialogOpen(false);
        setDuplicatingWorkflow(null);
        setDuplicateName('');
      }
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: t('workflows:view.messages.duplicateFailed'),
        variant: 'destructive',
      });
    } finally {
      setIsDuplicating(false);
    }
  };

  const handleDeleteWorkflow = async (workflow: ProcessWorkflow) => {
    if (!canEdit) {
      toast({
        title: t('workflows:view.permission.denied'),
        description: t('workflows:view.permission.deleteWorkflows'),
        variant: 'destructive',
      });
      return;
    }
    
    if (workflow.is_default) {
      toast({
        title: t('workflows:view.messages.cannotDelete'),
        description: t('workflows:view.messages.cannotDeleteDefault'),
        variant: 'destructive',
      });
      return;
    }
    
    try {
      await apiDeleteApi(`/api/workflows/${workflow.id}`);
      setWorkflows(prev => prev.filter(w => w.id !== workflow.id));
      toast({
        title: t('common:toast.success'),
        description: t('workflows:view.messages.deleteSuccess'),
      });
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: t('workflows:view.messages.deleteFailed'),
        variant: 'destructive',
      });
    }
  };

  const handleEditWorkflow = (workflow: ProcessWorkflow) => {
    navigate(`${pathname}/${workflow.id}`);
  };

  const handleLoadDefaultWorkflows = async (updateExisting: boolean = false) => {
    if (!canEdit) {
      toast({
        title: t('workflows:view.permission.denied'),
        description: t('workflows:view.permission.loadDefaults'),
        variant: 'destructive',
      });
      return;
    }
    
    try {
      const response = await apiPost<{ message: string; created: number; updated: number; skipped: number }>(
        `/api/workflows/load-defaults?update_existing=${updateExisting}`,
        {}
      );
      if (response.data) {
        toast({
          title: t('common:toast.success'),
          description: response.data.message,
        });
        loadWorkflows();
      }
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: t('workflows:view.messages.loadDefaultsFailed'),
        variant: 'destructive',
      });
    }
  };

  // Execution administration handlers
  const handleCancelExecution = async (execution: WorkflowExecution) => {
    if (!canEdit) {
      toast({
        title: t('workflows:view.permission.denied'),
        description: t('workflows:view.permission.cancelExecutions'),
        variant: 'destructive',
      });
      return;
    }
    
    setIsActionInProgress(true);
    try {
      const response = await apiPost<{ message: string }>(`/api/workflows/executions/${execution.id}/cancel`, {});
      if (response.data) {
        toast({
          title: t('common:toast.success'),
          description: t('workflows:view.messages.cancelSuccess'),
        });
        loadExecutions();
      }
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: t('workflows:view.messages.cancelFailed'),
        variant: 'destructive',
      });
    } finally {
      setIsActionInProgress(false);
    }
  };

  const handleRetryExecution = async (execution: WorkflowExecution) => {
    if (!canEdit) {
      toast({
        title: t('workflows:view.permission.denied'),
        description: t('workflows:view.permission.retryExecutions'),
        variant: 'destructive',
      });
      return;
    }
    
    setIsActionInProgress(true);
    try {
      const response = await apiPost<{ message: string }>(`/api/workflows/executions/${execution.id}/retry`, {});
      if (response.data) {
        toast({
          title: t('common:toast.success'),
          description: t('workflows:view.messages.retryStarted'),
        });
        loadExecutions();
      }
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: t('workflows:view.messages.retryFailed'),
        variant: 'destructive',
      });
    } finally {
      setIsActionInProgress(false);
    }
  };

  const handleDeleteExecution = async () => {
    if (!executionToDelete) return;
    
    setIsActionInProgress(true);
    try {
      await apiDeleteApi(`/api/workflows/executions/${executionToDelete.id}`);
      toast({
        title: t('common:toast.success'),
        description: t('workflows:view.messages.executionDeleteSuccess'),
      });
      setDeleteExecutionDialogOpen(false);
      setExecutionToDelete(null);
      loadExecutions();
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: t('workflows:view.messages.executionDeleteFailed'),
        variant: 'destructive',
      });
    } finally {
      setIsActionInProgress(false);
    }
  };

  const openDeleteExecutionDialog = (execution: WorkflowExecution) => {
    setExecutionToDelete(execution);
    setDeleteExecutionDialogOpen(true);
  };

  // Force approve/reject handlers for paused workflows (admin override)
  const handleForceApprove = async (execution: WorkflowExecution) => {
    if (!canEdit) {
      toast({
        title: t('workflows:view.permission.denied'),
        description: t('workflows:view.permission.overrideApprovals'),
        variant: 'destructive',
      });
      return;
    }
    
    setIsActionInProgress(true);
    try {
      const response = await apiPost<{ message: string }>(
        `/api/workflows/executions/${execution.id}/resume`,
        { approved: true, message: t('workflows:view.messages.forceApprovedByAdmin') }
      );
      if (response.data) {
        toast({
          title: t('common:toast.success'),
          description: t('workflows:view.messages.approveResumeSuccess'),
        });
        loadExecutions();
      }
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: t('workflows:view.messages.approveFailed'),
        variant: 'destructive',
      });
    } finally {
      setIsActionInProgress(false);
    }
  };

  const handleForceReject = async (execution: WorkflowExecution) => {
    if (!canEdit) {
      toast({
        title: t('workflows:view.permission.denied'),
        description: t('workflows:view.permission.overrideApprovals'),
        variant: 'destructive',
      });
      return;
    }
    
    setIsActionInProgress(true);
    try {
      const response = await apiPost<{ message: string }>(
        `/api/workflows/executions/${execution.id}/resume`,
        { approved: false, message: t('workflows:view.messages.forceRejectedByAdmin') }
      );
      if (response.data) {
        toast({
          title: t('common:toast.success'),
          description: t('workflows:view.messages.rejectResumeSuccess'),
        });
        loadExecutions();
      }
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: t('workflows:view.messages.rejectFailed'),
        variant: 'destructive',
      });
    } finally {
      setIsActionInProgress(false);
    }
  };

  // Bulk action handlers for workflows
  const handleBulkToggleWorkflows = async (workflows: ProcessWorkflow[], enable: boolean) => {
    if (!canEdit) {
      toast({
        title: t('workflows:view.permission.denied'),
        description: t('workflows:view.permission.modifyWorkflows'),
        variant: 'destructive',
      });
      return;
    }

    const toUpdate = workflows.filter(w => w.is_active !== enable);
    if (toUpdate.length === 0) {
      toast({
        title: t('workflows:view.messages.noChanges'),
        description: enable
          ? t('workflows:view.messages.allAlreadyEnabled')
          : t('workflows:view.messages.allAlreadyDisabled'),
      });
      return;
    }

    try {
      const results = await Promise.allSettled(
        toUpdate.map(w => 
          apiPost<ProcessWorkflow>(`/api/workflows/${w.id}/toggle-active?is_active=${enable}`, {})
        )
      );
      const successes = results.filter(r => r.status === 'fulfilled').length;
      const failures = results.filter(r => r.status === 'rejected').length;

      if (successes > 0) {
        toast({
          title: t('common:toast.success'),
          description: enable
            ? t('workflows:view.messages.workflowsEnabled', { count: successes })
            : t('workflows:view.messages.workflowsDisabled', { count: successes }),
        });
        loadWorkflows();
      }
      if (failures > 0) {
        toast({
          title: t('common:toast.error'),
          description: t('workflows:view.messages.workflowsFailedUpdate', { count: failures }),
          variant: 'destructive',
        });
      }
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: t('workflows:view.messages.updateWorkflowsFailed'),
        variant: 'destructive',
      });
    }
  };

  const handleBulkDeleteWorkflows = async (workflows: ProcessWorkflow[]) => {
    if (!canEdit) {
      toast({
        title: t('workflows:view.permission.denied'),
        description: t('workflows:view.permission.deleteWorkflows'),
        variant: 'destructive',
      });
      return;
    }

    const deletable = workflows.filter(w => !w.is_default);
    const skipped = workflows.length - deletable.length;

    if (deletable.length === 0) {
      toast({
        title: t('workflows:view.messages.cannotDelete'),
        description: t('workflows:view.messages.allDefaultsCannotDelete'),
        variant: 'destructive',
      });
      return;
    }

    if (!confirm(`${t('workflows:view.confirm.deleteWorkflows', { count: deletable.length })}${skipped > 0 ? t('workflows:view.confirm.deleteWorkflowsSkipped', { count: skipped }) : ''}`)) {
      return;
    }

    try {
      const results = await Promise.allSettled(
        deletable.map(w => apiDeleteApi(`/api/workflows/${w.id}`))
      );
      const successes = results.filter(r => r.status === 'fulfilled').length;
      const failures = results.filter(r => r.status === 'rejected').length;

      if (successes > 0) {
        toast({
          title: t('common:toast.success'),
          description: t('workflows:view.messages.workflowsDeleted', { count: successes }),
        });
        loadWorkflows();
      }
      if (failures > 0) {
        toast({
          title: t('common:toast.error'),
          description: t('workflows:view.messages.workflowsFailedDelete', { count: failures }),
          variant: 'destructive',
        });
      }
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: t('workflows:view.messages.deleteWorkflowsFailed'),
        variant: 'destructive',
      });
    }
  };

  // Bulk action handlers for executions
  const handleBulkCancelExecutions = async (executions: WorkflowExecution[]) => {
    if (!canEdit) {
      toast({
        title: t('workflows:view.permission.denied'),
        description: t('workflows:view.permission.cancelExecutions'),
        variant: 'destructive',
      });
      return;
    }

    const cancellable = executions.filter(e => e.status === 'running' || e.status === 'paused');
    if (cancellable.length === 0) {
      toast({
        title: t('workflows:view.messages.noCancellable'),
        description: t('workflows:view.messages.noCancellableDesc'),
      });
      return;
    }

    try {
      const results = await Promise.allSettled(
        cancellable.map(e => apiPost<{ message: string }>(`/api/workflows/executions/${e.id}/cancel`, {}))
      );
      const successes = results.filter(r => r.status === 'fulfilled').length;
      const failures = results.filter(r => r.status === 'rejected').length;

      if (successes > 0) {
        toast({
          title: t('common:toast.success'),
          description: t('workflows:view.messages.executionsCancelled', { count: successes }),
        });
        loadExecutions();
      }
      if (failures > 0) {
        toast({
          title: t('common:toast.error'),
          description: t('workflows:view.messages.executionsFailedCancel', { count: failures }),
          variant: 'destructive',
        });
      }
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: t('workflows:view.messages.cancelExecutionsFailed'),
        variant: 'destructive',
      });
    }
  };

  const handleBulkRetryExecutions = async (executions: WorkflowExecution[]) => {
    if (!canEdit) {
      toast({
        title: t('workflows:view.permission.denied'),
        description: t('workflows:view.permission.retryExecutions'),
        variant: 'destructive',
      });
      return;
    }

    const retriable = executions.filter(e => e.status === 'failed' || e.status === 'cancelled');
    if (retriable.length === 0) {
      toast({
        title: t('workflows:view.messages.noRetriable'),
        description: t('workflows:view.messages.noRetriableDesc'),
      });
      return;
    }

    try {
      const results = await Promise.allSettled(
        retriable.map(e => apiPost<{ message: string }>(`/api/workflows/executions/${e.id}/retry`, {}))
      );
      const successes = results.filter(r => r.status === 'fulfilled').length;
      const failures = results.filter(r => r.status === 'rejected').length;

      if (successes > 0) {
        toast({
          title: t('common:toast.success'),
          description: t('workflows:view.messages.executionsRetryStarted', { count: successes }),
        });
        loadExecutions();
      }
      if (failures > 0) {
        toast({
          title: t('common:toast.error'),
          description: t('workflows:view.messages.executionsFailedRetry', { count: failures }),
          variant: 'destructive',
        });
      }
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: t('workflows:view.messages.retryExecutionsFailed'),
        variant: 'destructive',
      });
    }
  };

  const handleBulkDeleteExecutions = async (executions: WorkflowExecution[]) => {
    if (!canEdit) {
      toast({
        title: t('workflows:view.permission.denied'),
        description: t('workflows:view.permission.deleteExecutions'),
        variant: 'destructive',
      });
      return;
    }

    const deletable = executions.filter(e => e.status !== 'running' && e.status !== 'paused');
    const skipped = executions.length - deletable.length;

    if (deletable.length === 0) {
      toast({
        title: t('workflows:view.messages.cannotDelete'),
        description: t('workflows:view.messages.runningCannotDelete'),
        variant: 'destructive',
      });
      return;
    }

    if (!confirm(`${t('workflows:view.confirm.deleteExecutions', { count: deletable.length })}${skipped > 0 ? t('workflows:view.confirm.deleteExecutionsSkipped', { count: skipped }) : ''}`)) {
      return;
    }

    try {
      const results = await Promise.allSettled(
        deletable.map(e => apiDeleteApi(`/api/workflows/executions/${e.id}`))
      );
      const successes = results.filter(r => r.status === 'fulfilled').length;
      const failures = results.filter(r => r.status === 'rejected').length;

      if (successes > 0) {
        toast({
          title: t('common:toast.success'),
          description: t('workflows:view.messages.executionsDeleted', { count: successes }),
        });
        loadExecutions();
      }
      if (failures > 0) {
        toast({
          title: t('common:toast.error'),
          description: t('workflows:view.messages.executionsFailedDelete', { count: failures }),
          variant: 'destructive',
        });
      }
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: t('workflows:view.messages.deleteExecutionsFailed'),
        variant: 'destructive',
      });
    }
  };

  const workflowColumns: ColumnDef<ProcessWorkflow>[] = [
    {
      accessorKey: 'name',
      header: ({ column }: { column: Column<ProcessWorkflow, unknown> }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
          {t('common:labels.name')}
          <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => (
        <div className="flex items-center gap-2">
          <GitBranch className="h-4 w-4 text-muted-foreground" />
          <button
            onClick={() => navigate(`${pathname}/${row.original.id}`)}
            className="font-medium hover:underline hover:text-primary text-left"
          >
            {row.original.name}
          </button>
          {row.original.is_default && (
            <Badge variant="secondary" className="text-xs">{t('workflows:view.badges.default')}</Badge>
          )}
          {row.original.workflow_type === 'approval' ? (
            <Badge variant="outline" className="text-xs bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-800">{t('workflows:view.badges.approval')}</Badge>
          ) : (
            <Badge variant="outline" className="text-xs bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950 dark:text-blue-300 dark:border-blue-800">{t('workflows:view.badges.process')}</Badge>
          )}
        </div>
      ),
    },
    {
      accessorKey: 'trigger.type',
      header: ({ column }: { column: Column<ProcessWorkflow, unknown> }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
          {t('common:labels.type')}
          <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground">
          {getTriggerDisplay(row.original.trigger, t)}
        </span>
      ),
    },
    {
      accessorKey: 'steps',
      header: t('workflows:view.columns.steps'),
      enableSorting: false,
      cell: ({ row }) => (
        <div className="flex items-center gap-1">
          {row.original.steps.slice(0, 4).map((step, i) => (
            <span key={i} className="text-muted-foreground" title={step.step_type}>
              {getStepTypeIcon(step.step_type)}
            </span>
          ))}
          {row.original.steps.length > 4 && (
            <span className="text-xs text-muted-foreground">
              +{row.original.steps.length - 4}
            </span>
          )}
        </div>
      ),
    },
    {
      accessorKey: 'is_active',
      header: ({ column }: { column: Column<ProcessWorkflow, unknown> }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
          {t('common:labels.status')}
          <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => (
        <div className="flex items-center gap-2">
          <Switch
            checked={row.original.is_active}
            onCheckedChange={() => handleToggleWorkflowActive(row.original)}
            disabled={!canEdit}
          />
          <span className={row.original.is_active ? 'text-green-600 dark:text-green-400' : 'text-muted-foreground'}>
            {row.original.is_active ? t('common:labels.active') : t('common:labels.inactive')}
          </span>
        </div>
      ),
    },
    {
      id: 'actions',
      cell: ({ row }) => (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon">
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>{t('common:labels.actions')}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => handleEditWorkflow(row.original)}>
              <Pencil className="h-4 w-4 mr-2" />
              {canEdit ? t('common:actions.edit') : t('common:actions.view')}
            </DropdownMenuItem>
            {row.original.workflow_type === 'approval' && (
              <DropdownMenuItem onClick={() => setPreviewingWorkflow(row.original)}>
                <Eye className="h-4 w-4 mr-2" />
                {t('workflows:view.actions.previewWizard')}
              </DropdownMenuItem>
            )}
            {canEdit && (
              <>
                <DropdownMenuItem onClick={() => {
                  setDuplicatingWorkflow(row.original);
                  setDuplicateName(t('workflows:view.copyNameSuffix', { name: row.original.name }));
                  setDuplicateDialogOpen(true);
                }}>
                  <Copy className="h-4 w-4 mr-2" />
                  {t('workflows:view.actions.duplicate')}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={() => handleDeleteWorkflow(row.original)}
                  disabled={row.original.is_default}
                  className="text-destructive"
                >
                  <Trash2 className="h-4 w-4 mr-2" />
                  {t('common:actions.delete')}
                </DropdownMenuItem>
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      ),
    },
  ];

  const executionColumns: ColumnDef<WorkflowExecution>[] = [
    {
      accessorKey: 'workflow_name',
      header: ({ column }: { column: Column<WorkflowExecution, unknown> }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
          {t('workflows:view.columns.workflow')}
          <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => {
        const wfMatch = workflows.find(w => w.name === row.original.workflow_name);
        const wfType = wfMatch?.workflow_type || 'process';
        return (
          <div className="flex items-center gap-2">
            <GitBranch className="h-4 w-4 text-muted-foreground" />
            <span className="font-medium">{row.original.workflow_name}</span>
            {wfType === 'approval' ? (
              <Badge variant="outline" className="text-xs bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-800">{t('workflows:view.badges.approval')}</Badge>
            ) : (
              <Badge variant="outline" className="text-xs bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950 dark:text-blue-300 dark:border-blue-800">{t('workflows:view.badges.process')}</Badge>
            )}
          </div>
        );
      },
    },
    {
      accessorKey: 'entity_name',
      header: t('workflows:view.columns.entity'),
      enableSorting: false,
      cell: ({ row }) => {
        const { entity_type, entity_name, entity_id } = row.original;
        if (!entity_type && !entity_name) return <span className="text-muted-foreground">-</span>;
        return (
          <div className="flex flex-col">
            <span className="text-sm font-medium">{entity_name || entity_id || '-'}</span>
            {entity_type && (
              <span className="text-xs text-muted-foreground capitalize">{entity_type}</span>
            )}
          </div>
        );
      },
    },
    {
      accessorKey: 'status',
      header: ({ column }: { column: Column<WorkflowExecution, unknown> }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
          {t('common:labels.status')}
          <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => getStatusBadge(row.original.status),
    },
    {
      accessorKey: 'current_step_name',
      header: t('workflows:view.columns.currentStep'),
      enableSorting: false,
      cell: ({ row }) => {
        const { status, current_step_name, current_step_id } = row.original;
        if (status !== 'paused' && status !== 'running') return null;
        const stepDisplay = current_step_name || current_step_id || '-';
        return (
          <Badge variant="outline" className="bg-amber-500/10 text-amber-600 border-amber-500/30 dark:text-amber-400">
            {stepDisplay}
          </Badge>
        );
      },
    },
    {
      accessorKey: 'started_at',
      header: ({ column }: { column: Column<WorkflowExecution, unknown> }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
          {t('workflows:view.columns.started')}
          <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => (
        <RelativeDate 
          date={row.original.started_at} 
          className="text-sm text-muted-foreground" 
        />
      ),
    },
    {
      accessorKey: 'finished_at',
      header: ({ column }: { column: Column<WorkflowExecution, unknown> }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
          {t('workflows:view.columns.completed')}
          <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => (
        <RelativeDate 
          date={row.original.finished_at} 
          className="text-sm text-muted-foreground" 
        />
      ),
    },
    {
      accessorKey: 'error_message',
      header: t('workflows:view.columns.error'),
      enableSorting: false,
      cell: ({ row }) => {
        const errorMessage = row.original.error_message;
        if (!errorMessage) return null;
        // `truncate` is a no-op on inline spans, so a multi-line stack trace
        // used to expand the row vertically; clamp to 2 lines on a block button
        // and hoist the full text into a Popover for inspection / copy.
        return (
          <Popover>
            <PopoverTrigger asChild>
              <button
                type="button"
                className="text-left text-sm text-destructive line-clamp-2 max-w-[280px] hover:underline focus:outline-none focus:ring-1 focus:ring-destructive/40 rounded-sm"
                onClick={(e) => e.stopPropagation()}
                title={t('workflows:view.tooltips.clickFullError')}
              >
                {errorMessage}
              </button>
            </PopoverTrigger>
            <PopoverContent
              align="start"
              side="bottom"
              className="w-[480px] max-w-[90vw] p-0"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between border-b px-3 py-2">
                <span className="text-xs font-medium text-muted-foreground">{t('workflows:view.errorDetails')}</span>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-xs"
                  onClick={() => {
                    void navigator.clipboard?.writeText(errorMessage).then(() => {
                      toast({ title: t('common:copied'), description: t('workflows:view.messages.errorCopied') });
                    });
                  }}
                >
                  <Copy className="h-3 w-3 mr-1" />
                  {t('common:actions.copy')}
                </Button>
              </div>
              <pre className="max-h-[320px] overflow-auto whitespace-pre-wrap break-words p-3 text-xs text-destructive">
                {errorMessage}
              </pre>
            </PopoverContent>
          </Popover>
        );
      },
    },
    {
      id: 'actions',
      header: '',
      enableSorting: false,
      cell: ({ row }) => {
        const execution = row.original;
        const canCancel = execution.status === 'running' || execution.status === 'paused';
        const canRetry = execution.status === 'failed' || execution.status === 'cancelled';
        const canDelete = execution.status !== 'running' && execution.status !== 'paused';
        const isPaused = execution.status === 'paused';
        // Show separator before delete only if there are other actions above it
        const hasActionsAboveDelete = isPaused || canCancel || canRetry;
        
        if (!canEdit) return null;
        
        return (
          <DropdownMenu>
            <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
              <Button variant="ghost" size="sm" className="h-8 w-8 p-0">
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
              <DropdownMenuLabel>{t('common:labels.actions')}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {isPaused && (
                <>
                  <DropdownMenuItem 
                    onClick={() => handleForceApprove(execution)}
                    disabled={isActionInProgress}
                  >
                    <CheckCircle className="h-4 w-4 mr-2 text-green-600 dark:text-green-400" />
                    {t('workflows:view.actions.forceApprove')}
                  </DropdownMenuItem>
                  <DropdownMenuItem 
                    onClick={() => handleForceReject(execution)}
                    disabled={isActionInProgress}
                  >
                    <XCircle className="h-4 w-4 mr-2 text-red-600 dark:text-red-400" />
                    {t('workflows:view.actions.forceReject')}
                  </DropdownMenuItem>
                </>
              )}
              {canCancel && (
                <DropdownMenuItem 
                  onClick={() => handleCancelExecution(execution)}
                  disabled={isActionInProgress}
                >
                  <XCircle className="h-4 w-4 mr-2" />
                  {t('common:actions.cancel')}
                </DropdownMenuItem>
              )}
              {canRetry && (
                <DropdownMenuItem 
                  onClick={() => handleRetryExecution(execution)}
                  disabled={isActionInProgress}
                >
                  <RotateCcw className="h-4 w-4 mr-2" />
                  {t('common:retry')}
                </DropdownMenuItem>
              )}
              {canDelete && (
                <>
                  {hasActionsAboveDelete && <DropdownMenuSeparator />}
                  <DropdownMenuItem 
                    onClick={() => openDeleteExecutionDialog(execution)}
                    className="text-destructive focus:text-destructive"
                    disabled={isActionInProgress}
                  >
                    <Trash2 className="h-4 w-4 mr-2" />
                    {t('common:actions.delete')}
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        );
      },
    },
  ];

  // Client-side type filtering (all data fetched once, tab switching is instant)
  const typeFilteredWorkflows = useMemo(() => {
    if (workflowTypeFilter === 'all') return workflows;
    return workflows.filter(w => (w.workflow_type || 'process') === workflowTypeFilter);
  }, [workflows, workflowTypeFilter]);

  // Build a set of workflow IDs for the active type filter to filter executions
  const typeFilteredWorkflowIds = useMemo(() => {
    if (workflowTypeFilter === 'all') return null; // null = don't filter
    return new Set(typeFilteredWorkflows.map(w => w.id));
  }, [workflowTypeFilter, typeFilteredWorkflows]);

  const typeFilteredExecutions = useMemo(() => {
    if (!typeFilteredWorkflowIds) return executions;
    return executions.filter(e => {
      // Match execution to workflow by workflow_id (from trigger context or name)
      const wfMatch = typeFilteredWorkflows.find(w => w.name === e.workflow_name);
      return wfMatch != null;
    });
  }, [executions, typeFilteredWorkflowIds, typeFilteredWorkflows]);

  // Transform approval sessions into execution-shaped rows for the unified table
  const approvalSessionsAsExecutions = useMemo(() => {
    if (workflowTypeFilter === 'process') return [];
    return approvalSessions.map((s): WorkflowExecution => ({
      id: s.id,
      workflow_id: s.workflow_id,
      workflow_name: s.workflow_name || t('workflows:view.approvalWorkflowFallback'),
      status: s.status === 'completed' ? 'succeeded' : s.status === 'abandoned' ? 'cancelled' : 'running',
      entity_type: s.entity_type,
      entity_id: s.entity_id,
      entity_name: s.entity_id,
      started_at: s.created_at,
      finished_at: s.updated_at,
      current_step_name: s.status === 'in_progress' ? t('workflows:view.stepLabel', { number: (s.current_step_index || 0) + 1 }) : undefined,
      success_count: s.status === 'completed' ? 1 : 0,
      failure_count: s.status === 'abandoned' ? 1 : 0,
      step_executions: [],
    }));
  }, [approvalSessions, workflowTypeFilter]);

  // Stats (computed after allExecutions is defined below)

  // Stats card filtered data (layered on top of type filtering)
  const filteredWorkflows = useMemo(() => {
    if (statsFilter === 'active') return typeFilteredWorkflows.filter(w => w.is_active);
    if (statsFilter === 'inactive') return typeFilteredWorkflows.filter(w => !w.is_active);
    if (statsFilter === 'default') return typeFilteredWorkflows.filter(w => w.is_default);
    return typeFilteredWorkflows;
  }, [typeFilteredWorkflows, statsFilter]);

  // Merge process executions + approval sessions into one unified list
  const allExecutions = useMemo(() => {
    const merged = [...typeFilteredExecutions, ...approvalSessionsAsExecutions];
    return merged.sort((a, b) => {
      const da = a.started_at ? new Date(a.started_at).getTime() : 0;
      const db = b.started_at ? new Date(b.started_at).getTime() : 0;
      return db - da; // newest first
    });
  }, [typeFilteredExecutions, approvalSessionsAsExecutions]);

  // Stats (computed from merged executions so they include approval sessions)
  const activeWorkflows = typeFilteredWorkflows.filter(w => w.is_active).length;
  const totalWorkflows = typeFilteredWorkflows.length;
  const runningExecutions = allExecutions.filter(e => e.status === 'running' || e.status === 'paused').length;
  const recentFailures = allExecutions.filter(e => e.status === 'failed' || e.status === 'cancelled').length;

  const filteredExecutions = useMemo(() => {
    if (statsFilter === 'running') return allExecutions.filter(e => e.status === 'running' || e.status === 'paused');
    if (statsFilter === 'failed') return allExecutions.filter(e => e.status === 'failed' || e.status === 'cancelled');
    return allExecutions;
  }, [allExecutions, statsFilter]);

  // Reset stats filter when workflow type changes
  useEffect(() => { setStatsFilter('all'); }, [workflowTypeFilter]);

  return (
    <SettingsPageWrapper title={t('common:labels.workflows', 'Workflows')} permissionId="settings-workflows">
      <div className="mb-6">
        <div className="flex justify-between items-start">
          <div>
            <h1 className="text-3xl font-bold flex items-center gap-2">
              <GitBranch className="w-8 h-8" />
              {t('common:labels.workflows', 'Workflows')}
            </h1>
            <p className="text-muted-foreground mt-1">
              {t('workflows:view.subtitle')}
            </p>
          </div>
          {canEdit && (
            <div className="flex items-center gap-2">
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline">
                    <Clock className="h-4 w-4 mr-2" />
                    {t('workflows:view.actions.loadDefaults')}
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuLabel>{t('workflows:view.loadDefaults.menuLabel')}</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={() => handleLoadDefaultWorkflows(false)}>
                    <Plus className="h-4 w-4 mr-2" />
                    {t('workflows:view.loadDefaults.newOnly')}
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => handleLoadDefaultWorkflows(true)}>
                    <RotateCcw className="h-4 w-4 mr-2" />
                    {t('workflows:view.loadDefaults.reloadAll')}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              <Button onClick={() => navigate(`${pathname}/new${workflowTypeFilter !== 'all' ? `?type=${workflowTypeFilter}` : ''}`)}>
                <Plus className="h-4 w-4 mr-2" />
                {t('workflows:view.actions.createWorkflow')}
              </Button>
            </div>
          )}
        </div>
        <div className="mt-4">
          <Tabs value={workflowTypeFilter} onValueChange={(v) => setWorkflowTypeFilter(v as 'all' | 'process' | 'approval')}>
            <div className="flex items-center gap-3">
              <TabsList className="h-auto p-1">
                <TabsTrigger value="all" className="px-4 py-2">
                  <span>{t('common:states.all')}</span>
                </TabsTrigger>
                <TabsTrigger value="process" className="px-4 py-2">
                  <span>{t('workflows:view.badges.process')}</span>
                </TabsTrigger>
                <TabsTrigger value="approval" className="px-4 py-2">
                  <span>{t('workflows:view.badges.approval')}</span>
                </TabsTrigger>
              </TabsList>
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <HelpCircle className="h-4 w-4 text-muted-foreground cursor-help" />
                  </TooltipTrigger>
                  <TooltipContent side="right" className="max-w-xs">
                    <ul className="text-xs space-y-1 list-disc pl-3">
                      <li>{t('workflows:view.help.process')}</li>
                      <li>{t('workflows:view.help.approval')}</li>
                      <li>{t('workflows:view.help.chain')}</li>
                    </ul>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </div>
          </Tabs>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8 min-h-[120px]">
        <Card
          className={`cursor-pointer transition-colors hover:border-primary ${statsFilter === 'active' ? 'border-primary bg-primary/5' : statsFilter === 'inactive' ? 'border-amber-500 bg-amber-500/5' : ''}`}
          onClick={() => setStatsFilter(prev => prev === 'active' ? 'all' : 'active')}
        >
          <CardHeader className="pb-2">
            <CardTitle className="text-lg">{t('workflows:view.stats.activeWorkflows')}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold text-green-600 dark:text-green-400">{activeWorkflows}</div>
            <p className="text-sm text-muted-foreground mt-1">
              {t('workflows:view.stats.ofTotal', { count: totalWorkflows })}
              {totalWorkflows - activeWorkflows > 0 && (
                <button
                  className="ml-1 text-amber-600 hover:underline"
                  onClick={(e) => { e.stopPropagation(); setStatsFilter(prev => prev === 'inactive' ? 'all' : 'inactive'); }}
                >
                  {t('workflows:view.stats.inactiveCount', { count: totalWorkflows - activeWorkflows })}
                </button>
              )}
            </p>
          </CardContent>
        </Card>
        <Card
          className={`cursor-pointer transition-colors hover:border-primary ${statsFilter === 'default' ? 'border-primary bg-primary/5' : ''}`}
          onClick={() => setStatsFilter(prev => prev === 'default' ? 'all' : 'default')}
        >
          <CardHeader className="pb-2">
            <CardTitle className="text-lg">{t('workflows:view.stats.defaultWorkflows')}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{typeFilteredWorkflows.filter(w => w.is_default).length}</div>
            <p className="text-sm text-muted-foreground mt-1">{t('workflows:view.stats.builtInWorkflows')}</p>
          </CardContent>
        </Card>
        <Card
          className={`cursor-pointer transition-colors hover:border-primary ${statsFilter === 'running' ? 'border-primary bg-primary/5' : ''}`}
          onClick={() => setStatsFilter(prev => prev === 'running' ? 'all' : 'running')}
        >
          <CardHeader className="pb-2">
            <CardTitle className="text-lg">{t('workflows:view.stats.inProgress')}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold text-blue-600">{runningExecutions}</div>
            <p className="text-sm text-muted-foreground mt-1">{t('workflows:view.stats.runningOrPaused')}</p>
          </CardContent>
        </Card>
        <Card
          className={`cursor-pointer transition-colors hover:border-primary ${statsFilter === 'failed' ? 'border-primary bg-primary/5' : ''}`}
          onClick={() => setStatsFilter(prev => prev === 'failed' ? 'all' : 'failed')}
        >
          <CardHeader className="pb-2">
            <CardTitle className="text-lg">{t('workflows:view.stats.recentFailures')}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className={`text-3xl font-bold ${recentFailures > 0 ? 'text-red-600' : ''}`}>
              {recentFailures}
            </div>
            <p className="text-sm text-muted-foreground mt-1">{t('workflows:view.stats.inLast50Runs')}</p>
          </CardContent>
        </Card>
      </div>

      {/* Stats filter indicator */}
      {statsFilter !== 'all' && (
        <div className="flex items-center gap-2 mb-4">
          <Badge variant="outline" className="text-sm">
            {t('workflows:view.filter.label', { filter: statsFilter === 'active' ? t('workflows:view.filter.active') : statsFilter === 'inactive' ? t('workflows:view.filter.inactive') : statsFilter === 'default' ? t('workflows:view.filter.default') : statsFilter === 'running' ? t('workflows:view.filter.running') : t('workflows:view.filter.failed') })}
          </Badge>
          <button className="text-xs text-muted-foreground hover:text-foreground" onClick={() => setStatsFilter('all')}>
            {t('workflows:view.filter.clear')}
          </button>
        </div>
      )}

      {/* Workflows Table */}
      <Card className="mb-8">
        <CardHeader>
          <div>
            <CardTitle className="flex items-center gap-2">
              <GitBranch className="h-5 w-5" />
              {t('workflows:view.sections.definitionsTitle')}
            </CardTitle>
            <CardDescription>
              {t('workflows:view.subtitle')}
              {!canEdit && (
                <span className="text-yellow-600 ml-2">{t('workflows:view.readOnlyAccess')}</span>
              )}
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          {isLoadingWorkflows ? (
            <TableSkeleton columns={5} rows={5} bordered={false} />
          ) : workflows.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <GitBranch className="h-12 w-12 mx-auto mb-4 opacity-20" />
              <p>{t('workflows:view.empty.noWorkflows')}</p>
              {canEdit && (
                <p className="text-sm">{t('workflows:view.empty.noWorkflowsHint')}</p>
              )}
            </div>
          ) : (
            <DataTable
              columns={workflowColumns}
              data={filteredWorkflows}
              searchColumn="name"
              storageKey="workflows-sort"
              bulkActions={canEdit ? (selectedRows) => (
                <>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-9 gap-1"
                    onClick={() => handleBulkToggleWorkflows(selectedRows, true)}
                  >
                    <Power className="w-4 h-4 mr-1" />
                    {t('workflows:view.bulk.enable', { count: selectedRows.length })}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-9 gap-1"
                    onClick={() => handleBulkToggleWorkflows(selectedRows, false)}
                  >
                    <PowerOff className="w-4 h-4 mr-1" />
                    {t('workflows:view.bulk.disable', { count: selectedRows.length })}
                  </Button>
                  <Button
                    variant="destructive"
                    size="sm"
                    className="h-9 gap-1"
                    onClick={() => handleBulkDeleteWorkflows(selectedRows)}
                  >
                    <Trash2 className="w-4 h-4 mr-1" />
                    {t('workflows:view.bulk.delete', { count: selectedRows.length })}
                  </Button>
                </>
              ) : undefined}
            />
          )}
        </CardContent>
      </Card>

      {/* Executions Table */}
      <Card>
        <CardHeader>
          <div>
            <CardTitle className="flex items-center gap-2">
              <Play className="h-5 w-5" />
              {t('workflows:view.sections.executionsTitle')}
            </CardTitle>
            <CardDescription>
              {t('workflows:view.sections.executionsDescription')}
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          {isLoadingExecutions ? (
            <TableSkeleton columns={8} rows={5} bordered={false} />
          ) : executions.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <Play className="h-12 w-12 mx-auto mb-4 opacity-20" />
              <p>{t('workflows:view.empty.noExecutions')}</p>
              <p className="text-sm">{t('workflows:view.empty.noExecutionsHint')}</p>
            </div>
          ) : (
            <DataTable
              columns={executionColumns}
              data={filteredExecutions}
              searchColumn="workflow_name"
              storageKey="workflow-executions-sort"
              onRowClick={(row) => {
                setSelectedExecution(row.original);
                setExecutionDialogOpen(true);
              }}
              bulkActions={canEdit ? (selectedRows) => (
                <>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-9 gap-1"
                    onClick={() => handleBulkCancelExecutions(selectedRows)}
                  >
                    <XCircle className="w-4 h-4 mr-1" />
                    {t('workflows:view.bulk.cancel', { count: selectedRows.filter(e => e.status === 'running' || e.status === 'paused').length })}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-9 gap-1"
                    onClick={() => handleBulkRetryExecutions(selectedRows)}
                  >
                    <RotateCcw className="w-4 h-4 mr-1" />
                    {t('workflows:view.bulk.retry', { count: selectedRows.filter(e => e.status === 'failed' || e.status === 'cancelled').length })}
                  </Button>
                  <Button
                    variant="destructive"
                    size="sm"
                    className="h-9 gap-1"
                    onClick={() => handleBulkDeleteExecutions(selectedRows)}
                  >
                    <Trash2 className="w-4 h-4 mr-1" />
                    {t('workflows:view.bulk.delete', { count: selectedRows.filter(e => e.status !== 'running' && e.status !== 'paused').length })}
                  </Button>
                </>
              ) : undefined}
            />
          )}
        </CardContent>
      </Card>

      {/* Approval Sessions are merged into the Recent Executions table above */}

      {/* Duplicate Workflow Dialog */}
      <Dialog open={duplicateDialogOpen} onOpenChange={setDuplicateDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('workflows:view.dialogs.duplicateTitle')}</DialogTitle>
            <DialogDescription>
              {t('workflows:view.dialogs.duplicateDescription', { name: duplicatingWorkflow?.name })}
            </DialogDescription>
          </DialogHeader>
          <div className="py-4">
            <Input
              placeholder={t('workflows:view.placeholders.newWorkflowName')}
              value={duplicateName}
              onChange={(e) => setDuplicateName(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDuplicateDialogOpen(false)}>
              {t('common:actions.cancel')}
            </Button>
            <Button onClick={handleDuplicateWorkflow} disabled={isDuplicating || !duplicateName.trim()}>
              {isDuplicating && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              {t('workflows:view.actions.duplicate')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      
      {/* Workflow Execution Detail Dialog */}
      <WorkflowExecutionDialog
        execution={selectedExecution}
        open={executionDialogOpen}
        onOpenChange={setExecutionDialogOpen}
      />

      {/* Approval Wizard Preview (issue #405) — synthetic dry-run, no API
          session, no agreement, no notifications. */}
      {previewingWorkflow && (
        <ApprovalWizardDialog
          isOpen={!!previewingWorkflow}
          onOpenChange={(open) => { if (!open) setPreviewingWorkflow(null); }}
          entityType="preview"
          entityId="preview"
          entityName={previewingWorkflow.name}
          preselectedWorkflowId={previewingWorkflow.id}
          autoStartWithPreselected
          previewMode
        />
      )}

      {/* Delete Execution Confirmation Dialog */}
      <Dialog open={deleteExecutionDialogOpen} onOpenChange={setDeleteExecutionDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('workflows:view.dialogs.deleteExecutionTitle')}</DialogTitle>
            <DialogDescription>
              {t('workflows:view.dialogs.deleteExecutionDescription')}
            </DialogDescription>
          </DialogHeader>
          {executionToDelete && (
            <div className="py-4 space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">{t('workflows:view.detail.workflow')}</span>
                <span className="text-sm text-muted-foreground">{executionToDelete.workflow_name}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">{t('workflows:view.detail.status')}</span>
                {getStatusBadge(executionToDelete.status)}
              </div>
              {executionToDelete.entity_name && (
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{t('workflows:view.detail.entity')}</span>
                  <span className="text-sm text-muted-foreground">{executionToDelete.entity_name}</span>
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteExecutionDialogOpen(false)}>
              {t('common:actions.cancel')}
            </Button>
            <Button 
              variant="destructive" 
              onClick={handleDeleteExecution} 
              disabled={isActionInProgress}
            >
              {isActionInProgress && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              {t('common:actions.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </SettingsPageWrapper>
  );
}
