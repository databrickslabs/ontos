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
  UserCheck,
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
import { ColumnDef, Column } from "@tanstack/react-table";
import { useApi } from '@/hooks/use-api';
import SettingsPageWrapper from '@/components/settings/settings-page-wrapper';
import { DataTable } from '@/components/ui/data-table';
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
  const { t } = useTranslation(['common']);
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
  const [isLoadingApprovalSessions, setIsLoadingApprovalSessions] = useState(true);
  
  // Execution detail dialog state
  const [selectedExecution, setSelectedExecution] = useState<WorkflowExecution | null>(null);
  const [executionDialogOpen, setExecutionDialogOpen] = useState(false);
  
  // Execution action states
  const [deleteExecutionDialogOpen, setDeleteExecutionDialogOpen] = useState(false);
  const [executionToDelete, setExecutionToDelete] = useState<WorkflowExecution | null>(null);
  const [isActionInProgress, setIsActionInProgress] = useState(false);

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
        description: 'Failed to load workflows',
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
        title: 'Permission Denied',
        description: 'You do not have permission to modify workflows.',
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
          description: `Workflow ${response.data.is_active ? 'enabled' : 'disabled'}`,
        });
      }
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: 'Failed to update workflow status',
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
          description: 'Workflow duplicated successfully',
        });
        setDuplicateDialogOpen(false);
        setDuplicatingWorkflow(null);
        setDuplicateName('');
      }
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: 'Failed to duplicate workflow',
        variant: 'destructive',
      });
    } finally {
      setIsDuplicating(false);
    }
  };

  const handleDeleteWorkflow = async (workflow: ProcessWorkflow) => {
    if (!canEdit) {
      toast({
        title: 'Permission Denied',
        description: 'You do not have permission to delete workflows.',
        variant: 'destructive',
      });
      return;
    }
    
    if (workflow.is_default) {
      toast({
        title: 'Cannot Delete',
        description: 'Default workflows cannot be deleted. Disable them instead.',
        variant: 'destructive',
      });
      return;
    }
    
    try {
      await apiDeleteApi(`/api/workflows/${workflow.id}`);
      setWorkflows(prev => prev.filter(w => w.id !== workflow.id));
      toast({
        title: t('common:toast.success'),
        description: 'Workflow deleted',
      });
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: 'Failed to delete workflow',
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
        title: 'Permission Denied',
        description: 'You do not have permission to load default workflows.',
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
        description: 'Failed to load default workflows',
        variant: 'destructive',
      });
    }
  };

  // Execution administration handlers
  const handleCancelExecution = async (execution: WorkflowExecution) => {
    if (!canEdit) {
      toast({
        title: 'Permission Denied',
        description: 'You do not have permission to cancel executions.',
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
          description: 'Execution cancelled successfully',
        });
        loadExecutions();
      }
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: 'Failed to cancel execution',
        variant: 'destructive',
      });
    } finally {
      setIsActionInProgress(false);
    }
  };

  const handleRetryExecution = async (execution: WorkflowExecution) => {
    if (!canEdit) {
      toast({
        title: 'Permission Denied',
        description: 'You do not have permission to retry executions.',
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
          description: 'Execution retry started',
        });
        loadExecutions();
      }
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: 'Failed to retry execution',
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
        description: 'Execution deleted successfully',
      });
      setDeleteExecutionDialogOpen(false);
      setExecutionToDelete(null);
      loadExecutions();
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: 'Failed to delete execution',
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
        title: 'Permission Denied',
        description: 'You do not have permission to override workflow approvals.',
        variant: 'destructive',
      });
      return;
    }
    
    setIsActionInProgress(true);
    try {
      const response = await apiPost<{ message: string }>(
        `/api/workflows/executions/${execution.id}/resume`,
        { approved: true, message: 'Force approved by administrator' }
      );
      if (response.data) {
        toast({
          title: t('common:toast.success'),
          description: 'Workflow approved and resumed',
        });
        loadExecutions();
      }
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: 'Failed to approve workflow',
        variant: 'destructive',
      });
    } finally {
      setIsActionInProgress(false);
    }
  };

  const handleForceReject = async (execution: WorkflowExecution) => {
    if (!canEdit) {
      toast({
        title: 'Permission Denied',
        description: 'You do not have permission to override workflow approvals.',
        variant: 'destructive',
      });
      return;
    }
    
    setIsActionInProgress(true);
    try {
      const response = await apiPost<{ message: string }>(
        `/api/workflows/executions/${execution.id}/resume`,
        { approved: false, message: 'Force rejected by administrator' }
      );
      if (response.data) {
        toast({
          title: t('common:toast.success'),
          description: 'Workflow rejected and resumed',
        });
        loadExecutions();
      }
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: 'Failed to reject workflow',
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
        title: 'Permission Denied',
        description: 'You do not have permission to modify workflows.',
        variant: 'destructive',
      });
      return;
    }

    const toUpdate = workflows.filter(w => w.is_active !== enable);
    if (toUpdate.length === 0) {
      toast({
        title: 'No Changes',
        description: `All selected workflows are already ${enable ? 'enabled' : 'disabled'}.`,
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
          description: `${successes} workflow(s) ${enable ? 'enabled' : 'disabled'}.`,
        });
        loadWorkflows();
      }
      if (failures > 0) {
        toast({
          title: t('common:toast.error'),
          description: `${failures} workflow(s) failed to update.`,
          variant: 'destructive',
        });
      }
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: 'Failed to update workflows',
        variant: 'destructive',
      });
    }
  };

  const handleBulkDeleteWorkflows = async (workflows: ProcessWorkflow[]) => {
    if (!canEdit) {
      toast({
        title: 'Permission Denied',
        description: 'You do not have permission to delete workflows.',
        variant: 'destructive',
      });
      return;
    }

    const deletable = workflows.filter(w => !w.is_default);
    const skipped = workflows.length - deletable.length;

    if (deletable.length === 0) {
      toast({
        title: 'Cannot Delete',
        description: 'All selected workflows are defaults and cannot be deleted.',
        variant: 'destructive',
      });
      return;
    }

    if (!confirm(`Are you sure you want to delete ${deletable.length} workflow(s)?${skipped > 0 ? ` (${skipped} default workflow(s) will be skipped)` : ''}`)) {
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
          description: `${successes} workflow(s) deleted.`,
        });
        loadWorkflows();
      }
      if (failures > 0) {
        toast({
          title: t('common:toast.error'),
          description: `${failures} workflow(s) failed to delete.`,
          variant: 'destructive',
        });
      }
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: 'Failed to delete workflows',
        variant: 'destructive',
      });
    }
  };

  // Bulk action handlers for executions
  const handleBulkCancelExecutions = async (executions: WorkflowExecution[]) => {
    if (!canEdit) {
      toast({
        title: 'Permission Denied',
        description: 'You do not have permission to cancel executions.',
        variant: 'destructive',
      });
      return;
    }

    const cancellable = executions.filter(e => e.status === 'running' || e.status === 'paused');
    if (cancellable.length === 0) {
      toast({
        title: 'No Cancellable Executions',
        description: 'None of the selected executions can be cancelled.',
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
          description: `${successes} execution(s) cancelled.`,
        });
        loadExecutions();
      }
      if (failures > 0) {
        toast({
          title: t('common:toast.error'),
          description: `${failures} execution(s) failed to cancel.`,
          variant: 'destructive',
        });
      }
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: 'Failed to cancel executions',
        variant: 'destructive',
      });
    }
  };

  const handleBulkRetryExecutions = async (executions: WorkflowExecution[]) => {
    if (!canEdit) {
      toast({
        title: 'Permission Denied',
        description: 'You do not have permission to retry executions.',
        variant: 'destructive',
      });
      return;
    }

    const retriable = executions.filter(e => e.status === 'failed' || e.status === 'cancelled');
    if (retriable.length === 0) {
      toast({
        title: 'No Retriable Executions',
        description: 'None of the selected executions can be retried.',
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
          description: `${successes} execution(s) retry started.`,
        });
        loadExecutions();
      }
      if (failures > 0) {
        toast({
          title: t('common:toast.error'),
          description: `${failures} execution(s) failed to retry.`,
          variant: 'destructive',
        });
      }
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: 'Failed to retry executions',
        variant: 'destructive',
      });
    }
  };

  const handleBulkDeleteExecutions = async (executions: WorkflowExecution[]) => {
    if (!canEdit) {
      toast({
        title: 'Permission Denied',
        description: 'You do not have permission to delete executions.',
        variant: 'destructive',
      });
      return;
    }

    const deletable = executions.filter(e => e.status !== 'running' && e.status !== 'paused');
    const skipped = executions.length - deletable.length;

    if (deletable.length === 0) {
      toast({
        title: 'Cannot Delete',
        description: 'Running or paused executions cannot be deleted.',
        variant: 'destructive',
      });
      return;
    }

    if (!confirm(`Are you sure you want to delete ${deletable.length} execution(s)?${skipped > 0 ? ` (${skipped} running/paused execution(s) will be skipped)` : ''}`)) {
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
          description: `${successes} execution(s) deleted.`,
        });
        loadExecutions();
      }
      if (failures > 0) {
        toast({
          title: t('common:toast.error'),
          description: `${failures} execution(s) failed to delete.`,
          variant: 'destructive',
        });
      }
    } catch (error) {
      toast({
        title: t('common:toast.error'),
        description: 'Failed to delete executions',
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
            <Badge variant="secondary" className="text-xs">Default</Badge>
          )}
          {row.original.workflow_type === 'approval' ? (
            <Badge variant="outline" className="text-xs bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-800">Approval</Badge>
          ) : (
            <Badge variant="outline" className="text-xs bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950 dark:text-blue-300 dark:border-blue-800">Process</Badge>
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
      header: 'Steps',
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
            {canEdit && (
              <>
                <DropdownMenuItem onClick={() => {
                  setDuplicatingWorkflow(row.original);
                  setDuplicateName(`${row.original.name} (Copy)`);
                  setDuplicateDialogOpen(true);
                }}>
                  <Copy className="h-4 w-4 mr-2" />
                  Duplicate
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
          Workflow
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
              <Badge variant="outline" className="text-xs bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-800">Approval</Badge>
            ) : (
              <Badge variant="outline" className="text-xs bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950 dark:text-blue-300 dark:border-blue-800">Process</Badge>
            )}
          </div>
        );
      },
    },
    {
      accessorKey: 'entity_name',
      header: 'Entity',
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
      header: 'Current Step',
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
          Started
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
          Completed
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
      header: 'Error',
      enableSorting: false,
      cell: ({ row }) => (
        row.original.error_message ? (
          <span className="text-sm text-destructive truncate max-w-[200px]" title={row.original.error_message}>
            {row.original.error_message}
          </span>
        ) : null
      ),
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
              <DropdownMenuLabel>Actions</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {isPaused && (
                <>
                  <DropdownMenuItem 
                    onClick={() => handleForceApprove(execution)}
                    disabled={isActionInProgress}
                  >
                    <CheckCircle className="h-4 w-4 mr-2 text-green-600 dark:text-green-400" />
                    Force Approve
                  </DropdownMenuItem>
                  <DropdownMenuItem 
                    onClick={() => handleForceReject(execution)}
                    disabled={isActionInProgress}
                  >
                    <XCircle className="h-4 w-4 mr-2 text-red-600 dark:text-red-400" />
                    Force Reject
                  </DropdownMenuItem>
                </>
              )}
              {canCancel && (
                <DropdownMenuItem 
                  onClick={() => handleCancelExecution(execution)}
                  disabled={isActionInProgress}
                >
                  <XCircle className="h-4 w-4 mr-2" />
                  Cancel
                </DropdownMenuItem>
              )}
              {canRetry && (
                <DropdownMenuItem 
                  onClick={() => handleRetryExecution(execution)}
                  disabled={isActionInProgress}
                >
                  <RotateCcw className="h-4 w-4 mr-2" />
                  Retry
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
                    Delete
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        );
      },
    },
  ];

  const approvalSessionColumns: ColumnDef<any>[] = [
    {
      accessorKey: 'workflow_name',
      header: 'Workflow',
      cell: ({ row }) => (
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="text-xs bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-800">Approval</Badge>
          <span className="font-medium">{row.original.workflow_name || 'Unknown'}</span>
        </div>
      ),
    },
    {
      accessorKey: 'entity_type',
      header: 'Entity',
      cell: ({ row }) => (
        <span className="text-sm">{row.original.entity_type}: {row.original.entity_id?.substring(0, 8)}...</span>
      ),
    },
    {
      accessorKey: 'status',
      header: 'Status',
      cell: ({ row }) => {
        const status = row.original.status;
        const color = status === 'completed' ? 'text-green-600' : status === 'abandoned' ? 'text-red-600' : 'text-blue-600';
        return <span className={`text-sm font-medium ${color}`}>{status}</span>;
      },
    },
    {
      accessorKey: 'completion_action',
      header: 'Action',
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground">{row.original.completion_action || '\u2014'}</span>
      ),
    },
    {
      accessorKey: 'created_by',
      header: 'User',
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground">{row.original.created_by || '\u2014'}</span>
      ),
    },
    {
      accessorKey: 'created_at',
      header: 'Started',
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground">
          {row.original.created_at ? new Date(row.original.created_at).toLocaleString() : '\u2014'}
        </span>
      ),
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

  const typeFilteredApprovalSessions = useMemo(() => {
    // Approval sessions are always approval type, so only show when filter is 'all' or 'approval'
    if (workflowTypeFilter === 'process') return [];
    return approvalSessions;
  }, [approvalSessions, workflowTypeFilter]);

  // Stats (computed from type-filtered data so they reflect the active tab)
  const activeWorkflows = typeFilteredWorkflows.filter(w => w.is_active).length;
  const totalWorkflows = typeFilteredWorkflows.length;
  const runningExecutions = typeFilteredExecutions.filter(e => e.status === 'running' || e.status === 'paused').length;
  const recentFailures = typeFilteredExecutions.filter(e => e.status === 'failed').length;

  // Stats card filtered data (layered on top of type filtering)
  const filteredWorkflows = useMemo(() => {
    if (statsFilter === 'active') return typeFilteredWorkflows.filter(w => w.is_active);
    if (statsFilter === 'inactive') return typeFilteredWorkflows.filter(w => !w.is_active);
    if (statsFilter === 'default') return typeFilteredWorkflows.filter(w => w.is_default);
    return typeFilteredWorkflows;
  }, [typeFilteredWorkflows, statsFilter]);

  const filteredExecutions = useMemo(() => {
    if (statsFilter === 'running') return typeFilteredExecutions.filter(e => e.status === 'running' || e.status === 'paused');
    if (statsFilter === 'failed') return typeFilteredExecutions.filter(e => e.status === 'failed');
    return typeFilteredExecutions;
  }, [typeFilteredExecutions, statsFilter]);

  // Reset stats filter when workflow type changes
  useEffect(() => { setStatsFilter('all'); }, [workflowTypeFilter]);

  return (
    <SettingsPageWrapper title={t('common:labels.workflows', 'Workflows')}>
      <div className="mb-6">
        <div className="flex justify-between items-start">
          <div>
            <h1 className="text-3xl font-bold flex items-center gap-2">
              <GitBranch className="w-8 h-8" />
              {t('common:labels.workflows', 'Workflows')}
            </h1>
            <p className="text-muted-foreground mt-1">
              Configure automated workflows for validation, approval, and notifications.
            </p>
          </div>
          {canEdit && (
            <div className="flex items-center gap-2">
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline">
                    <Clock className="h-4 w-4 mr-2" />
                    Load Defaults
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuLabel>Default Workflows</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={() => handleLoadDefaultWorkflows(false)}>
                    <Plus className="h-4 w-4 mr-2" />
                    Load New Only
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => handleLoadDefaultWorkflows(true)}>
                    <RotateCcw className="h-4 w-4 mr-2" />
                    Reload All Defaults
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              <Button onClick={() => navigate(`${pathname}/new${workflowTypeFilter !== 'all' ? `?type=${workflowTypeFilter}` : ''}`)}>
                <Plus className="h-4 w-4 mr-2" />
                Create Workflow
              </Button>
            </div>
          )}
        </div>
        <div className="mt-4">
          <Tabs value={workflowTypeFilter} onValueChange={(v) => setWorkflowTypeFilter(v as 'all' | 'process' | 'approval')}>
            <div className="flex items-center gap-3">
              <TabsList className="h-auto p-1">
                <TabsTrigger value="all" className="px-4 py-2">
                  <span>All</span>
                </TabsTrigger>
                <TabsTrigger value="process" className="flex flex-col items-start px-4 py-2">
                  <span>Process</span>
                  <span className="text-[10px] italic text-muted-foreground font-normal">Background automation</span>
                </TabsTrigger>
                <TabsTrigger value="approval" className="flex flex-col items-start px-4 py-2">
                  <span>Approval</span>
                  <span className="text-[10px] italic text-muted-foreground font-normal">Interactive consent</span>
                </TabsTrigger>
              </TabsList>
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <HelpCircle className="h-4 w-4 text-muted-foreground cursor-help" />
                  </TooltipTrigger>
                  <TooltipContent side="right" className="max-w-xs">
                    <ul className="text-xs space-y-1 list-disc pl-3">
                      <li>Process: runs after events (notify, tag, validate)</li>
                      <li>Approval: pops up before actions (consent, terms)</li>
                      <li>They chain: approval first, then process</li>
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
            <CardTitle className="text-lg">Active Workflows</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold text-green-600 dark:text-green-400">{activeWorkflows}</div>
            <p className="text-sm text-muted-foreground mt-1">
              of {totalWorkflows} total
              {totalWorkflows - activeWorkflows > 0 && (
                <button
                  className="ml-1 text-amber-600 hover:underline"
                  onClick={(e) => { e.stopPropagation(); setStatsFilter(prev => prev === 'inactive' ? 'all' : 'inactive'); }}
                >
                  ({totalWorkflows - activeWorkflows} inactive)
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
            <CardTitle className="text-lg">Default Workflows</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{workflows.filter(w => w.is_default).length}</div>
            <p className="text-sm text-muted-foreground mt-1">built-in workflows</p>
          </CardContent>
        </Card>
        <Card
          className={`cursor-pointer transition-colors hover:border-primary ${statsFilter === 'running' ? 'border-primary bg-primary/5' : ''}`}
          onClick={() => setStatsFilter(prev => prev === 'running' ? 'all' : 'running')}
        >
          <CardHeader className="pb-2">
            <CardTitle className="text-lg">In Progress</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold text-blue-600">{runningExecutions}</div>
            <p className="text-sm text-muted-foreground mt-1">running or paused</p>
          </CardContent>
        </Card>
        <Card
          className={`cursor-pointer transition-colors hover:border-primary ${statsFilter === 'failed' ? 'border-primary bg-primary/5' : ''}`}
          onClick={() => setStatsFilter(prev => prev === 'failed' ? 'all' : 'failed')}
        >
          <CardHeader className="pb-2">
            <CardTitle className="text-lg">Recent Failures</CardTitle>
          </CardHeader>
          <CardContent>
            <div className={`text-3xl font-bold ${recentFailures > 0 ? 'text-red-600' : ''}`}>
              {recentFailures}
            </div>
            <p className="text-sm text-muted-foreground mt-1">in last 50 runs</p>
          </CardContent>
        </Card>
      </div>

      {/* Stats filter indicator */}
      {statsFilter !== 'all' && (
        <div className="flex items-center gap-2 mb-4">
          <Badge variant="outline" className="text-sm">
            Filtered: {statsFilter === 'active' ? 'Active workflows' : statsFilter === 'inactive' ? 'Inactive workflows' : statsFilter === 'default' ? 'Default workflows' : statsFilter === 'running' ? 'Running executions' : 'Failed executions'}
          </Badge>
          <button className="text-xs text-muted-foreground hover:text-foreground" onClick={() => setStatsFilter('all')}>
            Clear filter
          </button>
        </div>
      )}

      {/* Workflows Table */}
      <Card className="mb-8">
        <CardHeader>
          <div>
            <CardTitle className="flex items-center gap-2">
              <GitBranch className="h-5 w-5" />
              Workflow Definitions
            </CardTitle>
            <CardDescription>
              Configure automated workflows for validation, approval, and notifications.
              {!canEdit && (
                <span className="text-yellow-600 ml-2">(Read-only access)</span>
              )}
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          {isLoadingWorkflows ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin" />
            </div>
          ) : workflows.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <GitBranch className="h-12 w-12 mx-auto mb-4 opacity-20" />
              <p>No workflows configured yet.</p>
              {canEdit && (
                <p className="text-sm">Click "Load Defaults" to get started with default workflows.</p>
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
                    Enable ({selectedRows.length})
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-9 gap-1"
                    onClick={() => handleBulkToggleWorkflows(selectedRows, false)}
                  >
                    <PowerOff className="w-4 h-4 mr-1" />
                    Disable ({selectedRows.length})
                  </Button>
                  <Button
                    variant="destructive"
                    size="sm"
                    className="h-9 gap-1"
                    onClick={() => handleBulkDeleteWorkflows(selectedRows)}
                  >
                    <Trash2 className="w-4 h-4 mr-1" />
                    Delete ({selectedRows.length})
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
              Recent Executions
            </CardTitle>
            <CardDescription>
              Monitor workflow executions and their status.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          {isLoadingExecutions ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin" />
            </div>
          ) : executions.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <Play className="h-12 w-12 mx-auto mb-4 opacity-20" />
              <p>No workflow executions yet.</p>
              <p className="text-sm">Executions will appear here when workflows are triggered.</p>
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
                    Cancel ({selectedRows.filter(e => e.status === 'running' || e.status === 'paused').length})
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-9 gap-1"
                    onClick={() => handleBulkRetryExecutions(selectedRows)}
                  >
                    <RotateCcw className="w-4 h-4 mr-1" />
                    Retry ({selectedRows.filter(e => e.status === 'failed' || e.status === 'cancelled').length})
                  </Button>
                  <Button
                    variant="destructive"
                    size="sm"
                    className="h-9 gap-1"
                    onClick={() => handleBulkDeleteExecutions(selectedRows)}
                  >
                    <Trash2 className="w-4 h-4 mr-1" />
                    Delete ({selectedRows.filter(e => e.status !== 'running' && e.status !== 'paused').length})
                  </Button>
                </>
              ) : undefined}
            />
          )}
        </CardContent>
      </Card>

      {/* Approval Sessions */}
      {typeFilteredApprovalSessions.length > 0 && (
        <Card className="mt-8">
          <CardHeader>
            <div>
              <CardTitle className="flex items-center gap-2">
                <UserCheck className="h-5 w-5" />
                Approval Sessions
              </CardTitle>
              <CardDescription>
                Wizard sessions from approval workflows (subscribe, request access, etc.).
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            {isLoadingApprovalSessions ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin" />
              </div>
            ) : (
              <DataTable
                columns={approvalSessionColumns}
                data={typeFilteredApprovalSessions}
                searchColumn="workflow_name"
                storageKey="approval-sessions-sort"
              />
            )}
          </CardContent>
        </Card>
      )}

      {/* Duplicate Workflow Dialog */}
      <Dialog open={duplicateDialogOpen} onOpenChange={setDuplicateDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Duplicate Workflow</DialogTitle>
            <DialogDescription>
              Create a copy of "{duplicatingWorkflow?.name}" with a new name.
            </DialogDescription>
          </DialogHeader>
          <div className="py-4">
            <Input
              placeholder="New workflow name"
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
              Duplicate
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

      {/* Delete Execution Confirmation Dialog */}
      <Dialog open={deleteExecutionDialogOpen} onOpenChange={setDeleteExecutionDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Execution</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete this workflow execution? This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          {executionToDelete && (
            <div className="py-4 space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">Workflow:</span>
                <span className="text-sm text-muted-foreground">{executionToDelete.workflow_name}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">Status:</span>
                {getStatusBadge(executionToDelete.status)}
              </div>
              {executionToDelete.entity_name && (
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">Entity:</span>
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
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </SettingsPageWrapper>
  );
}
