import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { AlertCircle, Loader2, Plus, RefreshCw, Sparkles } from 'lucide-react';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { RelativeDate } from '@/components/common/relative-date';
import NewRunDialog from '@/components/metadata-generation/new-run-dialog';
import RunStatusBadge from '@/components/metadata-generation/run-status-badge';
import { useApi } from '@/hooks/use-api';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import type { GenerationRunSummary } from '@/types/metadata-generation';

const FEATURE_ID = 'metadata-generation';

export default function MetadataGenerationView() {
  const { t } = useTranslation(['metadata-generation', 'common']);
  const { get } = useApi();
  const navigate = useNavigate();
  const { hasPermission } = usePermissions();
  const canWrite = hasPermission(FEATURE_ID, FeatureAccessLevel.READ_WRITE);
  const setStaticSegments = useBreadcrumbStore((s) => s.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((s) => s.setDynamicTitle);

  const [runs, setRuns] = useState<GenerationRunSummary[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isNewRunOpen, setIsNewRunOpen] = useState(false);

  useEffect(() => {
    setStaticSegments([]);
    setDynamicTitle(null);
  }, [setStaticSegments, setDynamicTitle]);

  const fetchRuns = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    const res = await get<{ runs: GenerationRunSummary[] }>('/api/metadata-generation/runs?limit=100');
    if (res.error) {
      setError(res.error);
    } else {
      setRuns(res.data?.runs ?? []);
    }
    setIsLoading(false);
  }, [get]);

  useEffect(() => {
    void fetchRuns();
  }, [fetchRuns]);

  const describeSelection = (run: GenerationRunSummary) => {
    const [first, ...rest] = run.selection;
    if (!first) return '';
    return rest.length > 0 ? t('list.selectionMore', { first: first.fqn, count: rest.length }) : first.fqn;
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-2xl font-semibold flex items-center gap-2">
            <Sparkles className="h-6 w-6" /> {t('title')}
          </h1>
          <p className="text-sm text-muted-foreground">{t('subtitle')}</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => void fetchRuns()} disabled={isLoading}>
            <RefreshCw className="h-4 w-4 mr-1" /> {t('common:actions.refresh')}
          </Button>
          {canWrite && (
            <Button size="sm" onClick={() => setIsNewRunOpen(true)}>
              <Plus className="h-4 w-4 mr-1" /> {t('actions.newRun')}
            </Button>
          )}
        </div>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardContent className="p-0">
          {isLoading && runs.length === 0 ? (
            <div className="flex justify-center py-10">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : runs.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-10">{t('list.empty')}</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('list.columns.selection')}</TableHead>
                  <TableHead>{t('list.columns.status')}</TableHead>
                  <TableHead className="text-right">{t('list.columns.suggestions')}</TableHead>
                  <TableHead>{t('list.columns.startedBy')}</TableHead>
                  <TableHead>{t('list.columns.created')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {runs.map((run) => (
                  <TableRow
                    key={run.run_id}
                    className="cursor-pointer"
                    onClick={() => navigate(`/metadata-generation/runs/${run.run_id}`)}
                  >
                    <TableCell className="font-mono text-xs">{describeSelection(run)}</TableCell>
                    <TableCell>
                      <RunStatusBadge status={run.status} />
                    </TableCell>
                    <TableCell className="text-right">{run.suggestion_count}</TableCell>
                    <TableCell className="text-sm">{run.user_id}</TableCell>
                    <TableCell className="text-sm">
                      <RelativeDate date={run.created_at} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <NewRunDialog
        isOpen={isNewRunOpen}
        onOpenChange={setIsNewRunOpen}
        onStarted={(runId) => navigate(`/metadata-generation/runs/${runId}`)}
      />
    </div>
  );
}
