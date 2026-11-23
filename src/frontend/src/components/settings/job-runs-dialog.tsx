import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useApi } from '@/hooks/use-api';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Check, ChevronDown, ChevronRight } from 'lucide-react';
// Collapsible components commented out - not currently used
// import {
//   Collapsible,
//   CollapsibleTrigger,
//   CollapsibleContent,
// } from '@/components/ui/collapsible';
import { WorkflowJobRun, getJobRunStatus, getStatusColor, formatDuration } from '@/types/workflow-job-run';
import { RelativeDate } from '@/components/common/relative-date';
import { ContentSkeleton } from '@/components/common/content-skeleton';

// Stands in for the runs while they load (see ContentSkeleton)
const SAMPLE_RUNS: WorkflowJobRun[] = [
  {
    id: 'sample-1', workflow_installation_id: 'sample', run_id: 1042, run_name: 'Metadata sync',
    life_cycle_state: 'TERMINATED', result_state: 'SUCCESS', state_message: null,
    start_time: 1767000000000, end_time: 1767000300000, duration_ms: 300000, notified_at: null,
    discovered_at: '2026-11-22T08:00:00Z', last_updated_at: '2026-11-22T08:05:00Z',
  },
  {
    id: 'sample-2', workflow_installation_id: 'sample', run_id: 1041, run_name: 'Metadata sync',
    life_cycle_state: 'TERMINATED', result_state: 'FAILED', state_message: 'Cluster terminated',
    start_time: 1766990000000, end_time: 1766990200000, duration_ms: 200000, notified_at: null,
    discovered_at: '2026-11-21T08:00:00Z', last_updated_at: '2026-11-21T08:03:00Z',
  },
];

interface JobRunsDialogProps {
  workflowId: string;
  workflowName: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function JobRunsDialog({ workflowId, workflowName, open, onOpenChange }: JobRunsDialogProps) {
  const { t } = useTranslation(['settings', 'common']);
  const { get } = useApi();
  const [runs, setRuns] = useState<WorkflowJobRun[]>([]);
  // Starts loading: the first open shows the skeleton, not "no runs"
  const [isLoading, setIsLoading] = useState(true);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());

  const toggleExpanded = (runId: string) => {
    setExpandedRows((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(runId)) {
        newSet.delete(runId);
      } else {
        newSet.add(runId);
      }
      return newSet;
    });
  };

  const fetchRuns = async () => {
    setIsLoading(true);
    try {
      const response = await get<WorkflowJobRun[]>(
        `/api/jobs/runs?workflow_id=${encodeURIComponent(workflowId)}&limit=50`
      );
      setRuns(response.data || []);
    } catch (error) {
      console.error('Failed to fetch job runs:', error);
      setRuns([]);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (open) {
      fetchRuns();

      // Auto-refresh every 30 seconds while modal is open
      const interval = setInterval(fetchRuns, 30000);
      return () => clearInterval(interval);
    }
  }, [open, workflowId]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('settings:jobRuns.dialogTitle', { workflowName })}</DialogTitle>
          <DialogDescription>
            {t('settings:jobRuns.dialogDescription')}
          </DialogDescription>
        </DialogHeader>

        <ContentSkeleton
          data={runs}
          sample={SAMPLE_RUNS}
          loading={isLoading && runs.length === 0}
          empty={runs.length === 0}
          emptyMessage={
            <div className="text-center py-8 text-gray-500">
              {t('settings:jobRuns.emptyState')}
            </div>
          }
        >
          {(shownRuns) => (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('settings:jobRuns.runId')}</TableHead>
                  <TableHead>{t('settings:jobRuns.runName')}</TableHead>
                  <TableHead>{t('settings:jobRuns.status')}</TableHead>
                  <TableHead>{t('settings:jobRuns.started')}</TableHead>
                  <TableHead>{t('settings:jobRuns.duration')}</TableHead>
                  <TableHead className="text-center">{t('settings:jobRuns.notified')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {shownRuns.map((run) => {
                  const status = getJobRunStatus(run);
                  const statusColor = getStatusColor(status);
                  const isExpanded = expandedRows.has(run.id);
                  const hasStateMessage = run.state_message && run.state_message.trim() !== '';

                  return (
                    <React.Fragment key={run.id}>
                      <TableRow className="hover:bg-gray-50 dark:hover:bg-gray-800">
                        <TableCell className="font-mono text-sm">{run.run_id}</TableCell>
                        <TableCell>{run.run_name || '-'}</TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            {hasStateMessage && (
                              <button
                                onClick={() => toggleExpanded(run.id)}
                                className="p-0.5 hover:bg-gray-200 dark:hover:bg-gray-700 rounded transition-colors"
                                aria-label={isExpanded ? t('settings:jobRuns.collapseDetails') : t('settings:jobRuns.expandDetails')}
                              >
                                {isExpanded ? (
                                  <ChevronDown className="h-4 w-4 text-gray-600 dark:text-gray-400" />
                                ) : (
                                  <ChevronRight className="h-4 w-4 text-gray-600 dark:text-gray-400" />
                                )}
                              </button>
                            )}
                            <Badge variant="outline" className={`${statusColor} border`}>
                              {t(`settings:jobRuns.statuses.${status.toLowerCase()}`)}
                            </Badge>
                          </div>
                        </TableCell>
                        <TableCell>
                          {run.start_time ? (
                            <RelativeDate date={new Date(run.start_time)} />
                          ) : (
                            '-'
                          )}
                        </TableCell>
                        <TableCell>{formatDuration(run.duration_ms)}</TableCell>
                        <TableCell className="text-center">
                          {run.notified_at ? (
                            <Check className="h-4 w-4 text-green-600 inline" />
                          ) : (
                            <span className="text-gray-300 dark:text-gray-600">-</span>
                          )}
                        </TableCell>
                      </TableRow>
                      {hasStateMessage && isExpanded && (
                        <TableRow className="bg-gray-50 dark:bg-gray-800/50 border-t-0">
                          <TableCell colSpan={6} className="py-3 px-6">
                            <div className="text-sm text-gray-700 dark:text-gray-300">
                              <span className="font-medium text-gray-900 dark:text-white">{t('settings:jobRuns.stateMessage')}</span>
                              <div className="mt-1 p-2 bg-white dark:bg-gray-900 rounded border border-gray-200 dark:border-gray-700 font-mono text-xs whitespace-pre-wrap">
                                {run.state_message}
                              </div>
                            </div>
                          </TableCell>
                        </TableRow>
                      )}
                    </React.Fragment>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </ContentSkeleton>
      </DialogContent>
    </Dialog>
  );
}
