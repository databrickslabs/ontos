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
import { Check, Loader2, ChevronDown, ChevronRight } from 'lucide-react';
// Collapsible components commented out - not currently used
// import {
//   Collapsible,
//   CollapsibleTrigger,
//   CollapsibleContent,
// } from '@/components/ui/collapsible';
import { WorkflowJobRun, getJobRunStatus, getStatusColor, formatDuration } from '@/types/workflow-job-run';
import { RelativeDate } from '@/components/common/relative-date';

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
  const [isLoading, setIsLoading] = useState(false);
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

        {isLoading && runs.length === 0 ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
          </div>
        ) : runs.length === 0 ? (
          <div className="text-center py-8 text-gray-500">
            {t('settings:jobRuns.emptyState')}
          </div>
        ) : (
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
              {runs.map((run) => {
                const status = getJobRunStatus(run);
                const statusColor = getStatusColor(status);
                const isExpanded = expandedRows.has(run.id);
                const hasStateMessage = run.state_message && run.state_message.trim() !== '';

                return (
                  <React.Fragment key={run.id}>
                    <TableRow className="hover:bg-gray-50">
                      <TableCell className="font-mono text-sm">{run.run_id}</TableCell>
                      <TableCell>{run.run_name || '-'}</TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          {hasStateMessage && (
                            <button
                              onClick={() => toggleExpanded(run.id)}
                              className="p-0.5 hover:bg-gray-200 rounded transition-colors"
                              aria-label={isExpanded ? 'Collapse details' : 'Expand details'}
                            >
                              {isExpanded ? (
                                <ChevronDown className="h-4 w-4 text-gray-600" />
                              ) : (
                                <ChevronRight className="h-4 w-4 text-gray-600" />
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
                          <span className="text-gray-300">-</span>
                        )}
                      </TableCell>
                    </TableRow>
                    {hasStateMessage && isExpanded && (
                      <TableRow className="bg-gray-50 border-t-0">
                        <TableCell colSpan={6} className="py-3 px-6">
                          <div className="text-sm text-gray-700">
                            <span className="font-medium text-gray-900">State Message:</span>
                            <div className="mt-1 p-2 bg-white rounded border border-gray-200 font-mono text-xs whitespace-pre-wrap">
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
      </DialogContent>
    </Dialog>
  );
}
