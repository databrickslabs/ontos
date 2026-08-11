import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertCircle, Loader2 } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { useToast } from '@/hooks/use-toast';

// ---------------------------------------------------------------------------
// Tag sync configuration dialog for the Enrich view.
//
// Design:
//   - Run mode: "Run once now" vs "On a schedule" (schedule read-only)
//   - Scope: "All concept schemes" vs "Specific schemes" (multi-select)
//   - Primary action:
//     * "Run once now" -> triggers POST /api/jobs/workflows/uc_tag_sync/start
//     * "On a schedule" -> informational (disabled; schedule is read-only)
//
// Real endpoints:
//   - GET /api/jobs/workflows/status -> dict of workflow statuses
//   - GET /api/knowledge/coverage -> returns {schemes: [{scheme, label}]}
//   - POST /api/jobs/workflows/uc_tag_sync/start -> {run_id}
//
// Note: job_parameters.schemes is NOT supported by the start endpoint today
// (per task spec), so scope selection is captured for future use and logged
// as advisory.
// ---------------------------------------------------------------------------

export interface TagSyncDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  hasJobsAdmin: boolean;
}

interface WorkflowStatus {
  installed: boolean;
  job_id?: number;
  is_running?: boolean;
  current_run_id?: number;
  last_result?: string;
  last_ended_at?: string;
  pause_status?: string;
  supports_pause?: boolean;
  schedule?: {
    quartz_cron_expression?: string;
    timezone_id?: string;
  };
}

interface Scheme {
  scheme: string;
  label: string;
}

