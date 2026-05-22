import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ColumnDef } from '@tanstack/react-table';
import { useToast } from '@/hooks/use-toast';
import { useApi } from '@/hooks/use-api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import { DataTable } from '@/components/ui/data-table';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { JobRunsDialog } from '@/components/settings/job-runs-dialog';
import SettingsActionBar from '@/components/settings/settings-action-bar';
import UnsavedChangesGuard from '@/components/common/unsaved-changes-guard';
import WorkflowActions from '@/components/settings/workflow-actions';
import WorkflowConfigurationDialog from '@/components/settings/workflow-configuration-dialog';
import { WorkflowStatus } from '@/types/workflows';
import { WorkflowParameterDefinition } from '@/types/workflow-configurations';
import { AlertTriangle, Briefcase, ChevronDown, History, Settings as SettingsIcon } from 'lucide-react';

interface SettingsApiResponse {
  job_cluster_id?: string | null;
  enabled_jobs?: string[];
  workspace_deployment_path?: string | null;
  available_workflows?: { id: string; name: string; description?: string }[];
  current_settings?: {
    job_cluster_id?: string | null;
    enabled_jobs?: string[];
    workspace_deployment_path?: string | null;
  };
}

type WorkflowsMap = Record<string, { id: string; name: string; description?: string }>;

interface MergedWorkflow {
  id: string;
  name: string;
  description?: string;
  status: WorkflowStatus;
  enabled: boolean;
}

interface JobsSnapshot {
  jobClusterId: string;
  workspaceDeploymentPath: string;
  enabledJobIds: string[];
}

// Build a stable comparison key for a JobsSnapshot. Sorting `enabledJobIds`
// keeps dirty detection insensitive to set iteration order.
function snapshotKey(snap: JobsSnapshot): string {
  return JSON.stringify({
    ...snap,
    enabledJobIds: [...snap.enabledJobIds].sort(),
  });
}