export default function TagSyncDialog({
  open,
  onOpenChange,
  hasJobsAdmin,
}: TagSyncDialogProps) {
  const { t } = useTranslation(['concepts', 'common']);
  const { toast } = useToast();

  const [runMode, setRunMode] = useState<'now' | 'schedule'>('now');
  const [scopeMode, setScopeMode] = useState<'all' | 'specific'>('all');
  const [selectedSchemes, setSelectedSchemes] = useState<string[]>([]);
  const [schemes, setSchemes] = useState<Scheme[]>([]);
  const [workflowStatus, setWorkflowStatus] = useState<WorkflowStatus | null>(
    null,
  );
  const [isLoading, setIsLoading] = useState(false);
  const [isRunning, setIsRunning] = useState(false);

  // Fetch workflow status and schemes on mount
  useEffect(() => {
    if (!open) return;

    let cancelled = false;

    (async () => {
      try {
        setIsLoading(true);

        // Fetch workflow status
        const statusRes = await fetch('/api/jobs/workflows/status');
        if (statusRes.ok) {
          const statuses = await statusRes.json();
          if (!cancelled && statuses.uc_tag_sync) {
            setWorkflowStatus(statuses.uc_tag_sync);
            // Log for debugging
            console.log('[tag-sync-dialog] workflow status:', statuses.uc_tag_sync);
          }
        }

        // Fetch schemes
        const coverageRes = await fetch('/api/knowledge/coverage');
        if (coverageRes.ok) {
          const coverage = await coverageRes.json();
          if (!cancelled && coverage.schemes && Array.isArray(coverage.schemes)) {
            setSchemes(coverage.schemes);
            // Initialize selected schemes to all
            setSelectedSchemes(coverage.schemes.map((s: any) => s.scheme));
          }
        }
      } catch (err) {
        console.error('[tag-sync-dialog] error fetching status/schemes:', err);
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [open]);

  const isInstalled = workflowStatus?.installed ?? false;
  const scheduleExpression =
    workflowStatus?.schedule?.quartz_cron_expression || 'No schedule set';
  const isWorkflowRunning = workflowStatus?.is_running ?? false;

  // Disable run if: still loading status, no admin, not installed, or running
  const canRunNow =
    !isLoading && hasJobsAdmin && isInstalled && !isWorkflowRunning && !isRunning;
  const disableReason = !hasJobsAdmin
    ? 'Requires admin access'
    : !isInstalled
      ? "Workflow 'uc_tag_sync' not installed"
      : isWorkflowRunning || isRunning
        ? 'Job is currently running'
        : null;

  const handleRunNow = async () => {
    try {
      setIsRunning(true);

      // Log scope for advisory purposes (not passed to start endpoint)
      if (scopeMode === 'specific') {
        console.log(
          '[tag-sync-dialog] scope selection (advisory — not passed to start endpoint):',
          selectedSchemes,
        );
      }

      const res = await fetch('/api/jobs/workflows/uc_tag_sync/start', {
        method: 'POST',
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(
          errorData.detail ||
            `Failed to start workflow (${res.status}: ${res.statusText})`,
        );
      }

      const data = await res.json();
      const runId = data.run_id;

      toast({
        title: 'Tag sync started',
        description: `Workflow run #${runId} is now executing.`,
      });

      onOpenChange(false);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error('[tag-sync-dialog] run failed:', err);
      toast({
        title: 'Failed to start sync',
        description: msg,
        variant: 'destructive',
      });
    } finally {
      setIsRunning(false);
    }
  };

  const primaryActionDisabled = runMode === 'schedule' || !canRunNow;
  const primaryActionLabel = runMode === 'now' ? 'Run now' : 'Configure schedule';

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {t('enrich.tagSync.title', 'Tag sync configuration')}
          </DialogTitle>
          <DialogDescription>
            {t(
              'enrich.tagSync.desc',
              'Sync concept tags to Unity Catalog. Choose a run mode and scope.',
            )}
          </DialogDescription>
        </DialogHeader>

        {/* Load status from workflow status API */}
        {!isInstalled && (
          <div className="flex gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <p className="font-medium">Workflow not installed</p>
              <p className="mt-0.5 text-xs opacity-90">
                {t(
                  'enrich.tagSync.notInstalled',
                  "The 'uc_tag_sync' workflow is not installed. Install it in Settings > Background Jobs first.",
                )}
              </p>
            </div>
          </div>
        )}

        {isWorkflowRunning && (
          <div className="flex gap-2 rounded-lg border border-blue-300 bg-blue-50 p-3 text-sm text-blue-900 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-100">
            <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin" />
            <div>
              <p className="font-medium">Workflow running</p>
              <p className="mt-0.5 text-xs opacity-90">
                {t(
                  'enrich.tagSync.alreadyRunning',
                  'The workflow is already executing (run #{{id}}). Wait for it to finish before starting a new run.',
                  { id: workflowStatus?.current_run_id ?? 'unknown' },
                )}
              </p>
            </div>
          </div>
        )}

        <div className="space-y-4">
          {/* Run mode selector */}
          <div>
            <label className="text-sm font-medium">
              {t('enrich.tagSync.runMode', 'Run mode')}
            </label>
            <div className="mt-2 flex gap-2">
              <button
                type="button"
                className={`flex-1 rounded border px-3 py-2 text-sm font-medium transition ${
                  runMode === 'now'
                    ? 'border-primary bg-primary text-primary-foreground'
                    : 'border-border bg-background hover:border-primary/50'
                }`}
                onClick={() => setRunMode('now')}
              >
                {t('enrich.tagSync.runNow', 'Run once now')}
              </button>
              <button
                type="button"
                className={`flex-1 rounded border px-3 py-2 text-sm font-medium transition ${
                  runMode === 'schedule'
                    ? 'border-primary bg-primary text-primary-foreground'
                    : 'border-border bg-background hover:border-primary/50'
                }`}
                onClick={() => setRunMode('schedule')}
              >
                {t('enrich.tagSync.onSchedule', 'On a schedule')}
              </button>
            </div>
          </div>

          {/* Schedule info (read-only) */}
          {runMode === 'schedule' && (
            <div className="rounded-lg border bg-muted/30 p-3">
              <p className="text-xs font-medium text-muted-foreground">
                {t('enrich.tagSync.currentSchedule', 'Current schedule')}
              </p>
              <div className="mt-1 flex items-center justify-between">
                <code className="text-xs font-mono">
                  {scheduleExpression}
                </code>
                <a
                  href="/settings/background-jobs"
                  className="text-xs font-medium text-sky-700 hover:underline dark:text-sky-400"
                >
                  {t('enrich.tagSync.editSchedule', 'Edit')}
                </a>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                {t(
                  'enrich.tagSync.scheduleNote',
                  'Schedule editing is managed in Settings > Background Jobs.',
                )}
              </p>
            </div>
          )}

          {/* Scope selector */}
          <div>
            <label className="text-sm font-medium">
              {t('enrich.tagSync.scope', 'Scope')}
            </label>
            <div className="mt-2 space-y-2">
              <div className="flex items-center gap-2">
                <input
                  type="radio"
                  id="scope-all"
                  name="scope"
                  value="all"
                  checked={scopeMode === 'all'}
                  onChange={() => setScopeMode('all')}
                  className="h-4 w-4"
                />
                <label htmlFor="scope-all" className="text-sm">
                  {t('enrich.tagSync.allSchemes', 'All concept schemes')}
                </label>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="radio"
                  id="scope-specific"
                  name="scope"
                  value="specific"
                  checked={scopeMode === 'specific'}
                  onChange={() => setScopeMode('specific')}
                  className="h-4 w-4"
                />
                <label htmlFor="scope-specific" className="text-sm">
                  {t(
                    'enrich.tagSync.specificSchemes',
                    'Specific schemes (coming soon)',
                  )}
                </label>
              </div>
            </div>

            {/* Specific schemes multi-select (disabled — advisory placeholder) */}
            {scopeMode === 'specific' && (
              <div className="mt-2 space-y-2 opacity-60">
                <Select disabled>
                  <SelectTrigger>
                    <SelectValue
                      placeholder={t('enrich.tagSync.selectSchemes', 'Select schemes')}
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {schemes.map((scheme) => (
                      <SelectItem key={scheme.scheme} value={scheme.scheme}>
                        {scheme.label || scheme.scheme}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  {t(
                    'enrich.tagSync.scopeAdvisory',
                    'Scheme-level scope selection is captured for future use. Currently, the entire synced configuration is applied.',
                  )}
                </p>
              </div>
            )}
          </div>

          {/* Last run info */}
          {workflowStatus?.last_ended_at && (
            <div className="text-xs text-muted-foreground">
              {t('enrich.tagSync.lastRun', 'Last run')}:{' '}
              <span className="font-medium">
                {new Date(workflowStatus.last_ended_at).toLocaleString()}
              </span>
              {workflowStatus.last_result && (
                <>
                  {' '}
                  <Badge
                    variant="outline"
                    className={
                      workflowStatus.last_result === 'SUCCESS'
                        ? 'border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-200'
                        : 'border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-800 dark:bg-rose-950 dark:text-rose-200'
                    }
                  >
                    {workflowStatus.last_result}
                  </Badge>
                </>
              )}
            </div>
          )}
        </div>

        <DialogFooter className="gap-2">
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isRunning}
          >
            {t('common:close', 'Close')}
          </Button>

          <TooltipProvider>
            <Tooltip open={disableReason ? true : undefined}>
              <TooltipTrigger asChild>
                <span tabIndex={0}>
                  <Button
                    onClick={handleRunNow}
                    disabled={primaryActionDisabled || isRunning}
                  >
                    {isRunning && (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    )}
                    {t('enrich.tagSync.action', primaryActionLabel)}
                  </Button>
                </span>
              </TooltipTrigger>
              {disableReason && (
                <TooltipContent className="max-w-[260px]">
                  {disableReason}
                </TooltipContent>
              )}
            </Tooltip>
          </TooltipProvider>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