export default function JobsSettings() {
  const { t } = useTranslation(['settings', 'common']);
  const { toast } = useToast();
  const { get, put, post } = useApi();

  const [jobClusterId, setJobClusterId] = useState<string>('');
  const [workspaceDeploymentPath, setWorkspaceDeploymentPath] = useState<string>('');
  const [workflows, setWorkflows] = useState<WorkflowsMap>({});
  const [enabled, setEnabled] = useState<Record<string, boolean>>({});
  const [statuses, setStatuses] = useState<Record<string, WorkflowStatus>>({});
  const [isSaving, setIsSaving] = useState(false);
  // Last-loaded / last-saved snapshot used to detect unsaved edits.
  const [snapshot, setSnapshot] = useState<JobsSnapshot>({
    jobClusterId: '',
    workspaceDeploymentPath: '',
    enabledJobIds: [],
  });

  // Job runs dialog state
  const [selectedWorkflow, setSelectedWorkflow] = useState<{ id: string; name: string } | null>(null);
  const [jobRunsDialogOpen, setJobRunsDialogOpen] = useState(false);
  
  // Configuration dialog state
  const [configDialogOpen, setConfigDialogOpen] = useState(false);
  const [configurableWorkflows, setConfigurableWorkflows] = useState<Set<string>>(new Set());

  const mergedList = useMemo<MergedWorkflow[]>(() => {
    return Object.values(workflows).map(w => ({
      ...w,
      status: statuses[w.id] || {
        workflow_id: w.id,
        installed: false,
        is_running: false,
        supports_pause: false,
      },
      enabled: !!enabled[w.id],
    }));
  }, [workflows, statuses, enabled]);

  useEffect(() => {
    const load = async () => {
      try {
        const response = await get<SettingsApiResponse>('/api/settings');
        const data = response.data || {};
        const clusterId = data.job_cluster_id ?? data.current_settings?.job_cluster_id ?? '';
        const loadedClusterId = clusterId || '';
        setJobClusterId(loadedClusterId);
        const deploymentPath = data.workspace_deployment_path ?? data.current_settings?.workspace_deployment_path ?? '';
        const loadedPath = deploymentPath || '';
        setWorkspaceDeploymentPath(loadedPath);
        const wfList = data.available_workflows || [];
        const wfMap: WorkflowsMap = {};
        wfList.forEach(w => { wfMap[w.id] = w; });
        setWorkflows(wfMap);
        const loadedEnabledIds = data.enabled_jobs || data.current_settings?.enabled_jobs || [];
        const enabledSet = new Set<string>(loadedEnabledIds);
        const toggles: Record<string, boolean> = {};
        wfList.forEach(w => { toggles[w.id] = enabledSet.has(w.id); });
        setEnabled(toggles);
        setSnapshot({
          jobClusterId: loadedClusterId,
          workspaceDeploymentPath: loadedPath,
          enabledJobIds: wfList.map(w => w.id).filter(id => enabledSet.has(id)),
        });
        
        const configurable = new Set<string>();
        for (const wf of wfList) {
          try {
            const defsResponse = await get<WorkflowParameterDefinition[]>(
              `/api/jobs/workflows/${encodeURIComponent(wf.id)}/parameter-definitions`
            );
            if (defsResponse.data && defsResponse.data.length > 0) {
              configurable.add(wf.id);
            }
          } catch (e) {
            console.debug(`No configurable parameters for ${wf.id}`);
          }
        }
        setConfigurableWorkflows(configurable);
      } catch (e) {
        console.error('Error loading settings', e);
      }
    };
    load();
  }, [get]);

  // Poll workflow statuses
  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await get<Record<string, WorkflowStatus>>('/api/jobs/workflows/statuses');
        if (!cancelled && res.data) {
          setStatuses(prev => {
            if (JSON.stringify(prev) === JSON.stringify(res.data)) return prev;
            return res.data!;
          });
        }
      } catch (e) {
        if (!cancelled) {
          toast({ title: t('common:status.error'), description: 'Failed to fetch workflow statuses', variant: 'destructive' });
        }
      }
    };
    poll();
    const id = setInterval(poll, 10000);
    return () => { cancelled = true; clearInterval(id); };
  }, [get, toast, t]);

  const hasPath = workspaceDeploymentPath.trim().length > 0;

  const currentEnabledIds = useMemo(
    () => Object.entries(enabled).filter(([, v]) => v).map(([k]) => k),
    [enabled]
  );

  const isDirty = useMemo(() => {
    return (
      snapshotKey(snapshot) !==
      snapshotKey({
        jobClusterId,
        workspaceDeploymentPath,
        enabledJobIds: currentEnabledIds,
      })
    );
  }, [snapshot, jobClusterId, workspaceDeploymentPath, currentEnabledIds]);

  const handleCancel = () => {
    setJobClusterId(snapshot.jobClusterId);
    setWorkspaceDeploymentPath(snapshot.workspaceDeploymentPath);
    const restoreSet = new Set(snapshot.enabledJobIds);
    setEnabled(prev => {
      const next: Record<string, boolean> = {};
      Object.keys(prev).forEach(id => { next[id] = restoreSet.has(id); });
      return next;
    });
  };

  const handleSave = async () => {
    if (currentEnabledIds.length > 0 && !hasPath) {
      toast({
        title: t('common:status.error'),
        description: t('settings:jobs.workspaceDeploymentPath.requiredHint'),
        variant: 'destructive',
      });
      return;
    }
    setIsSaving(true);
    try {
      const trimmedPath = workspaceDeploymentPath.trim();
      const payload = {
        job_cluster_id: jobClusterId || null,
        workspace_deployment_path: trimmedPath || null,
        enabled_jobs: currentEnabledIds,
      };
      const response = await put('/api/settings', payload);
      if (response.error) {
        toast({ title: t('common:status.error'), description: response.error, variant: 'destructive' });
        return;
      }
      // Refresh snapshot to the persisted values so isDirty resets to false.
      setSnapshot({
        jobClusterId,
        workspaceDeploymentPath: trimmedPath,
        enabledJobIds: currentEnabledIds,
      });
      toast({ title: t('common:status.success'), description: t('settings:jobs.messages.saveSuccess') });
    } catch (e: any) {
      toast({ title: t('common:status.error'), description: e?.message || 'Failed to save', variant: 'destructive' });
    } finally {
      setIsSaving(false);
    }
  };

  const toggleWorkflow = (workflowId: string) => {
    setEnabled(prev => ({ ...prev, [workflowId]: !prev[workflowId] }));
  };

  const startRun = async (workflowId: string) => {
    try {
      const res = await post(`/api/jobs/workflows/${encodeURIComponent(workflowId)}/start`, {});
      if (res.error) throw new Error(res.error);
      toast({ title: t('common:status.success'), description: 'Started run' });
    } catch (e: any) {
      toast({ title: t('common:status.error'), description: e?.message || 'Failed to start', variant: 'destructive' });
    }
  };

  const stopRun = async (workflowId: string) => {
    try {
      const res = await post(`/api/jobs/workflows/${encodeURIComponent(workflowId)}/stop`, {});
      if (res.error) throw new Error(res.error);
      toast({ title: t('common:status.success'), description: 'Stopped run' });
    } catch (e: any) {
      toast({ title: t('common:status.error'), description: e?.message || 'Failed to stop', variant: 'destructive' });
    }
  };

  const pauseSchedule = async (workflowId: string) => {
    try {
      const res = await post(`/api/jobs/workflows/${encodeURIComponent(workflowId)}/pause`, {});
      if (res.error) throw new Error(res.error);
      toast({ title: t('common:status.success'), description: 'Paused schedule' });
    } catch (e: any) {
      toast({ title: t('common:status.error'), description: e?.message || 'Failed to pause', variant: 'destructive' });
    }
  };

  const resumeSchedule = async (workflowId: string) => {
    try {
      const res = await post(`/api/jobs/workflows/${encodeURIComponent(workflowId)}/resume`, {});
      if (res.error) throw new Error(res.error);
      toast({ title: t('common:status.success'), description: 'Resumed schedule' });
    } catch (e: any) {
      toast({ title: t('common:status.error'), description: e?.message || 'Failed to resume', variant: 'destructive' });
    }
  };

  const columns = useMemo<ColumnDef<MergedWorkflow>[]>(() => [
    {
      accessorKey: 'name',
      header: ({ column }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}>
          {t('settings:jobs.table.name', 'Name')} <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => (
        <span className="font-medium">{row.original.name}</span>
      ),
    },
    {
      accessorKey: 'description',
      header: t('settings:jobs.table.description', 'Description'),
      cell: ({ row }) => (
        <div className="truncate max-w-sm text-sm text-muted-foreground">
          {row.original.description || '-'}
        </div>
      ),
    },
    {
      id: 'status',
      header: t('settings:jobs.table.status', 'Status'),
      cell: ({ row }) => {
        const { status } = row.original;
        if (!status.installed) {
          return <Badge variant="outline">{t('settings:jobs.table.notInstalled', 'Not Installed')}</Badge>;
        }
        if (status.is_running) {
          return <Badge variant="default">{t('settings:jobs.table.running', 'Running')}</Badge>;
        }
        switch (status.last_result) {
          case 'SUCCESS':
            return <Badge variant="default" className="bg-green-600">{t('settings:jobs.table.success', 'Success')}</Badge>;
          case 'FAILED':
            return <Badge variant="destructive">{t('settings:jobs.table.failed', 'Failed')}</Badge>;
          case 'CANCELED':
            return <Badge variant="secondary">{t('settings:jobs.table.canceled', 'Canceled')}</Badge>;
          case 'TIMEDOUT':
            return <Badge variant="secondary">{t('settings:jobs.table.timedOut', 'Timed Out')}</Badge>;
          default:
            return <Badge variant="secondary">{t('settings:jobs.table.idle', 'Idle')}</Badge>;
        }
      },
      enableSorting: false,
    },
    {
      id: 'enabled',
      header: t('settings:jobs.table.enabled', 'Enabled'),
      cell: ({ row }) => (
        <Switch
          checked={row.original.enabled}
          onCheckedChange={() => toggleWorkflow(row.original.id)}
          disabled={row.original.status?.is_running || (!hasPath && !row.original.enabled)}
        />
      ),
      enableSorting: false,
    },
    {
      id: 'actions',
      header: () => <div className="text-right">{t('settings:jobs.table.actions', 'Actions')}</div>,
      cell: ({ row }) => {
        const wf = row.original;
        return (
          <div className="flex items-center justify-end gap-1">
            {wf.status?.installed && wf.enabled && (
              <WorkflowActions
                status={wf.status}
                onStart={() => startRun(wf.id)}
                onStop={() => stopRun(wf.id)}
                onPause={() => pauseSchedule(wf.id)}
                onResume={() => resumeSchedule(wf.id)}
              />
            )}

            {wf.status?.installed && (
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => { setSelectedWorkflow({ id: wf.id, name: wf.name }); setJobRunsDialogOpen(true); }}
                aria-label="History"
                title={t('settings:jobRuns.viewHistory')}
              >
                <History className="h-4 w-4" />
              </Button>
            )}

            {configurableWorkflows.has(wf.id) && (
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => { setSelectedWorkflow({ id: wf.id, name: wf.name }); setConfigDialogOpen(true); }}
                aria-label="Configure"
                title="Configure workflow parameters"
              >
                <SettingsIcon className="h-4 w-4" />
              </Button>
            )}
          </div>
        );
      },
      enableSorting: false,
    },
  ], [configurableWorkflows, hasPath, t]);

  return (
    <>
      <div className="mb-6">
        <h1 className="text-3xl font-bold flex items-center gap-2">
          <Briefcase className="w-8 h-8" />
          {t('settings:jobs.title')}
        </h1>
        <p className="text-muted-foreground mt-1">{t('settings:jobs.description')}</p>
      </div>

      <div className="space-y-4 mb-6">
        <div className="space-y-2">
          <Label htmlFor="job-cluster-id">{t('settings:jobs.jobClusterId.label')}</Label>
          <Input id="job-cluster-id" value={jobClusterId} onChange={(e) => setJobClusterId(e.target.value)} placeholder={t('settings:jobs.jobClusterId.placeholder')} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="workspace-deployment-path">
            {t('settings:jobs.workspaceDeploymentPath.label')}
          </Label>
          <Input
            id="workspace-deployment-path"
            value={workspaceDeploymentPath}
            onChange={(e) => setWorkspaceDeploymentPath(e.target.value)}
            placeholder={t('settings:jobs.workspaceDeploymentPath.placeholder')}
          />
          <p className="text-sm text-muted-foreground">
            {t('settings:jobs.workspaceDeploymentPath.help')}
          </p>
          {!hasPath && (
            <Alert variant="default">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>
                {t('settings:jobs.workspaceDeploymentPath.requiredHint')}
              </AlertDescription>
            </Alert>
          )}
        </div>
      </div>

      <DataTable
        columns={columns}
        data={mergedList}
        searchColumn="name"
        storageKey="jobs-workflows-sort"
      />

      <SettingsActionBar
        isDirty={isDirty}
        isSaving={isSaving}
        onSave={handleSave}
        onCancel={handleCancel}
        saveLabel={t('settings:jobs.saveButton')}
      />
      <UnsavedChangesGuard isDirty={isDirty} />

      {selectedWorkflow && (
        <JobRunsDialog
          workflowId={selectedWorkflow.id}
          workflowName={selectedWorkflow.name}
          open={jobRunsDialogOpen}
          onOpenChange={setJobRunsDialogOpen}
        />
      )}

      {selectedWorkflow && (
        <WorkflowConfigurationDialog
          workflowId={selectedWorkflow.id}
          workflowName={selectedWorkflow.name}
          open={configDialogOpen}
          onOpenChange={setConfigDialogOpen}
        />
      )}
    </>
  );
}
